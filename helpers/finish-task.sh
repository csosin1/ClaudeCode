#!/bin/bash
# Merge the current task's worktree branch into main, push, clean up.
# Usage: finish-task.sh <project> [repo-path]
set -e

PROJECT="${1:?project required}"
REPO="${2:-/opt/site-deploy}"

# Locate the worktree for this project (matches claude/<project>-*)
WORKTREE=$(git -C "$REPO" worktree list --porcelain 2>/dev/null \
    | awk -v pat="refs/heads/claude/$PROJECT-" '
        /^worktree / { wt=$2 }
        /^branch /   { if (index($2, pat) == 1) print wt }
      ' | head -1)

if [ -z "$WORKTREE" ] || [ ! -d "$WORKTREE" ]; then
    # Back-compat: allow finishing from an in-repo branch (pre-worktree task)
    cd "$REPO"
    BRANCH=$(git branch --show-current)
    case "$BRANCH" in
        claude/"$PROJECT"-*)
            echo "No worktree for $PROJECT; finishing from in-repo branch $BRANCH." >&2
            WORKTREE=""
            ;;
        *)
            echo "No worktree for $PROJECT and repo is on '$BRANCH'. Nothing to finish." >&2
            exit 1
            ;;
    esac
else
    cd "$WORKTREE"
    BRANCH=$(git branch --show-current)
fi

git push -u origin "$BRANCH"

# Merge into main via the canonical repo (not the worktree).
cd "$REPO"
CURRENT=$(git branch --show-current)
if [ "$CURRENT" != "main" ]; then
    # If we were operating from the repo itself (back-compat path), switch back.
    git checkout main
fi
git pull --ff-only origin main
git merge --no-ff --no-edit "$BRANCH"
git push origin main

if [ -n "$WORKTREE" ] && [ -d "$WORKTREE" ]; then
    git worktree remove --force "$WORKTREE" 2>/dev/null || true
fi
git branch -d "$BRANCH" 2>/dev/null || true

/usr/local/bin/task-status.sh set "$PROJECT" "deploying to preview" deploying "merged $BRANCH → main"
echo "Merged and pushed. Auto-deploy will update the preview URL in ~5s."
