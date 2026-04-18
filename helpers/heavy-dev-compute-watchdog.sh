#!/bin/bash
# heavy-dev-compute-watchdog.sh — runs every 2 minutes on dev, detects any
# heavy Python/Node/Playwright process running under a Claude chat subtree
# on dev, and terminates it (with grace) + notifies.
#
# Complements the /opt/abs-venv/bin/python wrapper (which only protects
# abs-dashboard's specific venv). This script catches the general case:
# any heavy compute a Claude chat accidentally launches on dev.
#
# Thresholds (tuned for the 4GB dev box; adjust in /etc/heavy-dev-compute.conf):
#   MIN_RSS_MB=200   — ignore small processes
#   MIN_AGE_SEC=60   — ignore brief invocations
#   GRACE_SEC=120    — SIGTERM, wait, then SIGKILL
#
# What counts as "heavy compute on dev":
# - parent chain includes a `claude` process under tmux session `claude`
# - RSS > MIN_RSS_MB
# - process age > MIN_AGE_SEC
# - command matches: python* (from /opt/* venvs), node running a user script,
#   playwright browser automation, npm/npx run
#
# What does NOT count (whitelist):
# - /usr/bin/python3 running system scripts (auto-deploy hooks, etc.)
# - claude-code itself (the agent process)
# - editor processes, quick one-off utilities
#
# Action cascade per detection:
# 1. First sight: log to /var/log/heavy-dev-compute.log, tmux-send a directive
#    to the owning Claude chat, state=warn in /var/run/heavy-dev-compute.state
# 2. Still alive at GRACE_SEC/2: escalate, ntfy high
# 3. Still alive at GRACE_SEC: SIGTERM the process tree, ntfy urgent

set -u

CONF=/etc/heavy-dev-compute.conf
STATE_DIR=/var/run/heavy-dev-compute
LOG=/var/log/heavy-dev-compute.log
LOCK=/var/run/heavy-dev-compute-watchdog.lock

# Defaults (overridden by conf if present)
MIN_RSS_MB=200
MIN_AGE_SEC=60
GRACE_SEC=120
DEV_HOSTNAME="Cliffsfirstdroplet"

[ -f "$CONF" ] && . "$CONF" 2>/dev/null

# Only run on dev
[ "$(hostname)" = "$DEV_HOSTNAME" ] || exit 0

# Single-flight
exec 9>"$LOCK"
flock -n 9 || exit 0

mkdir -p "$STATE_DIR"

NOW_EPOCH=$(date +%s)

# Find all Claude chat PIDs (children of tmux server running the `claude` session)
TMUX_SERVER=$(pgrep -f 'tmux new-session.*-s claude' 2>/dev/null | head -1)
[ -z "$TMUX_SERVER" ] && exit 0

CHAT_PIDS=$(pgrep -P "$TMUX_SERVER" 2>/dev/null)
[ -z "$CHAT_PIDS" ] && exit 0

# For each chat, walk descendants looking for heavy processes
for CHAT_PID in $CHAT_PIDS; do
    CHAT_WIN=$(tmux list-windows -t claude -F '#{window_name} #{pane_pid}' 2>/dev/null | awk -v p=$CHAT_PID '$2==p {print $1}')
    [ -z "$CHAT_WIN" ] && continue

    # Skip the infra chat — that's the orchestrator; it legitimately runs some
    # shell compute and shouldn't trigger itself.
    [ "$CHAT_WIN" = "infra" ] && continue

    # Walk all descendants
    DESC_PIDS=$(pgrep -P "$CHAT_PID" 2>/dev/null)
    # Also get grandchildren (one level of bash → python nesting)
    for D in $DESC_PIDS; do
        DESC_PIDS="$DESC_PIDS $(pgrep -P "$D" 2>/dev/null)"
    done

    for PID in $DESC_PIDS; do
        [ -z "$PID" ] && continue
        [ ! -d "/proc/$PID" ] && continue

        # Get RSS in MB
        RSS_KB=$(ps -o rss= -p "$PID" 2>/dev/null | tr -d ' ')
        [ -z "$RSS_KB" ] && continue
        RSS_MB=$((RSS_KB / 1024))
        [ "$RSS_MB" -lt "$MIN_RSS_MB" ] && continue

        # Get age
        ETIME_SEC=$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ')
        [ -z "$ETIME_SEC" ] && continue
        [ "$ETIME_SEC" -lt "$MIN_AGE_SEC" ] && continue

        # Get command
        CMD=$(ps -o cmd= -p "$PID" 2>/dev/null)

        # Whitelist: skip claude-code itself, skip system python utilities
        echo "$CMD" | grep -qE '^claude$|node_modules/.*/claude' && continue
        echo "$CMD" | grep -qE '/usr/bin/python3? (-m (pip|venv)|/usr/bin/|/usr/lib/|/usr/share/)' && continue

        # Must match heavy-compute patterns
        HEAVY=0
        echo "$CMD" | grep -qE '/opt/.*/bin/python|/opt/.*-venv/bin/python' && HEAVY=1
        echo "$CMD" | grep -qE 'node .*/server\.js|node .*\.js|npm run|npx playwright' && HEAVY=1
        [ "$HEAVY" -eq 0 ] && continue

        # Track state per-PID
        STATE_FILE="$STATE_DIR/pid-$PID"
        if [ ! -f "$STATE_FILE" ]; then
            # First sight — warn
            FIRST_SEEN=$NOW_EPOCH
            echo "$FIRST_SEEN warn" > "$STATE_FILE"
            {
                echo "[$(date -Iseconds)] WARN heavy dev-compute detected"
                echo "  chat=$CHAT_WIN chat_pid=$CHAT_PID pid=$PID rss_mb=$RSS_MB age_sec=$ETIME_SEC"
                echo "  cmd: $CMD"
            } >> "$LOG"
            MSG="INFRA WATCHDOG — heavy compute on DEV detected from your chat.

Process: $CMD
PID: $PID  RSS: ${RSS_MB}MB  Age: ${ETIME_SEC}s

Post-migration rule: heavy compute runs on PROD, not dev. Either kill this process yourself and re-run via 'ssh prod-private ...', or set ALLOW_DEV_COMPUTE=1 if you genuinely need to run on dev.

If you don't act, this process will be SIGTERM'd in ${GRACE_SEC}s. Infra is watching."
            tmux send-keys -t "claude:$CHAT_WIN" "$MSG" Enter 2>/dev/null
            sleep 0.3
            tmux send-keys -t "claude:$CHAT_WIN" Enter 2>/dev/null
            /usr/local/bin/notify.sh \
                "Heavy dev-compute from $CHAT_WIN chat (pid $PID, ${RSS_MB}MB). Directive sent. Will kill in ${GRACE_SEC}s if not resolved." \
                "Wrong-server compute warning" \
                default 2>/dev/null || true
            continue
        fi

        read FIRST_SEEN STATE < "$STATE_FILE"
        AGE_SINCE_FIRST=$((NOW_EPOCH - FIRST_SEEN))

        if [ "$STATE" = "warn" ] && [ "$AGE_SINCE_FIRST" -ge $((GRACE_SEC / 2)) ]; then
            echo "$FIRST_SEEN escalated" > "$STATE_FILE"
            echo "[$(date -Iseconds)] ESCALATE pid=$PID still alive at T+${AGE_SINCE_FIRST}s" >> "$LOG"
            /usr/local/bin/notify.sh \
                "Dev-compute from $CHAT_WIN still running after warning (pid $PID). Will SIGTERM in $((GRACE_SEC - AGE_SINCE_FIRST))s." \
                "Wrong-server compute escalation" \
                high 2>/dev/null || true
        fi

        if [ "$AGE_SINCE_FIRST" -ge "$GRACE_SEC" ]; then
            # Kill the process tree
            echo "[$(date -Iseconds)] KILL pid=$PID grace exceeded, SIGTERM tree" >> "$LOG"
            # SIGTERM the process + all descendants
            pkill -TERM -P "$PID" 2>/dev/null
            kill -TERM "$PID" 2>/dev/null
            sleep 5
            # SIGKILL stragglers
            pkill -KILL -P "$PID" 2>/dev/null
            kill -KILL "$PID" 2>/dev/null
            rm -f "$STATE_FILE"
            /usr/local/bin/notify.sh \
                "KILLED wrong-server compute (chat=$CHAT_WIN pid=$PID, ran ${ETIME_SEC}s). See $LOG." \
                "Wrong-server compute killed" \
                urgent 2>/dev/null || true
        fi
    done
done

# Clean up state files for PIDs that no longer exist
for sf in "$STATE_DIR"/pid-*; do
    [ -f "$sf" ] || continue
    pid="${sf##*pid-}"
    [ -d "/proc/$pid" ] || rm -f "$sf"
done

exit 0
