#!/bin/bash
# Merge current feature branch into main, push, update task-status to deployed.
# Usage: finish-task.sh <project>
set -e
PROJECT="${1:?project required}"
REPO="${2:-/opt/site-deploy}"

cd "$REPO"
BRANCH=$(git branch --show-current)
if [ "$BRANCH" = "main" ] || [ -z "$BRANCH" ]; then
    echo "Not on a feature branch. Switch to claude/<project>-<desc> first." >&2
    exit 1
fi
case "$BRANCH" in claude/"$PROJECT"-*) ;; *)
    echo "Current branch '$BRANCH' doesn't match project '$PROJECT'." >&2
    exit 1
esac

git push origin "$BRANCH"
git checkout main
git pull --ff-only origin main
git merge --no-ff --no-edit "$BRANCH"
git push origin main
git branch -d "$BRANCH" 2>/dev/null || true

/usr/local/bin/task-status.sh set "$PROJECT" "deploying to preview" deploying "merged $BRANCH → main"
echo "Merged and pushed. Auto-deploy will update the preview URL in ~5s."
