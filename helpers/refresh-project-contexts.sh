#!/bin/bash
# refresh-project-contexts.sh
#
# Quarterly cron entry: iterate all projects in /etc/claude-projects.conf and
# dispatch the context-researcher agent in "refresh" mode for each. Sequential
# (not parallel) to avoid an LLM-cost spike.
#
# The actual researcher dispatch is performed by the head agent in each
# project's tmux window — this script's job is to DROP A TRIGGER FILE per
# project that the head agent (or its watchdog) picks up and acts on.
#
# Trigger file: /var/run/claude-sessions/<project>.refresh-context
# Consumers (head agent, claude-watchdog.sh) look for it, dispatch the
# research pass, and delete the trigger when done.
#
# Invoked from: /etc/cron.d/claude-ops at 04:00 on the 1st of every 3rd month.

set -eE -o pipefail
trap 'echo "refresh-project-contexts.sh failed at line $LINENO" >&2' ERR

CONF=/etc/claude-projects.conf
TRIGGER_DIR=/var/run/claude-sessions
LOG=/var/log/refresh-project-contexts.log

mkdir -p "$TRIGGER_DIR"

log() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"
}

log "=== refresh-project-contexts.sh start ==="

if [ ! -f "$CONF" ]; then
    log "WARN: $CONF missing; nothing to refresh"
    exit 0
fi

# Iterate project lines: <name> <cwd>
while read -r NAME CWD _; do
    case "$NAME" in
        ""|\#*) continue ;;
    esac
    if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
        log "SKIP: $NAME (cwd $CWD missing)"
        continue
    fi
    TRIGGER="$TRIGGER_DIR/$NAME.refresh-context"
    touch "$TRIGGER"
    log "TRIGGER: $NAME -> $TRIGGER (cwd $CWD)"
    # Also try notify the project tmux window via notify.sh so the human knows.
    if [ -x /usr/local/bin/notify.sh ]; then
        /usr/local/bin/notify.sh "Quarterly PROJECT_CONTEXT refresh due: $NAME" \
            "context-researcher trigger dropped at $TRIGGER" \
            low "" >/dev/null 2>&1 || true
    fi
done < "$CONF"

log "=== refresh-project-contexts.sh done ==="
