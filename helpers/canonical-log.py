#!/usr/bin/env python3
"""
canonical-log.py — emit one OTel GenAI canonical log line per assistant turn.

Walks every Claude Code session JSONL under /root/.claude/projects/-opt-*/,
groups entries by message.id (one API turn = one canonical row), and appends
newly seen turns to /var/log/token-usage.jsonl in OpenTelemetry GenAI
semantic-convention field names (draft spec, 2026; see
opentelemetry.io/docs/specs/semconv/gen-ai/).

State tracking: /var/run/canonical-log.state records the highest file offset
already ingested per session file, so re-runs produce zero duplicates.
Intended to run every 30 min via cron. Pure stdlib, no pip deps.
"""
import json
import glob
import os
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- Constants --
PROJECTS_GLOB = "/root/.claude/projects/-opt-*/*.jsonl"
OUTPUT_LOG = Path("/var/log/token-usage.jsonl")
STATE_FILE = Path("/var/run/canonical-log.state")
GEN_AI_SYSTEM = "anthropic"
GEN_AI_OPERATION = "chat"
# A very large JSONL line is almost always noise (huge paste, binary blob).
# Skip rather than risk a JSON parser OOM.
MAX_LINE_BYTES = 5_000_000


# ---------------------------------------------------------------- Helpers --
def load_state() -> dict:
    """Return {session_file_path: last_byte_offset_processed}."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as exc:
        sys.stderr.write(f"canonical-log: state file unreadable ({exc}); "
                         "starting from zero.\n")
        return {}


def save_state(state: dict) -> None:
    """Atomic replace — never leave a half-written state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STATE_FILE.parent),
                               prefix=".canonical-log.state.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def project_from_path(session_path: str) -> str:
    """/root/.claude/projects/-opt-abs-dashboard/xxx.jsonl -> 'abs-dashboard'."""
    parent = Path(session_path).parent.name  # e.g. "-opt-abs-dashboard"
    return parent.removeprefix("-opt-") or parent


def iter_new_entries(session_path: str, start_offset: int):
    """Yield (entry_dict, end_offset) for JSONL lines past start_offset.

    end_offset is the byte position AFTER the yielded line — that's what we
    persist to state so the next run resumes from there.
    """
    try:
        fh = open(session_path, "rb")
    except FileNotFoundError:
        return
    with fh:
        try:
            fh.seek(start_offset)
        except OSError:
            fh.seek(0)
        while True:
            line = fh.readline()
            if not line:
                break
            end_offset = fh.tell()
            if len(line) > MAX_LINE_BYTES:
                sys.stderr.write(
                    f"canonical-log: skipping {len(line)}-byte line in "
                    f"{session_path}\n")
                yield None, end_offset
                continue
            try:
                yield json.loads(line), end_offset
            except Exception:
                # Unparseable — skip the line but advance the offset so we
                # don't re-try it forever.
                yield None, end_offset


def count_tool_calls(content) -> tuple[int, dict]:
    """Return (total_tool_calls, {tool_name: count}) from message.content."""
    if not isinstance(content, list):
        return 0, {}
    mix: Counter = Counter()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name") or "unknown"
            mix[name] += 1
    return sum(mix.values()), dict(mix)


def detect_agent_name(entry: dict) -> str | None:
    """Best-effort subagent-name extraction.

    Claude Code doesn't tag subagent turns with an explicit name field today;
    isSidechain=true marks sidechain (Task-tool) dispatches, and the root
    message's `parent_tool_use_id` ties a sidechain back to its parent tool
    call. Agent name itself isn't in the JSONL — leave null when not known
    rather than guess. Downstream consumers can join on conversation.id if
    they need the mapping.
    """
    # Direct fields (future-proof if Claude Code starts emitting them).
    for key in ("agentName", "agent_name", "subagent", "agent"):
        value = entry.get(key)
        if value:
            return str(value)
    return None


def build_canonical_row(first_entry: dict, msg_group: list[dict]) -> dict | None:
    """Given every raw entry sharing one message.id, emit one canonical row.

    Returns None when the group carries no usage (e.g. API error turns).
    """
    # Usage is identical across duplicated entries for the same msg id —
    # take the first non-empty.
    usage = None
    content_all: list = []
    for entry in msg_group:
        msg = entry.get("message") or {}
        if usage is None:
            maybe = msg.get("usage")
            if isinstance(maybe, dict) and maybe:
                usage = maybe
        c = msg.get("content")
        if isinstance(c, list):
            content_all.extend(c)
    if not usage:
        return None

    # Duration: last-timestamp minus first-timestamp within the group. All
    # entries for a msg id usually share the same server timestamp, so this
    # is often 0 — still useful as a placeholder column.
    timestamps = [e.get("timestamp") for e in msg_group if e.get("timestamp")]
    duration_ms = 0
    if len(timestamps) >= 2:
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            tn = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            duration_ms = max(0, int((tn - t0).total_seconds() * 1000))
        except Exception:
            duration_ms = 0

    tool_calls, tool_mix = count_tool_calls(content_all)
    msg = first_entry.get("message") or {}
    session_id = first_entry.get("sessionId")

    return {
        "ts": first_entry.get("timestamp"),
        "gen_ai.system": GEN_AI_SYSTEM,
        "gen_ai.request.model": msg.get("model"),
        "gen_ai.operation.name": GEN_AI_OPERATION,
        "gen_ai.response.id": msg.get("id"),
        "gen_ai.usage.input_tokens": usage.get("input_tokens", 0),
        "gen_ai.usage.output_tokens": usage.get("output_tokens", 0),
        "gen_ai.usage.cache_read_input_tokens":
            usage.get("cache_read_input_tokens", 0),
        "gen_ai.usage.cache_creation_input_tokens":
            usage.get("cache_creation_input_tokens", 0),
        "gen_ai.agent.name": detect_agent_name(first_entry),
        "gen_ai.session.id": session_id,
        "gen_ai.conversation.id": session_id,
        "parent_tool_use_id": first_entry.get("parent_tool_use_id"),
        "project": project_from_path(first_entry.get("__session_path", "")),
        "cwd": first_entry.get("cwd"),
        "tool_calls": tool_calls,
        "tool_mix": tool_mix,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------- Main --
def load_existing_message_ids() -> set:
    """Scan the output log once at startup to guarantee no duplicate rows
    even if state is deleted."""
    if not OUTPUT_LOG.exists():
        return set()
    ids: set = set()
    try:
        with OUTPUT_LOG.open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                rid = row.get("gen_ai.response.id")
                if rid:
                    ids.add(rid)
    except Exception as exc:
        sys.stderr.write(f"canonical-log: could not read {OUTPUT_LOG} "
                         f"({exc}); treating as empty.\n")
    return ids


def main() -> int:
    OUTPUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    state = load_state()
    seen_ids = load_existing_message_ids()
    new_rows = 0

    # Sort session files for deterministic ordering in the output log.
    session_paths = sorted(glob.glob(PROJECTS_GLOB))
    # Open output in append mode once; write is line-buffered for crash safety.
    with OUTPUT_LOG.open("a", buffering=1) as out_fh:
        for path in session_paths:
            start_offset = state.get(path, 0)
            # Group entries by message.id within this file.
            groups: dict[str, list[dict]] = {}
            first_seen: dict[str, dict] = {}
            last_offset = start_offset
            for entry, end_offset in iter_new_entries(path, start_offset):
                last_offset = end_offset
                if entry is None:
                    continue
                if entry.get("type") != "assistant":
                    continue
                msg = entry.get("message") or {}
                mid = msg.get("id")
                if not mid:
                    continue
                if mid in seen_ids:
                    continue
                # Annotate so downstream helpers can recover the project.
                entry["__session_path"] = path
                groups.setdefault(mid, []).append(entry)
                first_seen.setdefault(mid, entry)
            # Emit in first-seen order.
            for mid, entry in first_seen.items():
                try:
                    row = build_canonical_row(entry, groups[mid])
                except Exception:
                    sys.stderr.write(
                        f"canonical-log: failed to build row for {mid}:\n"
                        + traceback.format_exc())
                    continue
                if row is None:
                    continue
                out_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                seen_ids.add(mid)
                new_rows += 1
            state[path] = last_offset

    save_state(state)
    sys.stdout.write(f"canonical-log: wrote {new_rows} new rows to "
                     f"{OUTPUT_LOG}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
