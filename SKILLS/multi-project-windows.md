---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Multi-Project Windows

## When To Use

When spawning / closing / renaming project chats, or when you need to understand how the platform's tmux / Claude-Code / bookmark plumbing hangs together.

## The Model

Each active project gets its own Claude conversation in a separate tmux window inside the `claude` tmux session. This avoids context bloat and keeps projects isolated. The orchestrator chat (currently the `timeshare-surveillance` window) routes work across them.

## Commands

- **Spawn a project window:** `claude-project.sh <project> [cwd]`
  - Creates tmux window, starts `claude --continue` if prior JSONL exists, else `claude`.
  - Activates `/remote-control`, captures the session URL.
  - Writes bookmark at `/var/www/landing/remote/<project>.html` → redirects to current URL.
- **End a project window:** `end-project.sh <project>`
  - Refuses to close if `PROJECT_STATE.md` wasn't updated this session (override with `--force`).
- **Reactivate remote-control** (when a window's URL goes stale): `reactivate-remote.sh <project>`
- **Watchdog** auto-handles stale remote-control and missing windows — see `SKILLS/session-resilience.md`.

## Bookmarks

- Stable per project: `https://casinv.dev/remote/<project>.html`.
- Redirects to the current underlying session URL — survives session restarts and claude process churn.
- Updated automatically by `claude-project.sh` and `reactivate-remote.sh`.

## Expected-Window Registry

`/etc/claude-projects.conf` — one line per project: `<name> <cwd>`. Watchdog + respawn cron + boot service read this. Add a new project here once it's stable; remove when retiring.

## Orchestrator vs Project Chat

- **Orchestrator chat** (`casinv.dev/remote.html` or the `timeshare-surveillance` window today): not tied to a single project. Dispatches work, merges results, handles platform-level decisions. Owns CLAUDE.md and SKILLS edits; project chats propose via `CHANGES.md`.
- **Project chats:** one per project. Own their project's directory, tests, deploy script, and PROJECT_STATE.md. Do not touch shared infra.

## Dashboard

`https://casinv.dev/projects.html` shows every project's live / preview / remote-control links + current task + liveness badge (busy / idle / stuck / archived). Nav bar shows `/todo.html`, `/accounts.html`, `/capacity.html`.

## When To Spawn

- Starting work on a named project with any multi-turn task: spawn its window first.
- Multi-hour tasks: always use their own window so the orchestrator stays clear.
- Trivial one-off questions ("what does this file do?"): answer in whichever window, no spawn needed.

## Integration

- `SKILLS/session-resilience.md` — failure modes, handoff playbooks, the three mandatory habits.
- `SKILLS/remote-control-fallback.md` — what to do when `/remote-control` relay is down.
- `SKILLS/non-blocking-prompt-intake.md` — main thread is a coordinator, not an executor.
