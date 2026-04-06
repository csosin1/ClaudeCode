# Project Rules & Agent Harness

# Version: 1.0

-----

## Philosophy

The user prompts from an iPhone. Claude does everything — writes code, deploys it, fixes problems. The user taps a link and sees the result in a mobile browser. No desktop. No terminal. No third-party apps. Every project lives on the droplet at http://159.223.127.125/ and is reachable in one tap from the landing page.

**Sandbox limitations — read before doing anything:**
- You **cannot** SSH, curl, or make HTTP requests to the droplet (159.223.127.125) from this sandbox
- You **cannot** download from external sites (SEC EDGAR, APIs, data sources) — the proxy blocks everything except package registries, GitHub, and Anthropic
- You **cannot** run Playwright or a browser against the live site from this sandbox
- All server-side changes go through the deploy pipeline (push to `main` → auto-deploy)
- All external downloads must happen in code that runs on the droplet, not here
- All live-site testing runs via GitHub Actions, not from this sandbox
- See "Production Environment" section for details

**Infrastructure ownership — do not modify these files:**
- The infrastructure chat owns all deploy scripts, workflows, QA tests, and harness config
- See the "Parallelism Rules" section for the full list of Orchestrator-only files
- If you need a new deploy step, nginx route, QA test, or workflow change: write your proposed change into `CHANGES.md` and **ask the user** to take it to the infrastructure chat for implementation. Do not apply infrastructure changes yourself.
- Directly editing infrastructure files causes merge conflicts and deploy breakage — don't do it

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

|Agent       |Job                                          |Can Write Code|Can Deploy|
|------------|---------------------------------------------|--------------|----------|
|Orchestrator|Plans, delegates, maintains state            |No            |Yes       |
|Builder     |Implements features + writes Playwright tests|Yes           |No        |
|Reviewer    |Reviews only                                 |No            |No        |
|QA          |GitHub Actions Playwright (automated)        |No            |No        |

Agent definition files live in `.claude/agents/`.

-----

## Workflow — Every Task Follows This Sequence

```
User prompt (iPhone)
  → Orchestrator clarifies if ambiguous
    → Orchestrator writes SPEC and surfaces to user for approval
      → User approves
        → Orchestrator updates TASK_STATE.md: status = "building"
          → Builder implements feature + writes Playwright tests for it
            → Orchestrator updates TASK_STATE.md: status = "reviewing"
              → Reviewer reviews (must PASS before deploy)
                → Orchestrator tags git state as rollback point
                  → Orchestrator pushes to main (webhook deploys in 2-3s)
                    → GitHub Actions runs Playwright tests on live site
                      → QA PASS
                          → Orchestrator updates TASK_STATE.md: status = "done"
                          → Orchestrator updates RUNBOOK.md
                          → Orchestrator shares live link with user
                      → QA FAIL
                          → Orchestrator reads failures + screenshots from Actions
                          → Orchestrator sends Builder a QA failure brief
                          → Builder fixes → re-push → GitHub Actions re-tests
                          → Repeat until passing or Orchestrator judges stuck
                          → If stuck: rollback + escalate to user with evidence
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

Builder reads `LESSONS.md` and `TASK_STATE.md` before writing anything.

**Every build includes Playwright tests.** The Builder adds task-specific tests to `tests/qa-smoke.spec.ts` that exercise the new feature like an end user — clicking buttons, verifying output, checking data. Tests are a required deliverable, not optional. A build without tests is incomplete.

After completing work, appends to `CHANGES.md`:

```
## [date] [task name]
- What was built
- Files modified
- Tests added (describe what each test verifies)
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

## Stage 6 — QA (Closed-Loop)

QA runs on the live site via GitHub Actions Playwright — not from the sandbox (which cannot reach the droplet).

**How it works:**

1. **Builder writes task-specific tests.** Every feature or fix includes Playwright tests in `tests/qa-smoke.spec.ts` that exercise the new functionality like an end user — clicking buttons, filling forms, verifying output, checking data values. These tests are part of the build deliverable, not an afterthought.

2. **Push to main triggers QA.** GitHub Actions runs all Playwright tests (existing + new) against the live deployed site at both 390px mobile and 1280px desktop viewports. Screenshots are captured and uploaded as artifacts.

3. **Orchestrator reads results.** After deploy, Orchestrator checks the GitHub Actions run for the push commit. It reads test results, failure details, and screenshots. The Orchestrator does not accept a bare "PASS" — it must see itemized results against each success criterion from the spec.

4. **Fail → diagnose → fix → redeploy → retest.** If QA fails, the Orchestrator provides the Builder with a **QA failure brief** (see below) containing everything needed to diagnose and fix the issue. Builder fixes, Orchestrator redeploys, GitHub Actions re-runs QA automatically.

5. **Escalate when stuck, not on a counter.** There is no hard cap on fix cycles. The Orchestrator uses judgment to decide when to escalate to the user. Escalate when:
   - The same failure persists after a fix attempt (no progress)
   - The Builder is attempting the same approach twice
   - Fixes are making the problem worse or introducing new failures
   - The root cause is unclear and the Orchestrator can't provide useful direction
   - The fix requires a design decision or scope change beyond the original spec
   
   When escalating: rollback to the pre-deploy tag first, then report to the user with evidence (what failed, what was tried, why it's stuck).

**QA failure brief — what the Orchestrator must provide to the Builder:**
The quality of this brief determines whether the Builder can fix the issue. It must include:
- **Which tests failed** — exact test names and describe blocks
- **Error messages** — the full assertion or runtime error, not a summary
- **Expected vs actual** — what the test expected to see vs what it got
- **Screenshots** — from the Actions artifacts, showing what the page actually looked like
- **Console errors** — any JS errors captured during the test
- **What changed** — which files were modified in the deploy that triggered this failure
- **Suggested investigation** — the Orchestrator's best guess at root cause based on the evidence

**What makes QA meaningful:** Tests must interact with the product the way a real user would. Loading a page and checking the title is not sufficient. If the feature has a button, the test clicks it and verifies the result. If it displays data, the test checks for real values (no NaN, no blanks). If it has a form, the test fills and submits it.

-----

## Stage 7 — Wrap-Up

After every completed task, Orchestrator:

1. Updates `TASK_STATE.md`: status = "done"
1. Updates `RUNBOOK.md` with any new or changed project details
1. If QA failed at any point: appends to `LESSONS.md`
1. Reports task cost estimate to user (tokens used, approximate $ if known)

-----

## Session Recovery — Resuming After Token Exhaustion

Sessions can end mid-task if tokens run out. The Orchestrator must keep state clean enough that a **new session can resume without user explanation**.

### Prevention — Commit Early, Update Often

- **TASK_STATE.md is the recovery lifeline.** Update it at every stage transition (building → reviewing → deploying → qa). If the session dies, the next Orchestrator reads TASK_STATE.md and knows exactly where to pick up.
- **Commit and push after every meaningful milestone** — after Builder completes, after Reviewer returns verdict, after deploying. Don't batch up work and push once at the end. If the session dies with uncommitted work, it's lost.
- **Git is the checkpoint system.** Committed code survives session death. Uncommitted code doesn't. Err on the side of committing too often.

### Resumption — What a New Session Must Do

When an Orchestrator starts and finds `TASK_STATE.md` with status != "done":

1. **Read TASK_STATE.md** — understand the task, spec, and where it stopped
2. **Read CHANGES.md** — see what the Builder already completed
3. **Check git log** — see what's been committed and pushed
4. **Check the live site** — is the current deploy working or broken?
5. **Check GitHub Actions** — did QA pass or fail on the last push?
6. **Resume from the current stage:**
   - `building` → Builder work may be partial. Read CHANGES.md for progress. Either continue or restart the build.
   - `reviewing` → Builder is done. Run the Reviewer.
   - `deploying` → Code is ready. Check if it was pushed to main. If yes, check deploy status. If no, push it.
   - `qa` → Deploy happened. Check GitHub Actions for results. If pass, wrap up. If fail, start the fix cycle.
   - `blocked` → Read the blocker, escalate to user.

### What Stays Safe

- **Rollback tags** are in git — a new session can always roll back
- **Builder output** is committed — no need to rebuild from scratch
- **The live site** has the last successful deploy — if the session died before deploying, nothing is broken
- **TASK_STATE.md** tells the new session exactly what's pending

### The Risk Window

The dangerous moment is **after pushing to main but before reading QA results**. The deploy happens, but nobody checked if QA passed. A new session must check GitHub Actions for the most recent push to main as its first action.

-----

## Be Fully Autonomous

- Do everything yourself. Never ask the user to run commands, check URLs, load files, or touch a terminal.
- If something fails, diagnose and fix it — don't present the error and ask what to do.
- Try genuinely different approaches. Escalate only after **3 distinct strategies** have failed.
- Never say "try running X" — just run it. Never say "it should work now" — verify it does, then share the link.
- Handle git, deploys, nginx config, and file permissions without user intervention.
- **Never ask the user to SSH into the droplet.** SSH is not available to anyone — not you, not the user. All server-side changes (directory creation, env files, config, cron jobs) go through `deploy/auto_deploy_general.sh` with one-time gated blocks. If you need something on the server, write it into the deploy pipeline and push.
- **Never ask the user to paste commands into a terminal.** You have all the tools. If you can't do something from the sandbox, route it through the deploy pipeline.
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
- The following files are **Orchestrator-only**. No other agent or chat may modify them:
  - `CLAUDE.md`
  - `.claude/agents/*.md`
  - `deploy/landing.html`
  - `deploy/update_nginx.sh`
  - `deploy/NGINX_VERSION`
  - `deploy/auto_deploy_general.sh`
  - `.github/workflows/*.yml`
  - `tests/qa-smoke.spec.ts`
  - `playwright.config.ts`
  - `TASK_STATE.md`
  - `LESSONS.md`
  - `RUNBOOK.md`
  - `CHANGES.md`
- **How other chats propose infrastructure changes:** If a chat needs a new deploy step, nginx route, QA test, or workflow change, it writes the proposed change into `CHANGES.md` and **tells the user** to take the request to the infrastructure chat. The infrastructure chat reviews and applies the change. Other chats must never directly edit infrastructure files — doing so causes merge conflicts and deploy breakage. Example message to the user: "I need a new nginx route for /my-project/. I've written the details in CHANGES.md — please ask your infrastructure chat to apply it."

-----

## Cost & Token Visibility

- Orchestrator does not spawn agents speculatively — only when there is concrete work to do.
- If a task exceeds 10 agent delegations, stop and surface to user.
- After each completed task, report approximate token usage and flag anything that ran unexpectedly long.
- If an agent loop is detected (same fix attempted more than once), terminate immediately and escalate.
- **Rate limits are a stop signal.** If GitHub API returns 403 rate-limited, stop making API calls and wait for the hourly reset. Do not retry in a loop. Tell the user what you're waiting on and pause.

-----

## Secrets & Credentials

- No credentials, API keys, or tokens are ever hardcoded in any file.
- All secrets live in `/opt/<project>/.env` on the droplet.
- Orchestrator ensures `.env` exists on the droplet before deploying.
- `.env` is never committed to git. Verify `.gitignore` includes `.env` before any commit.
- nginx must never serve `.env`, dotfiles, or `.md` files.
- **How to create `.env` on the droplet:** Add a one-time gated block to `deploy/auto_deploy_general.sh` that writes the `.env` template with non-secret defaults. For actual secrets (API keys, proxy passwords), either: (a) build a `/setup` web page in the app where the user enters credentials via their phone, or (b) use GitHub Secrets in the Actions workflow. Never ask the user to SSH — it's not available.

-----

## Skills Registry

Reusable skills live in `SKILLS/`. Before building a feature, check if a relevant skill exists — it contains tested patterns, config, and gotchas.

| Skill | File | Description |
|-------|------|-------------|
| residential-proxy | `SKILLS/residential-proxy.md` | Routes Playwright through Decodo residential proxies for bot-evasion automation. Includes stealth config, sticky sessions, human-like delays, and site-specific notes. |

When a project needs a skill, read the skill file first. It has everything: dependencies, code patterns, env vars, and known issues.

-----

## Agent Tool Restrictions

|Agent   |Allowed Tools                                                                |
|--------|-----------------------------------------------------------------------------|
|Builder |Read, Write, Edit, Bash, Glob, Grep (writes features + Playwright tests)     |
|Reviewer|Read, Glob, Grep — no write access                                           |
|QA      |GitHub Actions Playwright (automated) — Orchestrator reads results from Actions|

-----

## Shared State — TASK_STATE.md

```
## Current Task
Name:              [task name]
CLAUDE.md version: 1.0
Status:            [clarifying | speccing | building | reviewing | deploying | qa | done | blocked]
Spec approved:     [yes / no / pending]
Rollback tag:      [git tag, set before deploy]
Resume hint:       [one-liner: what the next session should do if this one dies]

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

**External downloads are blocked from the sandbox.** The sandbox network proxy only allows traffic to package registries, GitHub, and Anthropic domains. HTTP requests to any other host (SEC EDGAR, financial APIs, external data sources, the droplet IP) will fail with a 403. Code that downloads external data must run on the droplet, not in the sandbox. Write the download logic, push it via the deploy pipeline, and let it execute on the server where there are no network restrictions.

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

**Environment:** `http://159.223.127.125` (or project-specific path). The sandbox cannot reach the droplet — all live-site verification runs on GitHub Actions infrastructure.

### How QA Runs

1. Builder adds task-specific Playwright tests to `tests/qa-smoke.spec.ts` as part of the build
2. Orchestrator pushes to `main` → webhook deploys in 2-3s → GitHub Actions triggers `.github/workflows/qa.yml`
3. GitHub Actions installs Playwright + Chromium, waits 15s for deploy, runs all tests at 390px mobile and 1280px desktop
4. Screenshots uploaded as artifacts (7-day retention)
5. Orchestrator checks the Actions run for the push commit to read pass/fail results. **Note:** WebFetch returns cached/stale GitHub Actions data — do not trust it for QA results. Wait at least 90 seconds after push, check once with a cache-busting query parameter, and cross-reference with the user's report of email notifications if uncertain.

### Writing Task-Specific Tests

Every feature must have Playwright tests that act like an end user:

- **Interactive elements:** Click buttons, fill forms, select options — verify the response
- **Data display:** Check for real values — no NaN, no blanks, no placeholder text
- **Navigation:** Follow links, verify destinations load
- **Error states:** Test invalid input if applicable
- **Mobile:** All tests run at 390px — layouts must be usable

Tests go in `tests/qa-smoke.spec.ts` in a new `test.describe` block named after the feature. Example pattern:

```typescript
test.describe('Feature Name', () => {
  test('user can do the thing', async ({ page }) => {
    await page.goto('/feature-path/');
    await page.locator('#action-button').click();
    const result = await page.locator('#result').textContent();
    expect(result).toBeTruthy();
    // Verify actual values, not just presence
  });
});
```

### Closed-Loop Iteration

```
Deploy → GitHub Actions QA → PASS → done
                           → FAIL → Orchestrator reads failures
                                  → Orchestrator writes QA failure brief
                                  → Builder fixes with full context
                                  → Redeploy → GitHub Actions re-runs
                                  → Repeat until passing or stuck
                                  → If stuck: rollback + escalate to user
```

**Escalate when stuck, not on a counter.** No hard limit on fix cycles. The Orchestrator escalates when the same failure repeats, when fixes aren't making progress, or when the root cause is unclear. When escalating: rollback first, then report with evidence.

**QA failure brief — the Orchestrator sends this to the Builder on every failure:**
- **Which tests failed** — exact test names
- **Full error messages** — the assertion or runtime error verbatim, not summarized
- **Expected vs actual** — what the test wanted vs what it got
- **Screenshots** — from the Actions artifacts showing what the user would see
- **Console errors** — any JS errors captured
- **What changed** — which files were modified in the failing deploy
- **Suggested investigation** — Orchestrator's best guess at the root cause

The brief must be detailed enough that the Builder can diagnose without re-reading the entire codebase. Poor feedback = wasted fix cycles.

### Regression Testing

After every deploy, the full test suite runs — not just new tests. This covers:
- All existing project routes (landing page, games hub, each game)
- Security checks (.env, dotfiles, .md files return 404)
- Performance (pages load under 8s)
- Webhook health endpoint

### QA Report

The GitHub Actions run serves as the QA report. The Orchestrator summarizes results in `TASK_STATE.md`:

```
## QA Result
Run: [GitHub Actions run URL or number]
Verdict: PASS / FAIL
Tests: [X passed, Y failed]
Failed tests: [list if any]
Fix cycles used: [0-2]
```

### Auto-FAIL Criteria

- Unhandled JS error on any page
- Blank/NaN data fields
- Broken mobile layout at 390px
- Page load over 8 seconds
- Any regression in existing features
- Webhook health check failure

-----

## Git Workflow

- Commit and push all changes before stopping.
- Descriptive commit messages — explain why, not just what.
- Never force-push or amend published commits without permission.
- No PRs unless asked.
- Tag before every deploy.
- Static deploys push to `main` only.
- **Merge conflicts:** If `git push` fails because another chat pushed first, run `git pull --rebase origin main` to rebase on top, then push again. Never force-push to resolve conflicts. If the rebase has conflicts, resolve them manually — don't discard the other chat's work.

-----

## Deployment System

**Instant deploy via webhook:** Push to `main` → GitHub webhook → `http://159.223.127.125/webhook/deploy` → nginx proxies to Python listener on `127.0.0.1:9000` → verifies HMAC-SHA256 signature → triggers deploy script → deploys in 2-3 seconds. Fallback timer runs every 5 minutes in case webhook fails.

**Auto-deploy pipeline:** `main` branch → `/opt/site-deploy/` → syncs `games/` → `/var/www/games/`, copies `deploy/landing.html` → `/var/www/landing/index.html`, reloads nginx if `deploy/NGINX_VERSION` changed. Log at `/var/log/general-deploy.log`.

**Deploy script ordering — fast path first:** The deploy script must sync static files (landing page, games, hubs) BEFORE any heavy one-time setup (apt-get, npm install, Playwright install). The fast path must complete in 2-3 seconds regardless of pending setup work. Never block static deploys behind project-specific initialization.

**Deploy script self-update is two-deploy:** When you fix the deploy script itself, the fix doesn't take effect on the current run — the old script is already in memory. Push the fix, then push a second trivial commit to trigger a deploy that runs the new script. Pattern: fix → deploy (copies new script) → trigger commit → deploy (runs new script).

**Automated QA:** Every push to `main` triggers a GitHub Actions workflow (`.github/workflows/qa.yml`) that runs Playwright tests against the live site at 390px mobile and 1280px desktop. Tests cover: page loads, link integrity, JS errors, security (dotfile/env blocking), performance (<8s load), and webhook health. Results visible in the GitHub Actions tab. Screenshots uploaded as artifacts.

**Project isolation:** Own directory, nginx route, deploy script. Never write outside project directory. One deploy never breaks another.

**New project setup:**

1. Clarify location before writing code
1. Create `/opt/<project>/` (or `games/<name>/` for static games)
1. Add nginx location block in `deploy/update_nginx.sh`
1. Bump `NGINX_VERSION`
1. Add link card to every relevant hub page:
   - `deploy/landing.html` — always (this is the user's home screen)
   - `games/index.html` — if it's a game
   - Any parent sub-folder hub page — if the project lives inside a group (e.g. a `/carvana/` hub)
1. If a new sub-folder group is created (e.g. `/carvana/`), create a hub `index.html` for it with cards linking to each project in the group, and add a card on the main landing page pointing to the hub
1. Configure error logging and health check
1. Add to `RUNBOOK.md`

**Every project must be reachable by tapping links from the landing page.** No project should exist without a link card. If a user can't navigate to it from http://159.223.127.125/, it's not done.

**Static deploys:** `games/<n>/index.html` on `main` → live at `http://159.223.127.125/games/<n>/` within 30s.

**Moving a project:**

When the user wants to reorganize — e.g. move a project into a sub-folder or rename its URL path.

Step 1 — Confirm with the user. Present the before and after:

```
MOVE: [project name]
From: [current URL and paths]
To:   [new URL and paths]

What will change:
- URL: /old-path/ → /new-path/
- Server directory: /opt/old/ → /opt/new/
- nginx route updated
- All link cards updated (landing page, hub pages)
- RUNBOOK.md updated

Confirm? (yes/no)
```

Step 2 — Execute the move:

1. Update nginx: remove old location block, add new one in `deploy/update_nginx.sh`. Add a temporary redirect from the old URL to the new URL so bookmarks don't break:
   ```
   location = /old-path { return 301 /new-path/; }
   location = /old-path/ { return 301 /new-path/; }
   ```
1. Bump `NGINX_VERSION`
1. For static games: move the `games/<old>/` directory to the new location in the repo — `rsync --delete` handles the rest
1. For `/opt/` projects: add a one-time move block to `deploy/auto_deploy_general.sh` gated by a flag file:
   - `mv /opt/<old>/ /opt/<new>/`
   - `mv /var/log/<old>/ /var/log/<new>/`
   - Update logrotate config paths in `/etc/logrotate.d/`
   - Update uptime cron URL
   - Flag file: `touch /opt/.moved-<project>`
1. If creating a new sub-folder group: create a hub `index.html` with cards for all projects in the group
1. Update all link cards on every hub page — landing page, old hub (if any), new hub
1. Update `RUNBOOK.md` with new paths and URLs
1. Push to `main`

Step 3 — Verify after auto-deploy runs:

1. Confirm the new URL returns 200
1. Confirm the old URL redirects to the new one
1. Confirm all hub pages show correct links
1. Report to the user

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
- Link cards: landing page, games hub, any other page linking to it
- Uptime cron job
- Logrotate config
- RUNBOOK.md entry

Confirm? (yes/no)
```

Do NOT proceed until the user says yes. Wait for an explicit answer.

Step 2 — Remove everything (no orphans):

1. Remove all link cards pointing to the project:
   - `deploy/landing.html` — main landing page card
   - `games/index.html` — game hub card (if it's a game)
   - Any other index or hub page that links to it
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

Step 3 — Clean up empty hubs:

After deleting a project, check if its parent hub is now empty (no remaining project cards). If so:

1. Present this to the user:
   ```
   The [hub name] hub at /[path]/ is now empty.
   Remove the empty hub and its landing page card? (yes/no)
   ```
1. Do NOT auto-delete the empty hub — wait for the user to say yes
1. If confirmed: remove the hub `index.html`, its nginx route, and its card from the parent landing page
1. If not confirmed: leave it in place (user may plan to add new projects there)

Step 4 — Verify after auto-deploy runs:

1. Confirm the project URL returns 404
1. Confirm the landing page no longer links to it
1. If a hub was removed: confirm that URL also returns 404
1. Report to the user that deletion is complete

-----

## Link Audit

Links can drift from reality over time. The Orchestrator runs a link audit at the start of every task (before writing any spec) and after every deploy.

**Audit procedure:**

1. Scan all hub pages for link cards: `deploy/landing.html`, `games/index.html`, and any other `index.html` files that serve as hubs
1. For each link card, verify the target exists:
   - Static games: check that the `games/<name>/` directory exists in the repo with an `index.html`
   - `/opt/` projects: check that the nginx location block exists in `deploy/update_nginx.sh`
1. Check the reverse — scan for projects that exist but have no link card:
   - `games/*/index.html` files with no card on `games/index.html`
   - nginx location blocks with no card on any hub page
1. Check for empty hubs — hub pages with zero project cards

**If drift is found:**

- Report it to the user before starting the current task:
  ```
  LINK AUDIT: [issues found]
  - Dead link: [hub page] → [target] (target missing)
  - Unlinked project: [project] has no card on [hub page]
  - Empty hub: [hub page] has no project cards
  Fix these before proceeding? (y/n)
  ```
- If the user says yes, fix them as a prerequisite before the main task
- If no, note the drift in `TASK_STATE.md` blockers and proceed
