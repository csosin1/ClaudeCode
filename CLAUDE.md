# Agent Rules

## User Context
The user is non-technical and prompts from an iPhone. Claude owns technical decisions — don't surface jargon or ask the user to pick between implementation options. When a choice has real product trade-offs, explain them in plain terms and recommend one. Never ask the user to run a command, read a log, or paste output.

**URLs in messages must be plain, never wrapped in markdown formatting.** iOS URL detection in the chat grabs surrounding characters like `**`, `)`, or backticks and includes them in the tap target, producing 404s on the server. Write URLs on their own line with a space before and after, never as `**https://...**` or `[text](https://...)` or \`\`https://...\`\`.

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
- `PROJECT_STATE.md` — per-project "where we left off" log (see Session Continuity below)
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
7. Create `PROJECT_STATE.md` from `deploy/templates/PROJECT_STATE.md.template`

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
- `PROJECT_STATE.md` — per-project "where we left off" log (see Session Continuity).

## Session Continuity
Every project has a `PROJECT_STATE.md` at its root with four fixed sections: **Current focus**, **Last decisions**, **Open questions**, **Next step**.

- **On entry to a project window:** read `PROJECT_STATE.md` first, before any other work. It is the bridge between sessions. `claude-project.sh` prompts the AI to read it automatically on spawn.
- **Before ending a turn:** update it if anything about focus, decisions, open questions, or next step has changed. `end-project.sh` refuses to close a window whose `PROJECT_STATE.md` wasn't touched during the session (override with `--force`).
- **Keep it short.** Four sections, no history. Git covers history; this file is the present.
- **Missing file?** Create from `deploy/templates/PROJECT_STATE.md.template`.

## Multi-Project Windows
Each active project gets its own Claude conversation in a separate tmux window. Avoids context bloat and keeps projects isolated.

- **Spawn a project window:** `claude-project.sh <project> [cwd]` — creates tmux window, starts Claude, activates /remote-control, writes bookmark to `/remote/<project>.html`.
- **End a project window:** `end-project.sh <project>`.
- **Bookmarks:** `https://casinv.dev/remote/<project>.html` (stable per project; redirects to current session URL).
- **Main window:** `https://casinv.dev/remote.html` is the general-purpose orchestrator chat (not tied to a project).
- **Dashboard:** `https://casinv.dev/projects.html` shows every project's live/preview/remote links and current task.

When starting work on a named project, spawn its window first. Multi-hour tasks should use their own window so the orchestrator chat stays clear.

## Feature-Branch Workflow (recommended for multi-project parallelism)
For anything more than a small fix, use feature branches so parallel projects don't collide on main:

- **Start a task:** `start-task.sh <project> "<description>"` — creates branch `claude/<project>-<slug>` from origin/main, sets task status.
- **Do the work:** commit as normal on the branch. Pushing the branch does NOT deploy — only main deploys.
- **Ship to preview:** `finish-task.sh <project>` — merges the branch into main, pushes, updates task status. Auto-deploy handles the rest.
- **User says "ship it":** `bash /opt/site-deploy/deploy/promote.sh <project>` — promotes preview → live.

Small fixes can still push directly to main.

## Remote-Control Fallback
`/remote-control` session URLs depend on Anthropic's relay. If the Claude app stays on "Remote Control connecting…" forever, fall back to the web terminal:

- Open https://code.casinv.dev on any device (it's the droplet's ttyd web terminal)
- Type `tmux attach -t claude` to join the main session, or use `tmux attach -t claude \; select-window -t <project>` for a project window
- Detach with Ctrl-B then D

iPhone keyboards on a terminal aren't ideal, but this path doesn't depend on relays working.

## Cost Visibility
Claude includes an approximate token-usage summary in every `task-status.sh done` call, so the user can see how expensive each task was. Format: `task-status.sh done <project> "<name>" "completed; ~42k tokens"`. The dashboard surfaces this.

## Context Compaction
Long sessions degrade response quality. At natural checkpoints (task done, big milestone, end of a QA iteration cycle), run `/compact` to trim conversation history. Always before continuing to a new task in the same window.

## Autonomy
Do the work. Don't ask the user to run commands, read logs, or verify URLs. Escalate only after genuinely different approaches have failed. Never say "it should work" — verify, then share the link.

## Never Idle — Gather Blockers Upfront, Work Around the Rest
The user's time is the scarce resource. Do not end a turn waiting for permission when any useful work remains.

**At task start, produce a blocker brief.** While the user is still paying attention, enumerate every permission, secret, external account, domain, or piece of info you'll need. Ask for them all in one batch. Examples: GitHub token scopes, API keys (Stripe / Anthropic / OpenAI), third-party logins (Auth0, Cloudflare, SendGrid), DNS control, billing setup, access to existing data sources.

**While waiting for answers, keep making progress.** Do everything that doesn't depend on the pending items: scaffolding, tests, stubs, mocks, docs, infrastructure, research. Leave clean hooks for the blocking pieces so they slot in when answers arrive.

**If you discover a blocker mid-work:** add it to the running brief, immediately pivot to unblocked work, batch the new ask with any other pending asks. Never stop and wait.

**Never emit phrases like:** "want me to continue?", "should I proceed?", "tell me if…". Just act. If a decision is genuinely irreversible or externally visible (per the autonomy memory), state the plan and execute unless stopped.

**Examples of legitimately ending a turn:** everything is blocked on user input AND there's no further work you can do; task is complete and QA green; scope exploded into hours of new work that warrants a revised estimate.

## Keep-the-User-Informed Conventions
- **Scope upfront.** Before starting any non-trivial task, state estimated duration (e.g., "~15 min", "~1 hr", "~3 hr with multiple iterations"). User may walk away between prompt and completion; they need to know when to check back.
- **Task status file.** Call `/usr/local/bin/task-status.sh set "<name>" "<stage>" "<detail>"` when starting a task; `task-status.sh done "<name>" "<summary>" <preview_url>` when finished; `task-status.sh clear` when fully handed off. This updates `https://casinv.dev/tasks.json` which the user can tap anytime to see current state.
- **Notifications.** Push notifications fire automatically on every preview deploy via the webhook. For discrete milestones (task ready to review, QA failed after N cycles, blocker surfaced), call `/usr/local/bin/notify.sh "message" "title" priority "click-url"` directly. Priorities: `urgent` for hard blockers needing input; `high` for task done; `default` for routine updates.
- **Token-cost guardrail.** If a single task looks like it will exceed ~200k tokens or has burned through that much without reaching QA-green, stop and surface the scope blowout via `notify.sh` with `urgent` priority. Do not spiral.
- **Stuck detector.** If the same fix is attempted twice without making progress (e.g., same test failure after two edits to the same file), stop. Update `/tasks.json` via `task-status.sh set "<name>" blocked "<what's blocking>"` and notify the user. Don't attempt a third identical fix.
- **GitHub Actions QA.** Read QA run results with `gh run list --branch main --limit 5` / `gh run view <id>` — `GH_TOKEN` is pre-configured in the environment.

## Git
- Commit and push before stopping; commit messages explain *why*.
- Tag before every deploy. No force-push to published commits. Main branch only.
