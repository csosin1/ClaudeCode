#!/bin/bash
# refresh-project-context.sh
#
# On-demand single-project trigger. Drops a refresh trigger file that the
# project's head agent picks up to run the context-researcher in "refresh"
# mode.
#
# Usage: refresh-project-context.sh <project>
#
# Exit codes:
#   0 trigger dropped
#   1 usage error or unknown project

set -eE -o pipefail
trap 'echo "refresh-project-context.sh failed at line $LINENO" >&2' ERR

PROJECT="${1:?project name required (e.g. abs-dashboard)}"
CONF=/etc/claude-projects.conf
TRIGGER_DIR=/var/run/claude-sessions

case "$PROJECT" in
    *[^a-zA-Z0-9-]*)
        echo "Project name must be alphanumeric + dashes only" >&2
        exit 1
        ;;
esac

mkdir -p "$TRIGGER_DIR"

# Sanity-check the project is registered.
if [ -f "$CONF" ] && ! awk '{print $1}' "$CONF" | grep -qx "$PROJECT"; then
    echo "WARN: $PROJECT not in $CONF — trigger will still drop but no tmux window may pick it up." >&2
fi

TRIGGER="$TRIGGER_DIR/$PROJECT.refresh-context"
touch "$TRIGGER"

echo "Trigger dropped: $TRIGGER"
echo "The project's head agent (or claude-watchdog) will dispatch the context-researcher on next scan."

if [ -x /usr/local/bin/notify.sh ]; then
    /usr/local/bin/notify.sh "PROJECT_CONTEXT refresh requested: $PROJECT" \
        "Trigger at $TRIGGER" default "" >/dev/null 2>&1 || true
fi
