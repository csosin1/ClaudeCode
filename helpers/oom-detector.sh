#!/bin/bash
# oom-detector.sh — detect kernel OOM-killer events and fire an urgent notify.
#
# Why: 2026-04-15 02:19 UTC a 912 MB Python was OOM-killed on the dev droplet
# and carvana-abs-2 went down silently for 9 hours. The "silent OOM" pattern
# (kernel reaps a process, nothing visible, nobody notices) is a recurring
# failure mode across the platform. Track B audit alert #1.
#
# How: every 5 min (via /etc/cron.d/claude-ops) scan kernel journal for
# "oom-killer" / "Out of memory: Killed process" lines newer than the last
# timestamp we recorded. For each new event, post an urgent notify with the
# killed command, pid, rss, and invoking cgroup/scope, plus a journalctl hint.
#
# Dedup state: /var/run/claude-sessions/oom-last-seen-epoch  (unix epoch seconds
# of the newest event we've already alerted on). First-ever run seeds to `now`
# so we don't re-alert on history.
#
# Exit: 0 on success (no-events-found is success); non-zero only on fatal error.

set -u

STATE_DIR="/var/run/claude-sessions"
STATE_FILE="$STATE_DIR/oom-last-seen-epoch"
NOTIFY="/usr/local/bin/notify.sh"
CLICK_URL="https://casinv.dev/capacity.html"

mkdir -p "$STATE_DIR"

# Seed state on first run so we don't alert for history.
if [ ! -f "$STATE_FILE" ]; then
    date +%s > "$STATE_FILE"
    exit 0
fi

LAST_SEEN_EPOCH=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
# Small safety: if state file is garbage, reseed to now and exit.
if ! [[ "$LAST_SEEN_EPOCH" =~ ^[0-9]+$ ]]; then
    date +%s > "$STATE_FILE"
    exit 0
fi

# Scan the last 10 minutes of kernel journal. Cron runs every 5 min; 10 min
# gives a 2x safety margin so nothing is missed across clock skew / late
# journald flushes. Dedup by epoch is what actually prevents re-alerting.
SCAN_OUTPUT=$(journalctl -k --since="-10min" --no-pager -o short-iso 2>/dev/null || true)
if [ -z "$SCAN_OUTPUT" ]; then
    exit 0
fi

# Extract "Killed process" lines — these carry the useful fields (pid, comm, rss).
# Example line:
#   2026-04-16T02:19:51+0000 host kernel: Out of memory: Killed process 557201 (python) total-vm:2698108kB, anon-rss:912688kB, file-rss:2560kB, shmem-rss:0kB, UID:0 pgtables:5100kB oom_score_adj:0
KILLED_LINES=$(printf '%s\n' "$SCAN_OUTPUT" | grep -E "Out of memory: Killed process" || true)
if [ -z "$KILLED_LINES" ]; then
    exit 0
fi

NEWEST_EPOCH=$LAST_SEEN_EPOCH
ALERT_COUNT=0

while IFS= read -r line; do
    # Parse ISO timestamp (first field).
    TS_ISO=$(printf '%s' "$line" | awk '{print $1}')
    EVENT_EPOCH=$(date -d "$TS_ISO" +%s 2>/dev/null || echo 0)
    [ "$EVENT_EPOCH" = "0" ] && continue
    # Skip events we've already alerted on.
    if [ "$EVENT_EPOCH" -le "$LAST_SEEN_EPOCH" ]; then
        continue
    fi

    # Pull fields out of the Killed-process line.
    PID=$(printf '%s' "$line" | sed -n 's/.*Killed process \([0-9]\+\).*/\1/p')
    COMM=$(printf '%s' "$line" | sed -n 's/.*Killed process [0-9]\+ (\([^)]\+\)).*/\1/p')
    ANON_RSS_KB=$(printf '%s' "$line" | sed -n 's/.*anon-rss:\([0-9]\+\)kB.*/\1/p')
    RSS_MB="unknown"
    if [ -n "$ANON_RSS_KB" ]; then
        RSS_MB=$(( ANON_RSS_KB / 1024 ))
    fi

    # Find the invoking cgroup/scope by looking at the preceding "invoked oom-killer"
    # line with the same timestamp prefix (minute-level match is enough for correlation).
    TS_MIN=$(printf '%s' "$TS_ISO" | cut -c1-16)
    INVOKER_LINE=$(printf '%s\n' "$SCAN_OUTPUT" | grep -E "invoked oom-killer" | grep -F "$TS_MIN" | head -n1 || true)
    INVOKER=$(printf '%s' "$INVOKER_LINE" | sed -n 's/.*kernel: \([^ ]\+\) invoked oom-killer.*/\1/p')
    [ -z "$INVOKER" ] && INVOKER="unknown"

    # Compose notify body.
    BODY="Killed: ${COMM:-unknown} (pid=${PID:-?}, rss=${RSS_MB}MB). Cgroup: ${INVOKER}. Full event: journalctl -k --since '${TS_ISO}'."
    TITLE="Kernel OOM-kill on dev"
    "$NOTIFY" "$BODY" "$TITLE" "urgent" "$CLICK_URL" >/dev/null 2>&1 || true
    ALERT_COUNT=$((ALERT_COUNT + 1))

    if [ "$EVENT_EPOCH" -gt "$NEWEST_EPOCH" ]; then
        NEWEST_EPOCH=$EVENT_EPOCH
    fi
done <<< "$KILLED_LINES"

# Persist the newest epoch we saw so we don't re-alert.
if [ "$NEWEST_EPOCH" -gt "$LAST_SEEN_EPOCH" ]; then
    echo "$NEWEST_EPOCH" > "$STATE_FILE"
fi

exit 0
