#!/bin/bash
# Start a task on a feature branch and update task-status.
# Usage: start-task.sh <project> "<description>" [repo-path]
set -e

PROJECT="${1:?project required (e.g. car-offers)}"
DESC="${2:?description required in quotes}"
REPO="${3:-/opt/site-deploy}"

case "$PROJECT" in
    *[^a-zA-Z0-9-]*)
        echo "Project name must be alphanumeric + dashes only" >&2
        exit 1
        ;;
esac

SLUG=$(echo "$DESC" | tr '[:upper:] ' '[:lower:]-' | tr -cd '[:alnum:]-' | head -c 40 | sed 's/-*$//')
BRANCH="claude/$PROJECT-$SLUG"

cd "$REPO"
git fetch origin main --quiet
git checkout -B "$BRANCH" origin/main

/usr/local/bin/task-status.sh set "$PROJECT" "$DESC" building "branch: $BRANCH"

cat <<INFO
Task started.
  Project: $PROJECT
  Description: $DESC
  Branch: $BRANCH

When ready to deploy to preview:
  git push origin $BRANCH                       # pushes branch, no deploy
  git checkout main && git merge --ff-only $BRANCH && git push origin main  # DEPLOYS to preview

When user approves with "ship it":
  bash /opt/site-deploy/deploy/promote.sh $PROJECT
INFO
