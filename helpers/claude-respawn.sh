#!/bin/bash
# claude-respawn.sh — ensure every expected project has a live tmux window.
# Respawns any missing ones via claude-project.sh and notifies.
# Intended to run every 5 min via cron.
set -e

CONF=/etc/claude-projects.conf
SESSION=claude

[ -f "$CONF" ] || exit 0
tmux has-session -t "$SESSION" 2>/dev/null || exit 0

EXISTING=$(tmux list-windows -t "$SESSION" -F '#W' 2>/dev/null || echo "")

while read -r NAME CWD; do
    # skip blank + comment lines
    [ -z "$NAME" ] && continue
    case "$NAME" in \#*) continue ;; esac

    if ! echo "$EXISTING" | grep -qx "$NAME"; then
        logger -t claude-respawn "respawning missing window: $NAME ($CWD)"
        if /usr/local/bin/claude-project.sh "$NAME" "$CWD" >/tmp/claude-respawn-"$NAME".log 2>&1; then
            /usr/local/bin/notify.sh \
                "$NAME window was archived; respawned automatically" \
                "Claude respawn: $NAME" \
                default \
                "https://casinv.dev/remote/$NAME.html" 2>/dev/null || true
        else
            /usr/local/bin/notify.sh \
                "Failed to respawn $NAME; see /tmp/claude-respawn-$NAME.log" \
                "Claude respawn FAILED: $NAME" \
                urgent \
                "" 2>/dev/null || true
        fi
    fi
done < "$CONF"
