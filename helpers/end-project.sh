#!/bin/bash
# Close a per-project Claude window.
# Usage: end-project.sh <project-name>
set -e
PROJECT="${1:?project name required}"
SESSION=claude

if [ "$PROJECT" = "claude" ] || [ "$PROJECT" = "main" ] || [ "$PROJECT" = "0" ]; then
    echo "Cowardly refusing to close the main claude window." >&2
    exit 1
fi

tmux kill-window -t "$SESSION:$PROJECT" 2>&1 || echo "(window already gone)"
rm -f /var/www/landing/remote/"$PROJECT".html /var/www/landing/remote/"$PROJECT".url
echo "$PROJECT window closed."
