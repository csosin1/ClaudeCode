#!/bin/bash
# Spawn a per-project Claude window in the main "claude" tmux session.
# Each project gets its own Claude conversation, its own /remote-control URL,
# and its own bookmark at /remote/<project>.html.
#
# Usage:
#   claude-project.sh <project-name> [working-dir]
#
# Examples:
#   claude-project.sh car-offers
#   claude-project.sh infra /opt/site-deploy
set -e

PROJECT="${1:?project name required (e.g. car-offers)}"
CWD="${2:-/opt/site-deploy}"
SESSION=claude

# Sanitize project name (alphanumeric + dash only, for URL safety)
case "$PROJECT" in
    *[^a-zA-Z0-9-]*)
        echo "Project name must be alphanumeric + dashes only" >&2
        exit 1
        ;;
esac

if [ ! -d "$CWD" ]; then
    echo "Working directory $CWD doesn't exist" >&2
    exit 1
fi

# Ensure main tmux session exists (started by claude-tmux.service)
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Main '$SESSION' tmux session not running. Start: systemctl start claude-tmux" >&2
    exit 1
fi

# If a window already exists for this project, just report it
if tmux list-windows -t "$SESSION" -F '#W' 2>/dev/null | grep -qx "$PROJECT"; then
    URL=$(cat /var/www/landing/remote/"$PROJECT".url 2>/dev/null || echo "unknown")
    echo "Window '$PROJECT' already running. Current URL: $URL"
    echo "Bookmark: https://casinv.dev/remote/$PROJECT.html"
    exit 0
fi

# Resume if a prior conversation exists for this cwd
CWD_SLUG=$(echo "$CWD" | tr '/' '-' | sed 's/^-//')
CLAUDE_CMD="claude"
if ls /root/.claude/projects/-${CWD_SLUG}/*.jsonl >/dev/null 2>&1; then
    CLAUDE_CMD="claude --continue"
fi

# Spawn the window (append after existing; -a prevents "index in use" errors)
tmux new-window -a -t "$SESSION:" -n "$PROJECT" -c "$CWD" "$CLAUDE_CMD"

# Let Claude boot, accept trust, activate remote-control
sleep 4
tmux send-keys -t "$SESSION:$PROJECT" Enter
sleep 2
tmux send-keys -t "$SESSION:$PROJECT" "/remote-control" Enter
sleep 5

# Capture the remote-control URL
URL=$(tmux capture-pane -t "$SESSION:$PROJECT" -p -S -50 \
    | grep -oE 'https://claude.ai/code/session_[A-Za-z0-9]+' | tail -1)

if [ -n "$URL" ]; then
    mkdir -p /var/www/landing/remote
    echo "$URL" > /var/www/landing/remote/"$PROJECT".url
    cat > /var/www/landing/remote/"$PROJECT".html <<HTML
<!doctype html>
<meta http-equiv="refresh" content="0;url=$URL">
<title>Claude · $PROJECT</title>
<p>Opening $PROJECT session: <a href="$URL">$URL</a></p>
HTML
    echo "$PROJECT started in '$CWD'"
    echo "Remote Control: $URL"
    echo "Stable bookmark: https://casinv.dev/remote/$PROJECT.html"
else
    echo "WARNING: couldn't capture remote-control URL for $PROJECT"
fi
