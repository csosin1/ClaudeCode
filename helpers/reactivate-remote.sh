#!/bin/bash
# reactivate-remote.sh — reactivate /remote-control on a Claude project's
# tmux window when its URL has gone stale (URL dead, chat still alive).
# Usage: reactivate-remote.sh <project>
#
# Safe to run on a healthy window: no-op if "Remote Control active" is
# already present in the pane.
set -e

PROJECT="${1:?project name required}"
SESSION=claude
BOOKMARK_DIR=/var/www/landing/remote

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' not running" >&2
    exit 1
fi
if ! tmux list-windows -t "$SESSION" -F '#W' 2>/dev/null | grep -qx "$PROJECT"; then
    echo "window '$PROJECT' not in session" >&2
    exit 2
fi

# Already active? no-op.
CAP=$(tmux capture-pane -t "$SESSION:$PROJECT" -p -S -10 2>/dev/null)
if echo "$CAP" | grep -q 'Remote Control active'; then
    echo "already active"
    exit 0
fi

# Escape any stuck menu, clear input, then invoke /remote-control.
tmux send-keys -t "$SESSION:$PROJECT" Escape
sleep 1
tmux send-keys -t "$SESSION:$PROJECT" Escape
sleep 1
tmux send-keys -t "$SESSION:$PROJECT" "/remote-control" Enter
sleep 6

URL=$(tmux capture-pane -t "$SESSION:$PROJECT" -p -S -60 2>/dev/null \
    | grep -oE 'https://claude.ai/code/session_[A-Za-z0-9]+' | tail -1)

if [ -z "$URL" ]; then
    echo "FAILED to capture new URL for $PROJECT" >&2
    exit 3
fi

mkdir -p "$BOOKMARK_DIR"
echo "$URL" > "$BOOKMARK_DIR/$PROJECT.url"
cat > "$BOOKMARK_DIR/$PROJECT.html" <<HTML
<!doctype html>
<meta http-equiv="refresh" content="0;url=$URL">
<title>Claude · $PROJECT</title>
<p>Opening $PROJECT session: <a href="$URL">$URL</a></p>
HTML

echo "reactivated: $PROJECT -> $URL"
