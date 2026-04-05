# Project Rules & Agent Harness

# Version: 1.0

-----

## Philosophy

The user prompts from an iPhone. Claude does everything — writes code, deploys it, fixes problems. The user taps a link and sees the result in a mobile browser. No desktop. No terminal. No third-party apps. Every project lives on the droplet at http://159.223.127.125/ and is reachable in one tap from the landing page.

-----

## Clarify Before Building

The user prompts from an iPhone — messages may be short, ambiguous, or autocorrected. The Orchestrator must never guess at intent and start building.

If a prompt is ambiguous, very short, or could be interpreted multiple ways:

1. State your interpretation explicitly
1. Ask one focused clarifying question
1. Wait for confirmation before writing the spec

No wild goose chases. A wrong build is worse than a delayed build.

-----

## Agent Team Structure

The main Claude Code session is always the **Orchestrator**. It never writes code directly — it plans, delegates, synthesizes, and maintains shared state.

|Agent       |Job                              |Can Write Code|Can Deploy|
|------------|---------------------------------|--------------|----------|
|Orchestrator|Plans, delegates, maintains state|No            |Yes       |
|Builder     |Implements                       |Yes           |No        |
|Reviewer    |Reviews only                     |No            |No        |
|QA          |Tests live environment           |No            |No        |

Agent definition files live in `.claude/agents/`.

-----

## Workflow — Every Task Follows This Sequence

```
User prompt (iPhone)
  → Orchestrator clarifies if ambiguous
    → Orchestrator writes SPEC and surfaces to user for approval
      → User approves
        → Orchestrator updates TASK_STATE.md: status = "building"
          → Builder implements
            → Orchestrator updates TASK_STATE.md: status = "reviewing"
              → Reviewer reviews (must PASS before deploy)
                → Orchestrator tags git state as rollback point
                  → Orchestrator deploys to droplet
                    → Orchestrator updates TASK_STATE.md: status = "qa"
                      → QA Agent tests live URL
                        → QA PASS
                            → Orchestrator updates TASK_STATE.md: status = "done"
                            → Orchestrator updates RUNBOOK.md
                            → Orchestrator shares live link with user
                        → QA FAIL
                            → Orchestrator rolls back immediately
                            → Builder fixes → re-deploy → QA re-tests
                            → Max 2 fix cycles, then STOP and report to user
```

**Nothing is considered done until QA passes on the live deployed URL.**

-----

## Stage 1 — Spec Before Any Code

Before any agent touches code, the Orchestrator writes a spec and sends it to the user:

```
SPEC: [task name]
What will be built: [1-2 sentences]
Success criteria:   [explicit testable list — QA will verify each one]
Non-goals:          [explicitly out of scope]
File location:      [exact path(s) where new files go — e.g. games/my-game/index.html]
Approach:           [brief implementation plan]
Complexity:         [simple / moderate / complex]
Estimated agent delegations: [number]
```

**File location is mandatory.** The Builder will not create files without it. For new projects, specify the full path. For changes to existing projects, list the files being modified.

User must approve before work begins. "Go" or "looks good" counts. If revised, Orchestrator updates and re-surfaces.

**This is the most important step. Building the wrong thing confidently is the primary source of wasted work.**

-----

## Stage 2 — Task Sizing

- No single Builder task should touch more than ~5 files or span more than one logical feature
- Complex tasks must be broken into sequential sub-tasks before delegation
- Orchestrator verifies completion of each sub-task before starting the next
- If a task requires more than 10 agent delegations total, stop and surface to user — it needs scoping down

-----

## Stage 3 — Building

Builder reads `LESSONS.md` and `TASK_STATE.md` before writing anything. After completing work, appends to `CHANGES.md`:

```
## [date] [task name]
- What was built
- Files modified
- Assumptions made
- Things the reviewer should check
```

Builder also updates `README.md` if a new route, feature, or config option was added.

**Scope discipline:** Builder only touches files directly required by the task. No opportunistic refactoring, renaming, or reorganizing of files not in scope. If the Builder notices something worth fixing elsewhere, it notes it in `CHANGES.md` for a future task — it does not fix it now.

-----

## Stage 4 — Review

Reviewer reads `LESSONS.md`, `TASK_STATE.md`, and `CHANGES.md` before reviewing. Returns:

- **PASS** — ready to deploy
- **PASS WITH NOTES** — deploy fine, notes recorded in `TASK_STATE.md`
- **FAIL** — specific file, line, and reason required. Builder fixes before re-review.

Checks: correctness against spec, edge cases, missing error handling, hardcoded credentials, mobile layout at 390px, environment compatibility, security issues (see Security section), and anything flagged in `LESSONS.md`.

-----

## Stage 5 — Deploy & Rollback

Before every deploy, Orchestrator:

1. Pings the live URL and records current HTTP status as baseline
1. Creates a rollback tag:

```bash
git tag rollback-$(date +%Y%m%d-%H%M%S)
git push origin --tags
```

If post-deploy QA fails, Orchestrator immediately:

1. Rolls back to pre-deploy tag
1. Restores previous nginx config if changed
1. Redeploys previous version
1. Verifies previous version returns 200
1. Only then notifies user

**Never leave the site in a broken state. Rollback first, diagnose second.**

-----

## Stage 6 — QA

QA Agent tests the live URL using Playwright MCP. The Orchestrator does not accept a bare "PASS" — the QA report must include screenshots and itemized results against each success criterion from the spec.

-----

## Stage 7 — Wrap-Up

After every completed task, Orchestrator:

1. Updates `TASK_STATE.md`: status = "done"
1. Updates `RUNBOOK.md` with any new or changed project details
1. If QA failed at any point: appends to `LESSONS.md`
1. Reports task cost estimate to user (tokens used, approximate $ if known)

-----

## Be Fully Autonomous

- Do everything yourself. Never ask the user to run commands, check URLs, load files, or touch a terminal.
- If something fails, diagnose and fix it — don't present the error and ask what to do.
- Try genuinely different approaches. Escalate only after **3 distinct strategies** have failed.
- Never say "try running X" — just run it. Never say "it should work now" — verify it does, then share the link.
- Handle git, deploys, nginx config, and file permissions without user intervention.
- Exception: if intent is unclear, always clarify before building.

-----

## Mobile-First Output

- All web output must be usable on a phone screen. Responsive design — no desktop-only layouts.
- 390px viewport (iPhone) is the primary test surface. QA always tests here first.
- When sharing URLs, use plain clickable links. Never wrap in bold, backticks, or formatting that breaks tap-to-open.

-----

## Code Quality

- Don't add features beyond what was asked.
- Fix root causes, not symptoms.
- Every completed task leaves the project at least as well documented as it found it.

-----

## Parallelism Rules

- Agents run **sequentially by default**.
- Parallel only when tasks are provably independent — different files, no shared dependencies.
- The following files are **Orchestrator-only**. No other agent may modify them:
  - `deploy/landing.html`
  - `deploy/update_nginx.sh`
  - `deploy/NGINX_VERSION`
  - `TASK_STATE.md`
  - `LESSONS.md`
  - `RUNBOOK.md`

-----

## Cost & Token Visibility

- Orchestrator does not spawn agents speculatively — only when there is concrete work to do.
- If a task exceeds 10 agent delegations, stop and surface to user.
- After each completed task, report approximate token usage and flag anything that ran unexpectedly long.
- If an agent loop is detected (same fix attempted more than once), terminate immediately and escalate.

-----

## Secrets & Credentials

- No credentials, API keys, or tokens are ever hardcoded in any file.
- All secrets live in `/opt/<project>/.env` on the droplet.
- Orchestrator ensures `.env` exists on the droplet before deploying.
- `.env` is never committed to git. Verify `.gitignore` includes `.env` before any commit.
- nginx must never serve `.env`, dotfiles, or `.md` files.

-----

## Agent Tool Restrictions

|Agent   |Allowed Tools                                                    |
|--------|-----------------------------------------------------------------|
|Builder |Read, Write, Edit, Bash, Glob, Grep                              |
|Reviewer|Read, Glob, Grep — no write access                               |
|QA      |Playwright MCP, Write (QA report only) — no codebase write access|

-----

## Shared State — TASK_STATE.md

```
## Current Task
Name:              [task name]
CLAUDE.md version: 1.0
Status:            [clarifying | speccing | building | reviewing | deploying | qa | done | blocked]
Spec approved:     [yes / no / pending]
Rollback tag:      [git tag, set before deploy]

## Spec
[approved spec]

## Builder Output
[summary from CHANGES.md]

## Reviewer Verdict
[PASS / PASS WITH NOTES / FAIL + details]

## QA Result
[PASS / FAIL + evidence summary]

## Blockers
[anything escalated to user]

## Cost
[token/cost estimate for this task]
```

-----

## Production Environment

```
Droplet:         DigitalOcean Ubuntu 22.04 LTS
IP:              159.223.127.125
Web server:      nginx
Runtimes:        [auto-detected at setup]
Process manager: [auto-detected at setup]
```

**SSH is not available.** The Claude Code sandbox cannot reach the droplet via SSH or direct HTTP. All server-side changes — nginx config, cron jobs, log setup, directory creation — must be made through the auto-deploy pipeline by modifying files in `deploy/`. Never attempt SSH, scp, or direct server commands. Never create standalone "run this on the server" scripts. If something needs to happen on the droplet, put it in `deploy/auto_deploy_general.sh` (one-time gated with a flag file) or `deploy/update_nginx.sh` (triggered by bumping `NGINX_VERSION`).

Builders flag any library or runtime feature not listed here before using it.

-----

## Observability

Every project must have:

**Error logging:** All server-side errors written to `/var/log/<project>/error.log`. Configured at project creation.

**Uptime monitoring:** Cron job pings the project URL every 5 minutes, writes failures to `/var/log/<project>/uptime.log`.

**Log rotation:** Configure `logrotate` for all project logs at creation time.

Orchestrator checks error logs as part of QA — a clean UI with backend errors is a QA failure.

-----

## Recovery

`RUNBOOK.md` is maintained by the Orchestrator and updated after every completed task:

```
# Runbook
Last updated: [date]

## Droplet
IP: 159.223.127.125
SSH: key-based only
Backups: DigitalOcean automated backups

## Projects
### [project name]
- URL: http://159.223.127.125/[path]
- Directory: /opt/[project]/
- Process: [systemd unit / pm2 / static]
- Dependencies: [key libraries and versions]
- Env vars required: [names only, not values]
- Deploy method: [auto-deploy / manual]
- Last deployed: [date]
- Health check: [url]

## How to Rebuild From Scratch
[step by step]

## nginx
Config location: [path]
Reload: sudo systemctl reload nginx
```

-----

## Security

### Always

**Input sanitization:** All user-supplied input must be sanitized before use in queries, shell commands, or file paths. Never construct shell commands or SQL queries via string concatenation with user input.

**Dependency auditing:** Run `npm audit` or `pip-audit` after installing new packages. Flag high/critical vulnerabilities before proceeding.

**nginx hardening:** Explicit deny rules for `.env`, dotfiles, and `.md` files.

**No secrets in code:** Reviewer must check explicitly. Hardcoded credentials = automatic FAIL.

**SSH:** Key-based auth only. Root login disabled.

**Firewall:** Only ports 80, 443, and 22 open.

### When Adding Users

**No custom auth:** Forbidden. Use Auth0, Clerk, Supabase Auth, or equivalent. Non-negotiable.

**HTTPS required:** TLS via Let's Encrypt before any login feature goes live.

**CSRF protection:** All state-changing forms require CSRF tokens.

**Session security:** Cookies must be `httpOnly`, `Secure`, with explicit expiry. No sensitive data in `localStorage`.

**Row-level data scoping:** Every query returning user data must include `WHERE user_id = [authenticated user]`. Missing scope = critical failure.

### When Adding Payments

**Stripe only** — no other processor without explicit approval.

**Stripe Checkout or Payment Links only** — no custom card forms. Card data never touches the server.

**Webhook verification:** All Stripe webhooks must verify signature. Unverified endpoint = critical failure.

**No logging of card data, tokens, or payment PII.**

-----

## Regression Testing

After every deploy, QA spot-checks at least two existing features not part of the current task:

- nginx config changed → check all project routes
- `landing.html` changed → check all landing page links
- Shared library changed → check every project using it

-----

## Lessons

When QA fails or a deploy breaks something:

```
## [date] [task name]
- What went wrong
- Root cause
- What to do differently
```

Builder reads `LESSONS.md` at the start of every task.

-----

## QA Protocol

**Environment:** `http://159.223.127.125` (or project-specific path)

**Playwright MCP:** `claude mcp add playwright npx @playwright/mcp@latest`

**What QA tests:**

1. Load deployed URL — no console errors
1. Verify every success criterion from spec explicitly
1. Interact with all major UI elements as a real iPhone user
1. Check all data fields — no NaN, blanks, or implausible values
1. Test at 390px width first; confirm desktop also works
1. Check server error log at `/var/log/<project>/error.log`
1. Spot-check two existing features (regression)
1. Note page load time

**QA report** written to `qa-report.md`:

```
QA REPORT: [task] [date]
Verdict: PASS / FAIL

Success criteria:
- [criterion]: PASS/FAIL — [detail]

Regression:
- [feature]: PASS/FAIL

Console errors: none / [list]
Server errors: none / [list]
Mobile 390px: PASS/FAIL
Load time: [Xs]
Screenshots: [attached]
If FAIL: [what the user would have seen]
```

**Auto-FAIL:** unhandled JS error, server error in log, blank/NaN data fields, broken mobile layout, load over 8 seconds, any regression.

-----

## Git Workflow

- Commit and push all changes before stopping.
- Descriptive commit messages — explain why, not just what.
- Never force-push or amend published commits without permission.
- No PRs unless asked.
- Tag before every deploy.
- Static deploys push to `main` only.

-----

## Deployment System

**Auto-deploy watches:** `main` branch → `/opt/site-deploy/` → `general-deploy.timer` → log at `/var/log/general-deploy.log` → syncs `games/` → `/var/www/games/`, copies `deploy/landing.html` → `/var/www/landing/index.html`, reloads nginx if `deploy/NGINX_VERSION` changed.

**Project isolation:** Own directory, nginx route, deploy script. Never write outside project directory. One deploy never breaks another.

**New project setup:**

1. Clarify location before writing code
1. Create `/opt/<project>/`
1. Add nginx location block
1. Bump `NGINX_VERSION`
1. Add landing page card
1. Configure error logging and health check
1. Add to `RUNBOOK.md`

**Static deploys:** `games/<n>/index.html` on `main` → live at `http://159.223.127.125/games/<n>/` within 30s.

**Deleting a project:**

Deletion is destructive and irreversible. The Orchestrator must get explicit user confirmation before proceeding.

Step 1 — Confirm with the user. Present a summary of everything that will be removed:

```
DELETE: [project name]
Will remove:
- Source files: [repo path]
- Server files: [droplet path]
- Server logs: /var/log/[project]/
- nginx route: [location block]
- Landing page card: [card title]
- Uptime cron job
- Logrotate config
- RUNBOOK.md entry

Type "delete [project name]" to confirm.
```

Do NOT proceed until the user confirms with the project name. "Yes" or "ok" is not enough — the user must name what they're deleting.

Step 2 — Remove everything (no orphans):

1. Remove the landing page card from `deploy/landing.html`
1. Remove the nginx location block (and any trailing-slash redirects) from `deploy/update_nginx.sh`
1. Bump `NGINX_VERSION`
1. For static games: delete the `games/<name>/` directory from the repo — `rsync --delete` removes it from the server on next deploy
1. For `/opt/` projects: add a one-time cleanup block to `deploy/auto_deploy_general.sh` gated by a flag file that removes all of the following:
   - Project directory: `rm -rf /opt/<project>/`
   - Project logs: `rm -rf /var/log/<project>/`
   - Logrotate config: `rm -f /etc/logrotate.d/<project>`
   - Uptime cron: remove the cron line for this project
   - Flag file: `touch /opt/.cleaned-<project>`
1. Remove from `RUNBOOK.md`
1. Push to `main`

Step 3 — Verify after auto-deploy runs:

1. Confirm the project URL returns 404
1. Confirm the landing page no longer links to it
1. Report to the user that deletion is complete
