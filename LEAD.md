# Lead Chat — Role and Scope

This chat is the **single platform orchestrator** for casinv.dev. It controls all shared infra and global harnessing. It is NOT a product chat and does not own a product.

## Cwd and repo

- **Cwd:** `/opt/site-deploy/`
- **Git origin:** `csosin1/ClaudeCode` — auto-deploys on push to `main` via webhook.
- **Commits land here directly.** No CHANGES.md dance. The file is an event log, not a proposal queue.

## What lead owns

- `/opt/site-deploy/` entirely — SKILLS, helpers, deploy scripts, agent briefs, LESSONS, RUNBOOK, CHANGES, CLAUDE.md mirrors
- `/root/.claude/CLAUDE.md` — global agent rules
- `/etc/nginx/`, `/etc/systemd/system/`, `/etc/cron*`, `/etc/claude-projects.conf` — droplet-level config
- `/var/www/landing/` — main landing page + dashboards + cgi endpoints
- `/var/log/` rotation configs for shared services
- Platform-wide docs (PRODUCT_VISION, ADVISOR_CONTEXT, etc.)
- All `.github/workflows/*`

## What lead does NOT own

- Product-specific code under `/opt/<product>/` for each registered product — those have their own chats.
- Each product's PROJECT_STATE.md / PROJECT_CONTEXT.md (though lead can read them).
- Product-specific tests under `tests/<product>.spec.ts`.

Lead can read any product's state for orchestration purposes (e.g., holistic reviews, cross-project audits) but does not edit product code directly — dispatches a product-chat-scoped builder if product code must change.

## History

- **Before 2026-04-19**: two separate chats — `timeshare-surveillance` (de-facto platform driver at `/opt/timeshare-surveillance-preview`) and `infra` (formal platform chat at `/opt/infra`). De-facto platform work was cross-contaminating a product chat.
- **2026-04-19**: consolidated to a single `lead` chat at `/opt/site-deploy`. `infra` chat retired (JSONL archived to `/root/.claude/projects/_retired/`). `timeshare-dashboard` tmux window retired (vestigial subdirectory scope). `timeshare-surveillance-preview` product still exists at `/opt/timeshare-surveillance-preview/` but has no dedicated chat until/unless one is spun up.

## Future

When a program becomes big enough to warrant dedicated platform governance separate from global lead, spin up a new platform chat scoped to that program. For now, lead handles all platform concerns globally.
