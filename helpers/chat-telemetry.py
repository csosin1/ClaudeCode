#!/usr/bin/env python3
"""
chat-telemetry.py — walk every project's Claude JSONLs, compute:
  - per-chat token totals (today, last 7d, all-time) + approximate $ cost
  - per-SKILLS-file access counts (today, last 7d, all-time)
Output:
  /var/www/landing/tokens.json
  /var/www/landing/skills-usage.json
Intended to run every 30 min via cron. Full scan is idempotent; cost is
<1 sec per MB of JSONL on this droplet.
"""
import json
import glob
import os
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECTS_ROOT = Path("/root/.claude/projects")
CONF = Path("/etc/claude-projects.conf")
TOKENS_OUT = Path("/var/www/landing/tokens.json")
SKILLS_OUT = Path("/var/www/landing/skills-usage.json")
SKILLS_DIR = "/opt/site-deploy/SKILLS"

# Pricing (rough, Claude Opus / Sonnet average — adjust when model detection stabilizes)
# $ per 1M tokens
PRICE = {
    "claude-opus-4-6":    {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-6":  {"input":  3.00, "output": 15.00, "cache_read": 0.30, "cache_write":  3.75},
    "default":            {"input":  5.00, "output": 25.00, "cache_read": 0.50, "cache_write":  6.25},
}

# -----------------------------------------------------------------------------
# Project name from jsonl directory.
# Directories are /root/.claude/projects/-opt-<project>[-subdir...]
# Map directory slugs to the chat names in /etc/claude-projects.conf.
# -----------------------------------------------------------------------------
def load_projects():
    projects = {}
    if not CONF.exists():
        return projects
    for line in CONF.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            name, cwd = parts[0], parts[1]
            slug = cwd.replace("/", "-").lstrip("-")
            projects[slug] = name
    return projects

def cost_for(model, usage):
    p = PRICE.get(model) or PRICE["default"]
    input_tok = usage.get("input_tokens", 0)
    output_tok = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)
    dollars = (
        input_tok    * p["input"]      / 1_000_000 +
        output_tok   * p["output"]     / 1_000_000 +
        cache_read   * p["cache_read"] / 1_000_000 +
        cache_write  * p["cache_write"]/ 1_000_000
    )
    return dollars

def parse_ts(s):
    if not s:
        return None
    try:
        # JSONLs use ISO with Z or +00:00
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

SKILLS_RE = re.compile(r"SKILLS/([a-z0-9_\-]+)\.md", re.IGNORECASE)

def bucket(ts, now):
    """Return which time buckets this ts belongs to."""
    if not ts:
        return ()
    age = now - ts
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    buckets = []
    if ts >= today_start:
        buckets.append("today")
    if age <= timedelta(days=7):
        buckets.append("last_7d")
    if age <= timedelta(days=30):
        buckets.append("last_30d")
    buckets.append("all_time")
    return buckets

def scan_jsonl(path, now, token_totals, skills_hits):
    """Walk one JSONL, aggregating tokens and SKILLS references."""
    try:
        fp = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fp:
        for line in fp:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message") or {}
            ts = parse_ts(d.get("timestamp"))
            buckets = bucket(ts, now)

            # Token usage — only on assistant messages
            if d.get("type") == "assistant":
                usage = msg.get("usage") or {}
                model = msg.get("model") or "default"
                for b in buckets:
                    token_totals[b]["input"]   += usage.get("input_tokens", 0)
                    token_totals[b]["output"]  += usage.get("output_tokens", 0)
                    token_totals[b]["cache_r"] += usage.get("cache_read_input_tokens", 0)
                    token_totals[b]["cache_w"] += usage.get("cache_creation_input_tokens", 0)
                    token_totals[b]["cost"]   += cost_for(model, usage)
                    token_totals[b]["messages"] += 1

            # SKILLS references — in tool_use content OR in user-visible text
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    # Read / Edit / Write / Grep paths
                    input_ = c.get("input") or {}
                    path_val = input_.get("file_path") or input_.get("path") or ""
                    if "SKILLS/" in path_val:
                        m = SKILLS_RE.search(path_val)
                        if m:
                            for b in buckets:
                                skills_hits[m.group(1).lower()][b] += 1
                    # Grep pattern that references SKILLS
                    pattern = input_.get("pattern") or ""
                    if "SKILLS/" in pattern:
                        # Count as a general browse, not a specific file
                        for b in buckets:
                            skills_hits["__grep_across__"][b] += 1
                    # Text content that cites a SKILLS file (assistant reasoning)
                    if c.get("type") == "text":
                        for m in SKILLS_RE.finditer(c.get("text", "")):
                            for b in buckets:
                                skills_hits[m.group(1).lower()][b] += 1

def list_all_skills():
    """Include even skills that were never accessed, so dead letters show up."""
    return sorted({
        Path(p).stem for p in glob.glob(f"{SKILLS_DIR}/*.md")
    })

def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)

def build_dispatcher_map():
    """Pass 1: for each subagent session JSONL, find the project slug where its
    dispatching Task tool_use lives. Subagent tokens attribute to the dispatcher
    (who's responsible for the work), not to the cwd where the subagent
    happened to run. Fixes "infra chat shows $6 despite heavy dispatches" where
    infra's subagents land in opt-site-deploy's bucket because that was cwd.

    Returns: {jsonl_path_str: dispatcher_slug}

    Single-level resolution. Transitive (subagent-of-subagent) falls through to
    direct parent. Rare at our scale; acceptable limitation.
    """
    # First: collect tool_use_id -> slug_where_dispatched, for every Task tool_use
    tool_use_to_slug = {}
    for proj_dir in PROJECTS_ROOT.glob("-*"):
        slug = proj_dir.name.lstrip("-")
        for jsonl in proj_dir.glob("*.jsonl"):
            try:
                fp = open(jsonl, "r", encoding="utf-8", errors="replace")
            except OSError:
                continue
            with fp:
                for line in fp:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    msg = d.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Task":
                                tu_id = c.get("id")
                                if tu_id:
                                    tool_use_to_slug[tu_id] = slug

    # Second: for each JSONL, find its parent_tool_use_id; map to dispatcher slug
    jsonl_dispatcher = {}
    for proj_dir in PROJECTS_ROOT.glob("-*"):
        for jsonl in proj_dir.glob("*.jsonl"):
            try:
                fp = open(jsonl, "r", encoding="utf-8", errors="replace")
            except OSError:
                continue
            parent_tu_id = None
            with fp:
                for line in fp:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    parent_tu_id = d.get("parentToolUseID") or d.get("parent_tool_use_id")
                    if parent_tu_id:
                        break
            if parent_tu_id and parent_tu_id in tool_use_to_slug:
                jsonl_dispatcher[str(jsonl)] = tool_use_to_slug[parent_tu_id]
    return jsonl_dispatcher


def main():
    now = datetime.now(timezone.utc)
    projects = load_projects()
    dispatcher_map = build_dispatcher_map()

    # Per-chat data keyed by effective slug (= dispatcher slug if this JSONL is
    # a subagent session, else the cwd slug)
    per_chat_raw = defaultdict(lambda: {
        "token_totals": {
            b: {"input": 0, "output": 0, "cache_r": 0, "cache_w": 0, "cost": 0.0, "messages": 0}
            for b in ("today", "last_7d", "last_30d", "all_time")
        },
        "skills_hits": defaultdict(lambda: defaultdict(int)),
    })
    skills_hits_global = defaultdict(lambda: defaultdict(int))

    for proj_dir in PROJECTS_ROOT.glob("-*"):
        cwd_slug = proj_dir.name.lstrip("-")
        for jsonl in proj_dir.glob("*.jsonl"):
            effective_slug = dispatcher_map.get(str(jsonl), cwd_slug)
            bucket_data = per_chat_raw[effective_slug]
            scan_jsonl(jsonl, now, bucket_data["token_totals"], bucket_data["skills_hits"])

    per_chat = {}
    for slug, bucket_data in per_chat_raw.items():
        chat_name = projects.get(slug, slug)
        token_totals = bucket_data["token_totals"]
        chat_skills_hits = bucket_data["skills_hits"]

        # Merge into globals
        for skill, buckets in chat_skills_hits.items():
            for b, n in buckets.items():
                skills_hits_global[skill][b] += n

        # Only include this chat in the per-chat report if it has any activity
        # OR if it's a tracked expected project.
        if token_totals["all_time"]["messages"] > 0 or slug in projects:
            per_chat[chat_name] = {
                "cwd_slug": slug,
                "tokens": token_totals,
            }

    tokens_doc = {
        "updated_at": now.isoformat(timespec="seconds"),
        "chats": per_chat,
        "totals": {
            b: {
                "cost": round(sum(c["tokens"][b]["cost"] for c in per_chat.values()), 2),
                "messages": sum(c["tokens"][b]["messages"] for c in per_chat.values()),
            }
            for b in ("today", "last_7d", "last_30d", "all_time")
        },
    }

    # Round costs for readability
    for chat in tokens_doc["chats"].values():
        for b, t in chat["tokens"].items():
            t["cost"] = round(t["cost"], 2)

    write_atomic(TOKENS_OUT, tokens_doc)

    # Skills-usage with all skills present (including unreferenced)
    skills_doc = {
        "updated_at": now.isoformat(timespec="seconds"),
        "skills": {},
    }
    for skill in list_all_skills():
        hits = skills_hits_global.get(skill, {})
        skills_doc["skills"][skill] = {
            "today":    hits.get("today", 0),
            "last_7d":  hits.get("last_7d", 0),
            "last_30d": hits.get("last_30d", 0),
            "all_time": hits.get("all_time", 0),
        }
    # Also carry the "__grep_across__" cross-skill browses
    if "__grep_across__" in skills_hits_global:
        skills_doc["_grep_across_skills"] = dict(skills_hits_global["__grep_across__"])

    write_atomic(SKILLS_OUT, skills_doc)

if __name__ == "__main__":
    main()
