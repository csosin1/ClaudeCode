# Agent Rules

## User Context
The user is non-technical and prompts from an iPhone. Claude owns technical decisions — don't surface jargon or ask the user to pick between implementation options. When a choice has real product trade-offs, explain them in plain terms and recommend one. Never ask the user to run a command, read a log, or paste output.

## Setup
- Droplet: DigitalOcean Ubuntu 22.04 at 159.223.127.125. nginx in front, systemd for services. Claude has SSH; prefer the deploy pipeline for anything reproducible.
- Mobile-first output. Every project reachable in one tap from http://159.223.127.125/.
- Repos auto-deploy to `/opt/<project>/` on push to `main` via webhook (2–3s).

## Clarify Before Building
iPhone prompts are short and sometimes autocorrected. If a request is ambiguous, state your interpretation and ask one focused question. A wrong build done confidently is the most expensive outcome.

## Every Task Passes Three Gates
Nothing defective reaches the user. Each task runs through three checkpoints — use subagents so each has a fresh perspective.

1. **Build** — Builder subagent writes the feature AND Playwright tests in `tests/<project>.spec.ts`. Tests that exercise the feature like a user (click, fill, assert real values — no NaN/blanks) are required, not optional.
2. **Review** — Reviewer subagent reads the diff against the spec, `LESSONS.md`, and the security baseline. Must return PASS before deploy. FAIL comes back with file, line, and reason.
3. **QA** — push to `main` deploys to the project's **preview URL**. `.github/workflows/qa.yml` runs Playwright against preview at 390px and 1280px. Regressions in other features count as failures. On fail: fix and redeploy to preview, no approval needed.
4. **Accept** — when QA is green, share the preview URL with the user. Their "ship it" is the only approval gate in the whole flow. On accept: promote preview → live. On "change it": iterate on preview without asking permission.

The main session orchestrates — it does not write code directly.

## Spec Before Any Code
Surface to the user and wait for "go":
- What will be built (1–2 sentences)
- Success criteria (what QA will verify)
- File location(s) — mandatory, no speculative paths
- Non-goals

## Project Isolation
Multiple projects share this droplet. Each project touches only its own files.

**Each project owns:**
- `/opt/<project>/` on the server (or `games/<name>/` for static)
- `deploy/<project>.sh` — install + systemd unit, sourced by the main deploy script
- `tests/<project>.spec.ts` — its Playwright tests
- Its nginx location block, systemd unit, `/var/log/<project>/`, logrotate config, uptime cron

**Shared — never modified from a project chat; propose via `CHANGES.md`:**
- `deploy/auto_deploy_general.sh`, `deploy/update_nginx.sh`, `deploy/NGINX_VERSION`
- `deploy/landing.html`
- `.github/workflows/*`
- `CLAUDE.md`, `LESSONS.md`, `RUNBOOK.md`, `.claude/agents/*.md`

A project chat writing outside its own paths is a bug.

## New Project Checklist
Every new project ships with **both** a live URL and a preview URL. Claude's work always lands on preview; live only changes when the user says "ship it."

1. Create `/opt/<name>/{live,preview}/` (or `games/<name>/{live,preview}/` for static)
2. Add **two** nginx location blocks in `deploy/update_nginx.sh` — `/<name>/` (live) and `/<name>/preview/` — and bump `NGINX_VERSION`
3. Add a link card on `deploy/landing.html` pointing at the **live** URL (not preview)
4. Create `deploy/<name>.sh` that (a) builds/installs to `preview/`, (b) exposes a promote step that rsyncs `preview/` → `live/` (or swaps active port for services) only when a promote marker is set
5. Set up `/var/log/<name>/` with logrotate and a 5-minute uptime cron (against the live URL)
6. Add a `RUNBOOK.md` entry including both URLs

If it's not linked from http://159.223.127.125/, it's not done.

## Deploy & Rollback
- Every push to `main` deploys to **preview only**. Preview is where all iteration happens.
- Promotion from preview → live happens via an explicit marker file or deploy flag set by the orchestrator only after the user accepts. Implementations vary per project (rsync for static, active-port swap for services) but the principle is the same: live never changes without user acceptance.
- Before every **promote**: `git tag rollback-$(date +%Y%m%d-%H%M%S) && git push origin --tags`.
- If live is ever broken: roll back to the tag, restore previous nginx if changed, verify 200, then report.

## Secrets
- No credentials in git. `.gitignore` includes `.env`. nginx denies `.env`, dotfiles, `.md`.
- Secrets live in `/opt/<project>/.env` on the droplet, or GitHub Secrets for CI.
- For user-entered secrets from a phone, expose a `/setup` page in the app.

## Security Baseline
- Sanitize user input; no string-concat into shell or SQL.
- `npm audit` / `pip-audit` after adding deps; block on high/critical.
- No custom auth — Auth0, Clerk, or Supabase Auth only. HTTPS (Let's Encrypt) before any login ships.
- Stripe only for payments; Checkout or Payment Links (never custom card forms); verify webhook signatures.
- Row-level scoping on user-data queries. Missing `WHERE user_id=…` is a critical failure.
- Firewall: 80, 443, 22. Root SSH disabled, key auth only.

## Skills Registry
Reusable patterns live in `SKILLS/*.md`. Check there before implementing anything non-trivial. Promote any hard-won lesson into a skill so it isn't relearned.

## State Files (read first, update as you work)
- `TASK_STATE.md` — current task stage; the recovery lifeline if a session dies mid-task.
- `LESSONS.md` — append when something breaks. Builders and Reviewers read it first.
- `CHANGES.md` — Builder's per-task log for the Reviewer.
- `RUNBOOK.md` — per-project facts: URL, path, deps, env var names, health check.

## Autonomy
Do the work. Don't ask the user to run commands, read logs, or verify URLs. Escalate only after genuinely different approaches have failed. Never say "it should work" — verify, then share the link.

## Git
- Commit and push before stopping; commit messages explain *why*.
- Tag before every deploy. No force-push to published commits. Main branch only.
