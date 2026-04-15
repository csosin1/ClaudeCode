# Skill: Deploy & Rollback

## When To Use

At every deploy. Especially before promoting preview → live, and whenever live is broken.

## Rules

- Every push to `main` deploys to **preview only**. Preview is where all iteration happens.
- Promotion from preview → live happens via an explicit marker file or deploy flag set by the orchestrator only after the user accepts. Implementations vary per project (rsync for static, active-port swap for services) but the principle is the same: **live never changes without user acceptance**.
- **Before every promote:**
  ```bash
  git tag rollback-$(date +%Y%m%d-%H%M%S) && git push origin --tags
  ```
- If live is ever broken: roll back to the tag, restore previous nginx if changed, verify 200, then report.

## Rollback Procedure

1. `git tag --list 'rollback-*' | tail -5` — find the most recent good tag.
2. `git checkout <tag> -- <project>/` — restore the project's files.
3. If `update_nginx.sh` changed recently, `git checkout <tag> -- deploy/update_nginx.sh`.
4. Run `/opt/site-deploy/deploy/<project>.sh` to rebuild the affected preview.
5. Promote to live if the rollback is for a live bug: `bash /opt/site-deploy/deploy/promote.sh <project>`.
6. `curl -sI <live-URL> | head -1` — confirm 200.
7. Notify the user of the rollback + what commit introduced the break.

## Integration

- `SKILLS/root-cause-analysis.md` — every rollback gets an RCA + LESSONS.md entry.
- `SKILLS/feature-branch-worktree.md` — most deploys are follow-ups from `finish-task.sh`.
