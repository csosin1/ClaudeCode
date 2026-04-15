# Skill: New Project Checklist

## When To Use

When the user asks to create a new project on the droplet. Not on every project — only at project genesis.

## The Checklist

Every new project ships with **both** a live URL and a preview URL. Claude's work always lands on preview; live only changes when the user says "ship it."

1. Create `/opt/<name>/{live,preview}/` (or `games/<name>/{live,preview}/` for static games).
2. Add **two** nginx location blocks in `deploy/update_nginx.sh` — `/<name>/` (live) and `/<name>/preview/` — and bump `NGINX_VERSION`.
3. Add a link card on `deploy/landing.html` pointing at the **live** URL (not preview).
4. Create `deploy/<name>.sh` that:
   - builds/installs to `preview/`,
   - exposes a promote step that rsyncs `preview/` → `live/` (or swaps active port for services) only when a promote marker is set.
5. Set up `/var/log/<name>/` with logrotate and a 5-minute uptime cron (against the live URL).
6. Add a `RUNBOOK.md` entry including both URLs.
7. Create `PROJECT_STATE.md` from `deploy/templates/PROJECT_STATE.md.template`.
8. Add `<name> /opt/<name>` to `/etc/claude-projects.conf` if this project should have an auto-respawned chat window.

## Completion Criterion

**If it's not linked from http://159.223.127.125/, it's not done.**

## Integration

- `SKILLS/deploy-rollback.md` — the promote / rollback flow this checklist prepares for.
- `SKILLS/session-resilience.md` — PROJECT_STATE.md conventions.
- `SKILLS/multi-project-windows.md` — claude-projects.conf + chat-window lifecycle.
