---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Feature-Branch Workflow (worktree-based)

## When To Use

Any task that's more than a small fix. "Small fix" = <~30 lines, one file, no cross-cutting concern — those can push directly to main from `/opt/site-deploy`. **Everything larger uses a worktree.**

## Why Worktrees (Not Branch-Checkout)

Multiple project chats share `/opt/site-deploy`. If chat A switches it to a feature branch to work, chat B's next commit lands on A's branch — we've seen this happen and had to cherry-pick to recover. Worktrees give each task its own directory on its own branch, leaving the shared checkout permanently on `main`.

## The Commands

- **Start a task:**
  ```
  start-task.sh <project> "<description>"
  ```
  Creates branch `claude/<project>-<slug>` and a worktree at `/opt/worktrees/<project>-<slug>` off origin/main. Prints the worktree path. Updates task-status.

- **Do the work:**
  ```
  cd /opt/worktrees/<project>-<slug>
  # edit, commit as usual
  ```
  Pushing the branch does NOT deploy — only main deploys.

- **Ship to preview:**
  ```
  finish-task.sh <project>
  ```
  Pushes the feature branch, merges into main via the canonical `/opt/site-deploy` repo, pushes main, removes the worktree. Auto-deploy updates the preview URL in ~5 s.

- **User says "ship it":**
  ```
  bash /opt/site-deploy/deploy/promote.sh <project>
  ```
  Promotes preview → live. See `SKILLS/deploy-rollback.md`.

## Invariant

`git -C /opt/site-deploy branch --show-current` must always return `main`. `start-task.sh` auto-corrects if it's not, but that's a smell worth investigating.

## Troubleshooting

- **Worktree won't delete** (after `finish-task.sh`): `git worktree prune` then retry. Usually means a stale lockfile.
- **Merge conflict on finish-task.sh:** resolve in the worktree, then re-run `finish-task.sh`.
- **Branch already exists:** `start-task.sh` will refuse rather than clobber. Delete the stale one (`git branch -D claude/<project>-<slug>`) or rename the new task.

## Integration

- `SKILLS/deploy-rollback.md` — what happens after `finish-task.sh`.
- `SKILLS/session-resilience.md` — commit + push every 10-15 min so crashes don't lose worktree work.
- `SKILLS/root-cause-analysis.md` — every LESSONS.md entry commits alongside the permanent fix.
