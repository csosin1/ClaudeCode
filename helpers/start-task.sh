#!/bin/bash
# Start a task on a feature branch in an isolated git worktree.
# Using worktrees prevents multiple project chats from colliding on a shared checkout.
# Usage: start-task.sh <project> "<description>" [repo-path]
set -e

PROJECT="${1:?project required (e.g. car-offers)}"
DESC="${2:?description required in quotes}"
REPO="${3:-/opt/site-deploy}"
WORKTREES_ROOT=/opt/worktrees

case "$PROJECT" in
    *[^a-zA-Z0-9-]*)
        echo "Project name must be alphanumeric + dashes only" >&2
        exit 1
        ;;
esac

SLUG=$(echo "$DESC" | tr '[:upper:] ' '[:lower:]-' | tr -cd '[:alnum:]-' | head -c 40 | sed 's/-*$//')
BRANCH="claude/$PROJECT-$SLUG"
WORKTREE="$WORKTREES_ROOT/$PROJECT-$SLUG"

mkdir -p "$WORKTREES_ROOT"

cd "$REPO"
# Guard: the shared repo must stay on main. If it isn't, that's a bug elsewhere — surface it.
CURRENT=$(git branch --show-current 2>/dev/null || echo "")
if [ -n "$CURRENT" ] && [ "$CURRENT" != "main" ]; then
    echo "WARNING: $REPO is on '$CURRENT' instead of main. Restoring." >&2
    git stash -u --include-untracked >/dev/null 2>&1 || true
    git checkout main
fi

git fetch origin main --quiet
git pull --ff-only origin main --quiet || true

# Reuse if the worktree already exists; otherwise create it.
if [ -d "$WORKTREE" ]; then
    echo "Worktree already exists at $WORKTREE — reusing."
else
    git worktree add -B "$BRANCH" "$WORKTREE" origin/main
fi

/usr/local/bin/task-status.sh set "$PROJECT" "$DESC" building "branch: $BRANCH"

cat <<INFO
Task started.
  Project: $PROJECT
  Description: $DESC
  Branch: $BRANCH
  Worktree: $WORKTREE

Work in the worktree:
  cd $WORKTREE
  # edit, commit as normal

When ready to deploy to preview, call:
  finish-task.sh $PROJECT

When user approves with "ship it":
  bash /opt/site-deploy/deploy/promote.sh $PROJECT
INFO
