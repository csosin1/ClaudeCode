#!/bin/bash
# Start Claude Code in a persistent tmux session with remote-control mode.
# Attach in-place with: tmux attach -t claude
# Attach from phone: https://casinv.dev/remote.html (auto-redirects)
set -e
SESSION=claude
cd /root

# Reuse existing session if it's still alive (idempotent on reboot retries)
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' already running."
    exit 0
fi

# Resume last conversation if one exists; else start fresh
CLAUDE_CMD="claude"
if ls /root/.claude/projects/-root/*.jsonl >/dev/null 2>&1; then
    CLAUDE_CMD="claude --continue"
fi

# Create detached session
tmux new-session -d -s "$SESSION" -c /root "$CLAUDE_CMD"

# Claude shows a "trust this folder?" prompt on first boot. Option 1 is
# pre-selected, so pressing Enter accepts it. Safe to send even if not shown.
sleep 4
tmux send-keys -t "$SESSION" Enter
sleep 2

# Activate remote-control so the user can attach from claude.ai/code on any device
tmux send-keys -t "$SESSION" "/remote-control" Enter
sleep 4

# Capture the /remote-control URL and expose it at /var/www/landing/remote.html
# so the user can bookmark https://casinv.dev/remote.html and always hit the
# current session (URL changes each time /remote-control is re-activated).
REMOTE_URL=$(tmux capture-pane -t "$SESSION" -p | grep -oE 'https://claude.ai/code/session_[A-Za-z0-9]+' | head -1)
if [ -n "$REMOTE_URL" ]; then
    mkdir -p /var/www/landing
    cat > /var/www/landing/remote.html <<HTML
<!doctype html>
<meta http-equiv="refresh" content="0;url=$REMOTE_URL">
<title>Claude Remote Control</title>
<p>Redirecting to <a href="$REMOTE_URL">$REMOTE_URL</a>...</p>
HTML
    echo "Remote-control URL: $REMOTE_URL"
    echo "Stable bookmark:    https://casinv.dev/remote.html"
else
    echo "WARNING: could not capture /remote-control URL from pane"
fi

echo "tmux session '$SESSION' ready."
