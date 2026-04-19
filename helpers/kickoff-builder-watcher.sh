#!/bin/bash
# kickoff-builder-watcher.sh — scan /opt/*/.kickoff-state/ for BUILDER_READY
# sentinels, dispatch a builder subagent per new sentinel, log the dispatch,
# and move the sentinel to BUILDER_DISPATCHED so this doesn't re-fire.
#
# Invocation modes:
#   --once    one-shot scan (triggered by the .path unit or manual).
#   --loop    long-running inotify loop (used if the .path unit is not wired).
#
# Dispatch pattern mirrors helpers/visual-review-orchestrator.sh: uses the
# `claude -p` CLI with a brief built from the finalized KICKOFF_REPORT.md §
# Synthesized Spec section. Runs in background (setsid + nohup) so the watcher
# returns quickly.
#
# Log line (one per dispatch) written to /var/log/kickoff-dispatches.jsonl:
#   {"ts": "...", "project": "...", "spec_sha": "...", "builder_agent_id": "...",
#    "notify_tier": "milestone"}

set -u

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
NOTIFY_SH="/opt/site-deploy/helpers/notify.sh"
LOG_FILE="/var/log/kickoff-dispatches.jsonl"
DISPATCH_LOG_DIR="/var/log/kickoff-builder-dispatch"
mkdir -p "$DISPATCH_LOG_DIR" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/kickoff-dispatches.jsonl"

# Returns 0 iff claude binary is present & runnable; 1 otherwise.
have_claude() {
    command -v "$CLAUDE_BIN" >/dev/null 2>&1
}

extract_synthesized_spec() {
    # Pull the "## Synthesized Spec ..." section out of KICKOFF_REPORT.md and
    # print to stdout. If absent, print the whole file.
    local report="$1"
    python3 - "$report" <<'PY'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
src = p.read_text()
m = re.search(r'(?ms)^##\s+Synthesized Spec.*?(?=^##\s+|\Z)', src)
print(m.group(0).strip() if m else src.strip())
PY
}

dispatch_one() {
    local project="$1"
    local state_dir="/opt/$project/.kickoff-state"
    local report="/opt/$project/KICKOFF_REPORT.md"
    local sentinel="$state_dir/BUILDER_READY"
    local dispatched="$state_dir/BUILDER_DISPATCHED"
    local ts_iso; ts_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Move the sentinel FIRST so a second watcher fire can't race us.
    # If mv fails (e.g. another watcher already claimed it), exit silently.
    if ! mv "$sentinel" "$dispatched" 2>/dev/null; then
        return 0
    fi

    # Compute a short SHA of the spec section for the log.
    local spec_sha="unknown"
    if [ -f "$report" ]; then
        spec_sha="$(extract_synthesized_spec "$report" | sha256sum | cut -c1-12)"
    fi

    # Build the brief.
    local brief="$state_dir/builder-brief.txt"
    {
        echo "Role: Builder subagent for project $project."
        echo ""
        echo "The kickoff committee has finalized the spec. Your job is to implement it."
        echo ""
        echo "Authoritative spec: /opt/$project/KICKOFF_REPORT.md § Synthesized Spec"
        echo ""
        echo "Constraints (from user):"
        if [ -f "$state_dir/constraints.md" ]; then
            cat "$state_dir/constraints.md"
        else
            echo "(none)"
        fi
        echo ""
        echo "=== Synthesized Spec ==="
        if [ -f "$report" ]; then
            extract_synthesized_spec "$report"
        else
            echo "(KICKOFF_REPORT.md missing — escalate and stop)"
        fi
        echo ""
        echo "Follow CLAUDE.md + SKILLS/ conventions. Commit early, push often."
    } > "$brief"

    # Dispatch builder in background. If claude CLI isn't available here (e.g.
    # systemd's reduced environment), record that in the log and fall back to
    # writing a "BUILDER_BRIEF_READY" marker for a human-driven pickup.
    local builder_agent_id="builder-${project}-${ts_iso//[:T]/}-$$"
    local dispatch_log="$DISPATCH_LOG_DIR/${builder_agent_id}.log"
    local status="dispatched"

    if have_claude; then
        nohup setsid bash -c "'$CLAUDE_BIN' -p <'$brief' >'$dispatch_log' 2>&1" </dev/null >/dev/null 2>&1 &
        disown || true
    else
        status="deferred_no_claude_cli"
        touch "$state_dir/BUILDER_BRIEF_READY"
    fi

    # ntfy at milestone tier.
    local notify_tier="milestone"
    local preview_url="https://casinv.dev/"
    # If a known project-url mapping exists, improve the click target.
    case "$project" in
        car-offers)        preview_url="https://casinv.dev/car-offers/preview/" ;;
        gym-intelligence)  preview_url="https://casinv.dev/gym-intelligence/preview/" ;;
        carvana-abs-2)     preview_url="https://casinv.dev/CarvanaLoanDashBoard/preview/" ;;
        timeshare-dashboard) preview_url="https://casinv.dev/timeshare-surveillance/preview/" ;;
    esac
    if [ -x "$NOTIFY_SH" ]; then
        "$NOTIFY_SH" \
            "Kickoff finalized — builder dispatched for $project" \
            "Kickoff: $project" \
            --tier "$notify_tier" \
            --click "$preview_url" 2>/dev/null || true
    fi

    # Canonical log line.
    python3 - "$LOG_FILE" "$ts_iso" "$project" "$spec_sha" "$builder_agent_id" "$notify_tier" "$status" <<'PY'
import json, sys, pathlib
log, ts, project, sha, agent, tier, status = sys.argv[1:8]
row = {
    "ts":                ts,
    "project":           project,
    "spec_sha":          sha,
    "builder_agent_id":  agent,
    "notify_tier":       tier,
    "status":            status,
}
with open(log, "a") as f:
    f.write(json.dumps(row) + "\n")
PY

    echo "[kickoff-builder-watcher] dispatched project=$project sha=$spec_sha agent=$builder_agent_id status=$status"
}

scan_once() {
    local state_dir project
    shopt -s nullglob
    for state_dir in /opt/*/.kickoff-state; do
        project="$(basename "$(dirname "$state_dir")")"
        if [ -f "$state_dir/BUILDER_READY" ]; then
            dispatch_one "$project" || true
        fi
    done
    shopt -u nullglob
}

loop_inotify() {
    # Fallback loop for hosts where the .path unit isn't installed.
    command -v inotifywait >/dev/null 2>&1 || {
        echo "[kickoff-builder-watcher] inotifywait missing; install inotify-tools or use --once" >&2
        exit 2
    }
    # Initial pass in case sentinels already exist.
    scan_once
    while true; do
        # Wait up to 60s for any change under /opt/*/.kickoff-state/
        inotifywait -qq -t 60 -e create -e moved_to /opt/*/.kickoff-state/ 2>/dev/null || true
        scan_once
    done
}

case "${1:---once}" in
    --once) scan_once ;;
    --loop) loop_inotify ;;
    -h|--help) sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "usage: $0 [--once|--loop]" >&2; exit 2 ;;
esac
