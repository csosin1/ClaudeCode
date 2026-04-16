# /opt/infra/ — home of the infrastructure orchestrator chat

## Why this directory exists

The platform's orchestrator chat was originally the `timeshare-surveillance` tmux window with cwd `/opt/timeshare-surveillance-preview/`. That was an accident of how the window first got repurposed: a project chat got promoted into an orchestrator role but never moved out of the project's deploy directory. The risk it created: a busy orchestrator absently editing a file in a project directory is a project-isolation violation, and `/opt/timeshare-surveillance-preview/` isn't even a git repo (it's a deploy target), so any such edit would be silently lost on the next auto-deploy.

Creating `/opt/infra/` as a neutral home is the structural fix. The infra agent has no project source under its cwd, so there's nothing in the local filesystem for it to accidentally corrupt. It must reach `/opt/site-deploy/` with explicit `git -C` commands, which makes the commit target an intentional act rather than an implicit one.

## What lives here

- `CLAUDE.md` — scope-narrowed rules for the infra agent: allowed paths, forbidden paths, branching convention, self-check on every turn.
- `PROJECT_STATE.md` — the orchestrator's own continuity file, read first on session spawn.
- `README.md` — this file.

## What does NOT live here

- No project source. No project data. No secrets. No PII.
- No per-project RUNBOOK or PROJECT_STATE — those live in each project's own directory.
- No git repo (by design — the infra agent's commit target is `/opt/site-deploy/`, not this dir).

## Commit target

Always `/opt/site-deploy/`. Always via `git -C /opt/site-deploy ...` or inside a worktree under `/opt/worktrees/infra-*/` for larger tasks.
