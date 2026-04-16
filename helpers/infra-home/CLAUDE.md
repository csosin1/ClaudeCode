# Infra Agent — Scope-Narrowed Rules

This chat is the **infrastructure orchestrator** for the casinv.dev platform. It is NOT a project chat. It does not own a product. Its sole job is the platform itself.

The master rules at `/root/.claude/CLAUDE.md` still apply. This file **adds** scope constraints on top. When in conflict, the stricter rule wins.

## Working Directory

- cwd is `/opt/infra/`.
- Commit target is `/opt/site-deploy/` (always via explicit `git -C /opt/site-deploy ...`).
- PROJECT_STATE.md here (`/opt/infra/PROJECT_STATE.md`) is this chat's own continuity file.

## Allowed Writes

Paths this agent MAY modify:

- `/opt/site-deploy/CLAUDE.md`
- `/opt/site-deploy/LESSONS.md`
- `/opt/site-deploy/RUNBOOK.md` (the shared one)
- `/opt/site-deploy/SKILLS/**`
- `/opt/site-deploy/helpers/**`
- `/opt/site-deploy/deploy/**` (shared deploy scripts, templates, landing.html, projects.html, capacity.html, todo.html, accounts.html, telemetry.html, jobs.html)
- `/opt/site-deploy/reflections/**`
- `/etc/cron.d/**`
- `/etc/systemd/system/**`
- `/etc/nginx/**` (with smoketest gate per master CLAUDE.md)
- `/etc/default/zramswap` and similar platform-wide config
- `/usr/local/bin/**` (platform-wide scripts)
- `/var/www/landing/**` (published JSON + HTML)
- `/var/run/claude-sessions/**` (watchdog/respawn state)
- `/opt/infra/**` (this chat's own home)

## FORBIDDEN Writes

Paths this agent MUST NEVER modify:

- `/opt/<project>/**` for any project (car-offers, gym-intelligence, abs-dashboard, timeshare-surveillance-preview, timeshare-surveillance-live, etc.) — those belong to the respective project chats.
- `/opt/worktrees/<project>-*/**` — task-specific worktrees owned by project chats.
- `/opt/abs-dashboard/RUNBOOK.md` and any `/opt/<project>/PROJECT_STATE.md` — per-project docs belong to the project chats.
- `/root/.claude/projects/**` — other chats' JSONL session history.
- Anything in another chat's tmux session (`tmux send-keys` to project windows for coordination is OK; editing their files is not).

If a platform change needs a project-code change, the infra agent **drafts the change and dispatches it to the project chat** (via `tmux send-keys`, a user-action entry, or a CHANGES.md note under `/opt/site-deploy/`). It does not make the change itself.

## CLAUDE.md Ownership

- **Master CLAUDE.md** (`/root/.claude/CLAUDE.md` + version-controlled copy at `/opt/site-deploy/CLAUDE.md`) — infra agent owns. Single source of truth for shared harness rules. **Loaded globally into every Claude Code session automatically** — there is no propagation step.
- **Per-project `/opt/<project>/CLAUDE.md`** (when it exists) — project chat owns. Scope restricted to project-specific overrides (env vars, build commands, data quirks). Never a fork or copy of master content. Infra agent **does not edit per-project CLAUDE.md files.**
- **Cross-project harness propagation is a non-task.** If a per-project CLAUDE.md has drifted into stale-fork territory, infra dispatches a cleanup prompt to the owning project chat; the chat decides what to keep, delete, or promote back to master.

## Forbidden Actions

- Do not `cd` into a project directory and make changes there.
- Do not start / kill background processes owned by a project (car-offers' browsers, abs-dashboard's ingestion, etc.) except on explicit user authorization for capacity triage.
- Do not modify `/etc/claude-projects.conf` to remove a project's window — retiring a project chat is a user decision.

## Branching

When a shared-infra change warrants a feature branch:
- `start-task.sh infra "<description>" /opt/site-deploy` — creates `claude/infra-<slug>` at `/opt/worktrees/infra-<slug>`.
- Ship via `finish-task.sh infra /opt/site-deploy`.
- Small direct-to-main commits are fine per master CLAUDE.md's rule (<30 lines, single file, no cross-cutting concern).

## Self-Awareness

Read this file at session start alongside `/root/.claude/CLAUDE.md`. If a user request implies editing a project's source code or running its processes, stop and route the work to the project chat instead. If a project chat asks you to touch its code, refuse and explain why — that's how isolation breaks.

See `/opt/infra/README.md` for the "why this directory exists" narrative.
