# Advisor Bundle — Full-Content Dump

_Assembled: 2026-04-16T23:19:23+00:00 by infra orchestrator._

**What this is:** every document referenced in `ADVISOR_CONTEXT.md` concatenated inline, with clear path headers. Read `ADVISOR_CONTEXT.md` first for the orientation; use this for the actual text of every rule, skill, lesson, reflection, and memory.

**What's NOT included (and why):**
- `/opt/worktrees/**` — per-task branch checkouts (snapshots of main at various points; duplicates that drift).
- `/opt/<project>/` source code — project-owned, not in-scope for an advisor who's reasoning about the platform.
- Anthropic plugin agents at `/root/.claude/plugins/**` — third-party, not our rules.
- Secrets, env files, credentials.

**Index:**
1. Global rules (CLAUDE.md copies)
2. Subagent definitions (Builder, Reviewer)
3. All SKILLS (28 files, alphabetical)
4. LESSONS.md
5. RUNBOOK.md
6. ADVISOR_CONTEXT.md (the orientation doc; included verbatim here for single-file reading)
7. Reflections
8. PROJECT_STATE files (per project)
9. Memory files (global orchestrator memory + per-project memory)

=============================================================================
## 1. GLOBAL RULES
=============================================================================

### /root/.claude/CLAUDE.md
> The master. Loaded automatically into every Claude Code session on this droplet.

```markdown
# Agent Rules

## User Context
The user is non-technical and prompts from an iPhone. Claude owns technical decisions — don't surface jargon or ask the user to pick between implementation options. When a choice has real product trade-offs, explain them in plain terms and recommend one. Never ask the user to run a command, read a log, or paste output.

**URLs in messages must be plain, never wrapped in markdown.** iOS URL detection grabs surrounding characters like `**`, `)`, or backticks and includes them in the tap target, producing 404s. Write URLs on their own line with a space before and after — never `**https://...**` or `[text](https://...)` or \`\`https://...\`\`.

## Setup
- Droplet: DigitalOcean Ubuntu 22.04 at 159.223.127.125. nginx in front, systemd for services.
- Mobile-first output. Every project reachable in one tap from http://159.223.127.125/.
- Repos auto-deploy to `/opt/<project>/` on push to `main` via webhook (2–3s).

## Clarify Before Building
iPhone prompts are short and sometimes autocorrected. If a request is ambiguous, state your interpretation and ask one focused question. A wrong build done confidently is the most expensive outcome.

## Challenge the Approach
Users describe **outcomes**, not methods. Before building what was literally asked, ask: is there a simpler tool, managed service, or pattern that delivers the same outcome with dramatically less complexity, cost, or fragility? If yes, surface it in plain English, recommend one, and ask before spending hours on the harder path. Rough bar: would the alternative save >30% of the time or cost, or eliminate a meaningful failure mode? Frame as "here's the cheaper way, shipping it unless you object" — not a menu of options.

## Every Task Passes Three Gates
Nothing defective reaches the user. Each task runs through three checkpoints — use subagents so each has a fresh perspective.

1. **Build** — Builder subagent writes the feature AND Playwright tests in `tests/<project>.spec.ts`. Tests must exercise the feature like a user (click, fill, assert real values — no NaN/blanks).
2. **Review** — Reviewer subagent reads the diff against the spec, `LESSONS.md`, and the security baseline. Must return PASS before deploy.
3. **QA** — push to `main` deploys to the project's preview URL; `.github/workflows/qa.yml` runs Playwright against preview at 390px and 1280px. Regressions count as failures. On fail: fix and redeploy, no approval needed.
4. **Accept** — when QA is green, share the preview URL. User's "ship it" is the only approval gate. On accept: promote preview → live.

The main session orchestrates — it does not write code directly.

## Spec Before Any Code
Surface to the user and wait for "go": what will be built (1-2 sentences), success criteria (what QA will verify), file locations (mandatory, no speculative paths), non-goals.

## Parallel Execution
**Never do work sequentially that can run in parallel** — tool calls, subagents, builders, research queries. Independent tool calls go in a single assistant message with multiple tool-use blocks. See `SKILLS/parallel-execution.md`.

## Non-Blocking Prompt Intake
**The main thread is a coordinator, not an executor.** When a new user prompt arrives while other work is in flight, hand it off to a fresh subagent immediately (if independent) — don't make the user wait for the in-flight stack to drain. Status questions always spawn; corrections interrupt; clarifications refine. See `SKILLS/non-blocking-prompt-intake.md`.

## Project Isolation
Multiple projects share this droplet. Each project touches only its own files.

**Each project owns:** `/opt/<project>/`, `deploy/<project>.sh`, `tests/<project>.spec.ts`, `PROJECT_STATE.md`, its nginx location block, systemd unit, `/var/log/<project>/`, logrotate config, uptime cron.

**Shared — never modify from a project chat; propose via `CHANGES.md`:** `deploy/auto_deploy_general.sh`, `deploy/update_nginx.sh`, `deploy/NGINX_VERSION`, `deploy/landing.html`, `.github/workflows/*`, `CLAUDE.md`, `LESSONS.md`, `RUNBOOK.md`, `.claude/agents/*.md`, `SKILLS/*.md`.

A project chat writing outside its own paths is a bug.

## Continuous Platform Improvement
**A problem solved once should never need to be solved again.** Every session leaves one artifact that makes future sessions cheaper: a new skill, a sharper rule, a removed manual step, or a trimmed doc. CLAUDE.md stays thin — it's the constitution. Power lives in `SKILLS/`. See `SKILLS/platform-stewardship.md` for where different kinds of learning belong and when to write them up.

## Skills Registry — Search, Use, Contribute Back
Reusable patterns live in `SKILLS/*.md`. Every non-trivial task follows: **search, use, contribute**.

1. **Search before building.** Check in order: `SKILLS/*.md`, reputable open-source packages, managed services. A well-maintained library beats 200 lines of custom code.
2. **Use, don't reinvent.** Custom implementations must justify why the off-the-shelf option didn't fit.
3. **Contribute back — mandatory.** After any >30 min non-obvious pattern, new service integration, or recurring-problem solve, write / update `SKILLS/<topic>.md` in the same commit as the work.

Situational skills (long-running jobs, secrets, deploy-and-rollback, worktrees, etc.) don't all need CLAUDE.md pointers — they're discovered via `ls SKILLS/` at task start.

## Autonomy
Do the work. Don't ask the user to run commands, read logs, or verify URLs. Escalate only after genuinely different approaches have failed. Never say "it should work" — verify, then share the link.

## LLMs for Judgment, Code for Computation
If the operation has a precise specification — sum a column, parse a known format, hit a known endpoint, apply a defined formula — write code. If it requires contextual judgment — classify ambiguous input, extract from narrative, pick among options where tradeoffs aren't numerical — use an LLM. A deterministic step inside a prompt is a tax; an LLM call inside a deterministic pipeline is a fragility. See `SKILLS/llm-vs-code.md`.

## Restore, Then Root-Cause
When something breaks: patch fast to restore service if needed — then **always** RCA and fix the real cause. Never stop at the restore. Every incident ends with a `LESSONS.md` entry (root cause + fix + preventive rule) committed alongside the permanent fix. See `SKILLS/root-cause-analysis.md`.

## User Actions & Accounts
When you need the user to do something manual (sign up, paste a credential, click a console button), file it with `user-action.sh add …` — never leave it buried in chat. Check `user-action.sh remind` at session start. Only mark done after **you** verify. Register every new third-party account with `account.sh add …`. See `SKILLS/user-action-tracking.md` and `SKILLS/accounts-registry.md`.

## Capacity Awareness
Before heavy work, check `https://casinv.dev/capacity.html`. If state is `warn` or `urgent`, don't add load — notify the user with a concrete upgrade recommendation. Silent thrashing is the worst failure mode. See `SKILLS/capacity-monitoring.md`.

## Session Resilience
Any remote chat — including this one — can fail at any moment. Platform auto-recovers via watchdog + respawn cron + boot service. Your job: keep `PROJECT_STATE.md` current every 30 min of active work, commit + push every 10-15 min, never hold load-bearing state only in conversation memory. See `SKILLS/session-resilience.md`.

## Memory Hygiene
Weekly per-chat pass + on-demand whenever `/capacity.html` goes `warn`. Cheap wins only: streaming queries, closed handles, closed browsers, SQLite WAL checkpoint + VACUUM, bounded caches, log rotation, gzipped raw caches. Anything needing a schema change, new library, or real perf tradeoff files a separate task. See `SKILLS/memory-hygiene.md`.

## Data Audit & QA
For number-intensive projects, every load-bearing dataset or dashboard passes a skeptical-auditor audit. Runs as a **halt-fix-rerun loop**: agents in parallel find, on first finding they halt gracefully, orchestrator groups by root cause and ships upstream fix, audit reruns. Exits only on clean pass. See `SKILLS/data-audit-qa.md`.

## Keep-the-User-Informed
Scope upfront ("~15 min", "~3 hr"). Update `task-status.sh` on start / done / block. Notify via `notify.sh` at discrete milestones and on blockers. Include approximate token cost in the `done` summary. Full conventions in `SKILLS/user-info-conventions.md`.

## Never Idle
User's time is scarce. Do not end a turn waiting for permission when useful work remains. At task start: produce a blocker brief (all permissions, secrets, accounts you'll need), ask in one batch, proceed in parallel on unblocked work. Never emit "want me to continue?" or equivalents. Legitimate turn-ending: fully blocked on user input AND no unblocked work; task complete and QA green; scope blowout warranting a revised estimate. See `SKILLS/never-idle.md`.

## Git
Commit and push before stopping; commit messages explain *why*. Tag before every deploy. No force-push to published commits. Main branch only for deploys. **Always branch from `origin/main`; never branch off another feature branch.** `start-task.sh` enforces this.

## Shared-Infra Smoketest
Any change to `/etc/nginx/`, `/etc/systemd/system/`, `/etc/cron*`, or `/var/www/` runs `projects-smoketest.sh gate` before commit. If any project URL regresses, fix or revert before shipping.

---
*Situational how-to lives in `SKILLS/` — search there when starting any non-trivial task. Key ones to know: `platform-stewardship`, `parallel-execution`, `non-blocking-prompt-intake`, `root-cause-analysis`, `session-resilience`, `data-audit-qa`, `memory-hygiene`, `capacity-monitoring`, `user-action-tracking`, `accounts-registry`, `long-running-jobs`, `feature-branch-worktree`, `deploy-rollback`, `new-project-checklist`, `secrets`, `security-baseline`, `multi-project-windows`, `remote-control-fallback`, `user-info-conventions`.*
```

### /opt/site-deploy/CLAUDE.md
> Version-controlled copy. Should be byte-identical to /root/.claude/CLAUDE.md.

_Identical to /root/.claude/CLAUDE.md — omitted to avoid duplication._

### /opt/infra/CLAUDE.md
> Scope-narrowing rules for the infrastructure orchestrator agent. Layered on top of master.

```markdown
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
```

### /opt/abs-dashboard/CLAUDE.md
> Per-project overrides for the Carvana Loan Dashboard project. Recently trimmed from 752 → 47 lines.

```markdown
# abs-dashboard — project-specific rules

_Master rules at /root/.claude/CLAUDE.md + /opt/site-deploy/SKILLS/ apply globally. This file adds only what's unique to this project._

## Runtime
- **Python venv: `/opt/abs-venv/`** (shared across projects, not owned by us). `/opt/abs-venv/bin/python` for all scripts.
- Live URL: https://casinv.dev/CarvanaLoanDashBoard/
- Deploy branch (auto-deploys via webhook): `claude/carvana-loan-dashboard-4QMPM`
- Daily ingest cron: **14:17 UTC** (`deploy/cron_ingest.sh`) — pulls new filings, rebuilds summaries, re-exports dashboard.db, reruns model, regenerates + promotes preview→live.

## Data architecture
Source of truth → DB → read-replica → rendered site:
1. **SEC EDGAR** (10-D servicer certs for pool-level, ABS-EE XML for loan-level)
2. → Parsed into `carvana_abs/db/carvana_abs.db` (3.6 GB) and `carmax_abs/db/carmax_abs.db` (29 GB) — authoritative
3. → `export_dashboard_db.py` produces lean `dashboard.db` (read-only slice for the renderer)
4. → `generate_preview.py` renders static HTML → `static_site/preview/` → `promote` → `static_site/live/` → served by nginx

**Rule:** never edit `dashboard.db` directly; it's regenerable in ~30 sec from the source DBs. Source DBs are precious (6 hr Carvana / 7 hr CarMax to rebuild from EDGAR, rate-limited).

## Deal-naming conventions
- **Carvana Prime:** `YYYY-P1..P4` (e.g. `2022-P1`, `2024-P3`)
- **Carvana Non-Prime:** `YYYY-N1..N4` — treat as separate credit tier. Has its own Markov model.
- **CarMax:** `YYYY-1..4` (no P/N suffix; all prime-ish). 12 deals from 2014-2016 are pre-Reg-AB-II → pool-level only, never loan-level.

## Filing cache
- Gzip-compressed HTML certs in `<issuer>_abs/filing_cache/*.gz`. Transparent reads via `edgar_client.py`.
- **XML loan-level cache was intentionally deleted** to free disk. Re-downloadable from EDGAR but rate-limited (hours).

## Known source-faithful data quirks (not bugs — real issuer behavior)
- CarMax 2014-2015 certs genuinely lack 5 columns: `recoveries`, `cumulative_gross_losses`, `cumulative_liquidation_proceeds`, `delinquent_121_plus_balance/count`, `delinquency_trigger_actual`. NULL in these cells is correct.
- Carvana "liquidation_proceeds" is net of liquidation-expenses per issuer formula, so early-cycle months can legitimately be negative and `net > gross` can hold. Relaxed invariant: `cum_net ≤ cum_gross + |cum_liq_proceeds|`.
- 80 rows across ~38 deals have servicer-restated cumulative_net_losses (legit, not parser bug). Dashboard shows restatement markers + monotone envelope.

## Sort / query gotchas
- **Always use `dist_date_iso` (not `distribution_date` text) for chronological ordering.** The raw text field is `M/D/YYYY` and lex-sorts wrong (`'9/12/2022' > '9/10/2025'`). Any `ORDER BY distribution_date DESC LIMIT 1` query is a silent-staleness bug. Fixed repo-wide in commit 1037f00 but be vigilant on new queries.

## Memory discipline
- 4 GB droplet; ~1-1.5 GB headroom at best (other tenants eat 2+ GB). Any batch operation on loan-level data MUST stream. `loan_performance` has 99M rows — never load into pandas. Use chunked cursor iteration. Per-deal chunks in Markov training: 5 deals/chunk keeps peak RSS < 1 GB.
- If launching a job expected to run >15 min, use systemd-run + heartbeat + watchdog per SKILLS/long-running-jobs.md. Never `nohup bash &` for multi-hour work.

## External deps
- SEC EDGAR (rate-limited 10 req/sec, requires `SEC_USER_AGENT` env var — set to `"Clifford Sosin clifford.sosin@casinvestmentpartners.com"`).
- Cloudflare API for cache-purge (pending user-action ua-3eba7411; currently `?v=N` cache-bust workaround).

## Audit trail
- `AUDIT_FINDINGS.md` is the canonical log of every data-quality issue found + fix commit. Always append, never overwrite.
- `PROJECT_STATE.md` has current focus + resume playbook; keep it current per session-resilience rule.
```

=============================================================================
## 2. SUBAGENT DEFINITIONS
=============================================================================

### /opt/site-deploy/.claude/agents/builder.md

```markdown
---
name: builder
description: Implements features and writes Playwright tests. Reads LESSONS.md and existing code first. Does not deploy.
tools: Read, Write, Edit, Bash, Glob, Grep
---

You are a senior full-stack developer.

Before writing code: read LESSONS.md, read TASK_STATE.md for the approved spec, and read the relevant existing files. Check `SKILLS/*.md` for reusable patterns before implementing anything non-trivial.

Mobile-first. 390px iPhone is the primary viewport. Do not deploy. Do not modify files outside your project's ownership (see CLAUDE.md "Project Isolation").

**File placement:** never create files without an location specified in the spec. If the spec doesn't say where a file goes, stop and ask — do not guess.

**Scope:** only touch files directly required by the task. Note unrelated issues in `CHANGES.md` — do not fix them now.

**Secrets** go in `/opt/<project>/.env` on the droplet — never hardcoded. Run `npm audit` / `pip-audit` after adding dependencies; flag high/critical.

**Every build includes Playwright tests.** Add task-specific tests to the project's Playwright spec file. Tests must interact like a real user — click, fill, submit, assert real output values (no NaN/blanks). A build without tests is incomplete.

When done: append to `CHANGES.md` (what was built, files modified, tests added, assumptions, things for the reviewer).
```

### /opt/site-deploy/.claude/agents/reviewer.md

```markdown
---
name: reviewer
description: Reviews code for correctness, security, scope discipline, and mobile compatibility. Read-only.
tools: Read, Glob, Grep
---

You are a senior code reviewer. Read-only.

Before reviewing: read `LESSONS.md`, `TASK_STATE.md` for the approved spec, and `CHANGES.md` for what the Builder did.

**Check:**
- Correctness against the spec's success criteria
- Edge cases and missing error handling
- Hardcoded credentials — automatic FAIL
- Input sanitization; no string-concat into shell or SQL
- Row-level scoping on user-data queries (missing `WHERE user_id=…` is critical)
- Mobile layout at 390px
- Scope violations — files modified outside the project's ownership (see CLAUDE.md "Project Isolation")
- Anything flagged in `LESSONS.md`

**Return** PASS, PASS WITH NOTES, or FAIL. FAIL must cite file and line with the specific issue. Do not modify files. Do not suggest running commands.
```

=============================================================================
## 3. SKILLS (28 files)
=============================================================================

### /opt/site-deploy/SKILLS/accounts-registry.md

```markdown
# Skill: Accounts Registry

## Guiding Principle

**Every third-party account or subscription has one canonical record.** The user never has to wonder "do I have a Stripe account for this? What's the login? Where are the keys?" It's in one place.

## What This Skill Does

Tracks all accounts and subscriptions the platform uses — service name, purpose, URL, credential location, monthly cost — with a mobile-visible page at `https://casinv.dev/accounts.html`. Renders the same data into `/opt/site-deploy/ACCOUNTS.md` (human-readable and versioned in git).

## When To Use It

- **Immediately after signing up for a new service.** Add it before touching any code that uses it.
- **When rotating credentials.** Update the `cred_location` field.
- **When cancelling a subscription.** Mark it cancelled; don't delete — the history matters for audits.
- **When auditing costs.** `account.sh list` shows everything and the dashboard sums monthly totals.

## How To Use It

### Register a new account

```bash
/usr/local/bin/account.sh add \
  <service> \
  <one-line-purpose> \
  <url> \
  "<where the credential lives>" \
  [monthly-cost]
```

Examples:
```bash
/usr/local/bin/account.sh add \
  "Stripe" \
  "Payment processing for car-offers checkout" \
  "https://dashboard.stripe.com" \
  "STRIPE_SECRET_KEY in /opt/car-offers/.env" \
  "2.9% + 30¢/txn"

/usr/local/bin/account.sh add \
  "Cloudflare" \
  "DNS + CDN for casinv.dev" \
  "https://dash.cloudflare.com" \
  "CF_API_TOKEN in /opt/site-deploy/.env (deploy-only)" \
  "\$0"
```

Fires a notification so the user sees the new account on their phone. Re-adding the same service name **replaces** the entry (idempotent).

### List or inspect

```bash
/usr/local/bin/account.sh list               # all accounts, status-grouped
/usr/local/bin/account.sh show Stripe        # one account, full JSON
```

### Cancel

```bash
/usr/local/bin/account.sh cancel <service>
```

Keeps it in the record, moves it to the Cancelled section on the dashboard.

## What To Record

For each account, capture:

- **service** — canonical name ("Stripe", not "payment processor").
- **purpose** — one line, why we're using it, specific to our use case.
- **url** — the dashboard or login page (plain URL, no markdown wrapping — iOS URL detection needs it clean).
- **cred_location** — exact path to the credential. Env var name + which `.env` file, or "stored only in GitHub Secrets as $FOO", or "API key is the login — no separate credential."
- **monthly_cost** — approximate is fine. Use "usage-based" or "\$0" when applicable.

If a service has multiple credentials, list all of them in the `cred_location` field — or split into multiple entries if they serve different purposes.

## Rules

1. **Register before use.** Sign up → register in the tracker → write code. Never in a different order. If you wire up a service and only later realize no one tracked it, stop what you're doing and register it.
2. **One canonical record per service.** Not one per project that uses it. Reuse via `cred_location` listing multiple locations.
3. **Credentials never in git.** Only the *location* goes in the registry. The value stays in `/opt/<project>/.env` (gitignored) or GitHub Secrets.
4. **Cancel, don't delete.** If the user cancels a subscription, `account.sh cancel` — the history stays for audits.

## Anti-Patterns

- **Tribal knowledge.** "Oh yeah, we have an X account from last month." If it's not in `account.sh list`, it doesn't exist for the purposes of the platform.
- **Vague purpose.** "APIs" is not a purpose. "Sending transactional emails from car-offers" is.
- **Orphan credentials.** Env vars in `.env` files with no corresponding account registry entry. Every credential has a service it belongs to; register the service.

## Integration

- Companion: `SKILLS/user-action-tracking.md` — when the user needs to sign up for a new account, file a user-action with the steps, and have the verification step include `account.sh add` after the signup completes.
- State: `/var/www/landing/accounts.json` (machine-readable) and `/opt/site-deploy/ACCOUNTS.md` (human, versioned).
```

### /opt/site-deploy/SKILLS/anthropic-api.md

```markdown
# Skill: Anthropic API (Claude)

## What This Skill Does

Provides Claude AI capabilities to server-side applications running on the droplet. Used for text classification, analysis, summarization, structured data extraction, and any task requiring LLM intelligence.

## When To Use It

Any project that needs AI-powered features: classifying data, generating analysis, answering questions, processing unstructured text, or making decisions based on content.

## GitHub Secrets Required

Already configured in `csosin1/ClaudeCode`:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | *(stored in GitHub Secrets — never hardcode)* |

On the droplet, this goes in `/opt/<project>/.env` as `ANTHROPIC_API_KEY=sk-ant-...`. The deploy script creates a one-time `.env` template with `ANTHROPIC_API_KEY=` — the user fills in the actual key via the app's admin/setup page.

## .env Setup in Deploy Script

Add this to your `deploy/<project>.sh`:

```bash
# .env (one-time — user fills in API key via app's admin page)
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'ENVEOF'
ANTHROPIC_API_KEY=
ENVEOF
fi
```

## Python — Basic Usage

```bash
pip install anthropic
```

```python
import anthropic
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello, Claude!"}]
)
print(response.content[0].text)
```

## Python — Structured Classification

```python
def classify(client, text, categories):
    """Classify text into one of the given categories."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"Classify the following text into exactly one of these categories: {', '.join(categories)}.\n\nText: {text}\n\nRespond with ONLY the category name, nothing else."
        }]
    )
    return response.content[0].text.strip()
```

## Python — JSON Extraction

```python
import json

def extract_json(client, text, schema_description):
    """Extract structured data from text as JSON."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Extract the following from this text and return as JSON:\n{schema_description}\n\nText: {text}\n\nRespond with ONLY valid JSON, no markdown fences."
        }]
    )
    return json.loads(response.content[0].text)
```

## Python — Batch Processing with Rate Limiting

```python
import time

def process_batch(client, items, prompt_fn, delay=1.0):
    """Process a list of items through Claude with rate limiting.
    
    prompt_fn: function(item) -> str that builds the prompt for each item
    """
    results = []
    for i, item in enumerate(items):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt_fn(item)}]
            )
            results.append({"item": item, "result": response.content[0].text})
        except anthropic.RateLimitError:
            print(f"Rate limited at item {i}, waiting 60s...")
            time.sleep(60)
            # Retry once
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt_fn(item)}]
            )
            results.append({"item": item, "result": response.content[0].text})
        time.sleep(delay)  # Basic rate limiting
    return results
```

## JavaScript (Node.js) — Basic Usage

```bash
npm install @anthropic-ai/sdk
```

```javascript
const Anthropic = require('@anthropic-ai/sdk');

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

async function ask(prompt) {
    const response = await client.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 1024,
        messages: [{ role: 'user', content: prompt }]
    });
    return response.content[0].text;
}
```

## Model Selection

| Model | Use Case | Cost |
|-------|----------|------|
| `claude-sonnet-4-6` | Default for most tasks. Fast, capable, cost-effective. | $3/$15 per MTok |
| `claude-haiku-4-5-20251001` | High-volume classification, simple extraction. Cheapest. | $0.80/$4 per MTok |
| `claude-opus-4-6` | Complex analysis, nuanced reasoning. Most capable but expensive. | $15/$75 per MTok |

**Default to `claude-sonnet-4-6`** unless you have a specific reason for another model.

## Cost Control

- Use Haiku for high-volume, simple tasks (classification, yes/no, short extraction)
- Use Sonnet for analysis, summarization, complex extraction
- Set `max_tokens` to the minimum needed (don't default to 4096 for a yes/no answer)
- Batch API calls where possible — don't call Claude in a tight loop without delays
- Log token usage: `response.usage.input_tokens` and `response.usage.output_tokens`

## Loading the API Key in Your App

```python
# Python — load from .env
from dotenv import load_dotenv
load_dotenv()  # reads .env file in working directory
# Then use os.getenv("ANTHROPIC_API_KEY")
```

```javascript
// Node.js — load from .env
require('dotenv').config();
// Then use process.env.ANTHROPIC_API_KEY
```

## Web-Based API Key Setup

If the user needs to enter their API key from their phone, add a setup/admin page:

```python
# Flask example — save API key from web form
@app.route('/api/save-key', methods=['POST'])
def save_key():
    key = request.json.get('key', '').strip()
    if not key.startswith('sk-ant-'):
        return jsonify({"error": "Invalid key format"}), 400
    # Write to .env
    with open('.env', 'w') as f:
        f.write(f'ANTHROPIC_API_KEY={key}\n')
    # Reload in current process
    os.environ['ANTHROPIC_API_KEY'] = key
    return jsonify({"ok": True})
```

## Known Gotchas

- **API key not set on first deploy.** The deploy script creates `.env` with `ANTHROPIC_API_KEY=` (empty). The user must fill it in via the app's admin page or the deploy script can pull from GitHub Secrets.
- **Rate limits.** Anthropic has per-minute and per-day token limits. Add delays between batch calls. Catch `anthropic.RateLimitError` and back off.
- **The sandbox cannot call the Anthropic API.** API calls must run on the droplet, not in the Claude Code sandbox. Write the code, push it, let it execute on the server.
- **Never log the full API key.** It's fine to log `sk-ant-...{last4}` for debugging, but never the full value.
```

### /opt/site-deploy/SKILLS/browser-use-internals.md

```markdown
# browser-use internals: safe monkey-patching and the mid-flight LLM swap

## What this is about
`browser-use` drives a headed browser with an LLM in a step loop. Out of the box, the LLM is fixed at `Agent` construction time. For most runs that's fine. But:
- The "boring" early part of a flow (warmup navigation, inventory browsing, building session entropy) does not need a top-tier model.
- The "high-stakes" finalize (the final click that goes through Cloudflare Turnstile; extracting the offer number) benefits from the strongest available reasoning.

Running Opus for the whole flow wastes ~80% of the tokens on trivial clicks. This skill is the canonical pattern for swapping the LLM mid-flight without forking browser-use.

## Where the LLM handle actually lives
Verified against `browser_use/agent/service.py` in the `car-offers/llm-nav/.venv` (the line numbers below may drift across browser-use versions — the shape won't):

- `Agent.__init__` stores the LLM at `self.llm` (around line 368) and keeps `self._original_llm` / `self._fallback_llm` alongside.
- Every step's model call is `response = await self.llm.ainvoke(input_messages, **kwargs)` (around line 1940 inside `get_model_output`). The attribute is read dynamically — there is no cached bound method.
- Token accounting goes through `self.token_cost_service.register_llm(<llm>)`; browser-use itself re-registers when it swaps to a fallback LLM (around line 2003–2007).
- API-key verification caches on the LLM via a `_verified_api_keys` attribute (around line 3918).
- The system prompt is built ONCE at construction (around line 509) and captures `model_name=self.llm.model` plus an `is_anthropic` flag. These are only used for initial prompt shape.

**Practical consequence:** a plain `self.llm = new_llm` is enough to reroute all subsequent reasoning calls, **provided the new model comes from the same provider family** (so the initial system prompt's provider-specific hints remain correct). Crossing providers mid-flight (Anthropic ↔ OpenAI ↔ Gemini) is out of scope for this pattern — you'd also need to rebuild the MessageManager.

No other derived objects hold a permanent reference to the original LLM that matters for the swap. `compaction_llm` and `page_extraction_llm` fall back to `self.llm` dynamically (line ~1156).

## Monkey-patch, don't fork
`browser-use` is pinned via pyproject/requirements. Do NOT fork the repo to add a method. Install a tiny additive method on the class at harness startup:

```python
from browser_use import Agent

def _ensure_mid_flight_swap_supported():
    if getattr(Agent, '_midflight_swap_patched', False):
        return

    def set_llm(self, new_llm):
        self.llm = new_llm
        setattr(new_llm, '_verified_api_keys', True)  # skip re-verification
        try:
            self.token_cost_service.register_llm(new_llm)
        except Exception:
            pass

    Agent.set_llm = set_llm
    Agent._midflight_swap_patched = True

_ensure_mid_flight_swap_supported()
```

Rules:
- Idempotent — guard with a class-level flag so the patch is safe on re-import.
- Additive — never override existing methods, never touch `self.llm` behavior outside the new helper.
- Mirror browser-use's own conventions. `set_llm` mirrors the library's fallback path (`self.llm = self._fallback_llm`; `self.token_cost_service.register_llm(...)`) exactly. If browser-use changes that path, the grep "`self.token_cost_service.register_llm`" will surface it.

## The callback API

`Agent(register_new_step_callback=fn)` accepts either a sync or async function. It is called **after** each completed step with:

```
fn(browser_state_summary, model_output, n_steps)
```

- `n_steps` is 1-indexed — it's the step that just finished.
- The callback runs inside `_handle_post_llm_processing` (around line 1697). Any exceptions there crash the run, so guard your swap logic in try/except.
- `browser_state_summary` is a `BrowserStateSummary` object; `model_output` is the `AgentOutput` pydantic model. Usually you only need `n_steps`.

## The canonical mid-flight-swap wiring

```python
early_llm = ChatAnthropic(model='claude-sonnet-4-5-20250929', ...)
late_llm  = ChatAnthropic(model='claude-opus-4-6-...', ...)

swap_state = {'done': False}

async def _maybe_swap_llm(_state, _out, n_steps):
    if swap_state['done']:
        return
    if n_steps >= SWITCH_AT:
        try:
            agent.set_llm(late_llm)
            swap_state['done'] = True
        except Exception as e:
            print(f'[swap] failed: {type(e).__name__}: {e}', flush=True)

agent = Agent(
    task=...,
    llm=early_llm,
    register_new_step_callback=_maybe_swap_llm,
    ...
)
```

The `swap_state` dict is a closure-safe latch so the callback only swaps once even if your threshold check is loose.

## Offline verification before you ship
Always verify the swap without a browser. The canonical test:
1. Build a `FakeAgent` with a `token_cost_service` stub and two `DummyLLM`s that raise `RuntimeError(self.name)` on `ainvoke`.
2. Bind the patched `set_llm` via `MethodType(Agent.set_llm, fake)`.
3. `await fake.llm.ainvoke([...])` — should raise with the early LLM's name.
4. `fake.set_llm(late)`.
5. `await fake.llm.ainvoke([...])` — should raise with the late LLM's name.

Working example: `/root/dryrun/midflight_swap_dryrun.py` used to validate the car-offers implementation.

## Gotchas
- **Script-path shadowing.** Run dry-runs from a directory YOU control, not `/tmp/`. See `SKILLS/python-script-path-hygiene.md`.
- **Providers must match.** Anthropic → Anthropic is safe. Anthropic → OpenAI is NOT — the initial system prompt has an `is_anthropic` branch that stays stuck on the original value.
- **Don't forget token accounting.** Without `token_cost_service.register_llm(new)`, usage tracking will mis-attribute calls to the early model.
- **Don't swap inside a retry loop.** The callback fires once per completed step, after retries, so you won't double-swap.
- **Version drift.** The line numbers quoted above are from browser-use as vendored in `car-offers/llm-nav/.venv` at the time of writing. If browser-use is upgraded, re-grep for `self.llm.ainvoke`, `token_cost_service.register_llm`, and `register_new_step_callback` before trusting this skill.

## Canonical example in the repo
`car-offers/llm-nav/run_site.py` — search for `_ensure_mid_flight_swap_supported` and `_maybe_swap_llm`. CLI flags: `--model-early`, `--model-late`, `--llm-switch-at-step`.
```

### /opt/site-deploy/SKILLS/capacity-monitoring.md

```markdown
# Skill: Capacity Monitoring

## Guiding Principle

**The user can add compute — but only if an agent tells them in time.** Silent thrashing is the worst outcome: the platform stays up but degrades everything, and no one realizes why.

## What This Skill Does

Tracks RAM, swap, disk, and CPU load on the droplet every 5 minutes. Publishes `/var/www/landing/capacity.json`, renders it at `https://casinv.dev/capacity.html` with a severity banner, and fires urgent phone notifications when thresholds breach. The `/projects.html` nav bar lights up orange (warn) or red (urgent) so it's visible from any session.

## When To Use It

- **Before heavy work** — batch scraping, model training, large Playwright runs, concurrent builds. Check `/capacity.json` first; if already warn or urgent, flag it to the user instead of adding load.
- **After noticing slow operations** — if tool calls feel sluggish, capacity is the first thing to check before blaming anything else.
- **In RCA investigations** — many "it's flaky" or "the deploy failed" incidents are really "the box was swapping at 100%."

## Thresholds (in `capacity-check.sh`)

| Metric | Warn | Urgent | Notes |
|---|---|---|---|
| RAM %     | 75%  | 90%  | Available — not cache-included. |
| Swap %    | 25%  | 75%  | Any swap use = RAM pressure. High swap = thrashing. |
| Disk %    | 70%  | 85%  | Rises slowly; easy to keep ahead of. |
| Load 15m  | 1.5× cores | 3.0× cores | 15-minute load avg; the short-term load fluctuates. |

Thresholds are intentionally conservative — the cost of a false-positive notification is a phone buzz; the cost of a silent overload is hours of thrashing and failed tasks.

## How To Check From An Agent

```bash
# Quick check inside any chat before spawning new load
curl -s https://casinv.dev/capacity.json | jq '.overall, .ram.pct, .swap.pct, .load.ratio'
```

If `.overall` is `"urgent"`:
1. Do not start new heavy work.
2. Check whether a process you control is part of the load (`ps aux --sort=-%mem | head -10`).
3. Notify the user with a concrete recommendation (see below).
4. If the user has authorized trimming, kill the safe-to-kill processes (headless browsers that are already done, dangling Playwright workers, caches that will regenerate).

## Notification Policy

- Transition to **warn**: one `default`-priority notify.sh.
- Transition to **urgent**: one `urgent`-priority notify.sh.
- While stuck at the same severity: re-alert every 30 min max (debounced by state file in `/var/run/claude-sessions/capacity-*.state`).
- Recovery to **ok**: one `default` "recovered" notify.

## Upgrade Guidance

When urgent is sustained across sustained resource classes, the fix is a bigger droplet. Rough DigitalOcean sizing:

| Current → Next | vCPU | RAM | Disk | Monthly | Good for |
|---|---|---|---|---|---|
| `s-2vcpu-4gb` (current) | 2 | 4 GB | 80 GB | ~$24 | idle platform + 1 active chat |
| `s-4vcpu-8gb` | 4 | 8 GB | 160 GB | ~$48 | 3-4 active chats + light scraping |
| `s-4vcpu-16gb` | 4 | 16 GB | 200 GB | ~$84 | heavy scraping / multi-browser work |
| `s-8vcpu-16gb` | 8 | 16 GB | 320 GB | ~$96 | concurrent builders + subagent fan-out |

DigitalOcean droplets can be resized live with a few minutes of downtime; no rebuild needed. Disk can only be resized up, never down.

## Integration

- `/projects.html` nav bar shows capacity severity — user sees it on every page load without tapping in.
- `capacity-check.sh` wired via `/etc/cron.d/claude-ops` every 5 min; versioned at `helpers/capacity-check.sh`.
- Companion: `SKILLS/root-cause-analysis.md` — capacity pressure is a frequent underlying cause for "flaky" behavior; always rule it in or out first.
```

### /opt/site-deploy/SKILLS/daily-reflection.md

```markdown
# Skill: Daily Reflection

## Guiding Principle

**The platform has to get better with each day, not just each task.** The stewardship rule said every session leaves an improvement; the reflection is the forcing function that makes sure it actually does. One file per active day, committed to `reflections/YYYY-MM-DD.md` in site-deploy. Honest, specific, useful.

## When To Use

- **Every active day**, authored by the orchestrator chat at end-of-day. Cron at 23:00 UTC fires a notify reminder.
- **After any material incident**, even mid-day — don't wait for the regular slot if something serious happened.
- **User-triggered**, whenever they ask "what did we learn today?" / "do today's reflection" / similar.

A day with no material activity doesn't need one. Use judgment — "I edited two READMEs and one CSS rule" is not a reflection day.

## The Template

Copy this skeleton. Fill it with specifics, not platitudes. Past reflections in `reflections/*.md` are your reference.

```markdown
# Daily Reflection — YYYY-MM-DD

_Authored by <chat name>, covering <time window>._

## What shipped
- Commits, SKILLS added/updated, CLAUDE.md changes, infrastructure built.
- Project-level outcomes (data loaded, features shipped, handoffs completed).
- Keep to bullets with concrete names / numbers. Not "various improvements."

## What broke or degraded
- Per incident: symptom → root cause → fix shipped → preventive rule.
- Include silent degradations (capacity drift, skill that was wrong, doc that misled).
- If something broke and was NOT RCA'd, surface that — it's a debt item.

## Patterns I'm noticing
- Things that happened more than once.
- Tools / skills / docs that keep coming up.
- Friction points agents worked around instead of fixing.
- Positive patterns too: what's compounding well?

## External best practices worth considering
- Things the industry does that we don't, where adoption might pay off.
- Be specific: name the practice, say why it might fit us, note cost.
- Mark "probably overkill" explicitly — surfacing and rejecting is still useful.

## Concrete improvements to propose (ranked by leverage)
- Each proposal: one paragraph.
- Leverage (high/medium/low) and effort (low/medium/high) called out.
- Link to open questions they resolve.

## What I'd do differently if today restarted
- Sequencing mistakes ("should have built X before Y").
- Scope mistakes ("spent 2 hrs on a thing that didn't matter").
- Discipline mistakes ("added a CLAUDE.md section I shouldn't have").

## Rule / skill proposals graduating to work items
- Bullet list of the concrete things that should become tasks / commits from this reflection.
- Each links back to a section above.
```

## How To Research Best Practices

Don't over-engineer this. A single session of structured thinking:

- **What felt clunky today?** That's usually the honest best-practice trigger. "We did X manually three times" → research automation patterns.
- **What did industry peers solve that looks analogous?** SRE practices for service-uptime concerns; agent-orchestration patterns (Langchain / MCP / Claude Agent SDK patterns); DevOps conventions for deploy / rollback / observability.
- **Don't import wholesale.** A pattern that works at Netflix's scale often doesn't fit a solo-operator droplet. Scale-match explicitly.
- **Web search is OK for research.** When you want to check current state of a technique, it's fine to pull a couple of authoritative references. Don't build a research report — one or two references that inform a proposal is enough.

Be honest about what's working. Boosting the signal on things that compound (other chats shipping skills, user actions discovered that would otherwise be buried) matters as much as calling out failures.

## Output Flow

1. Write the reflection to `/opt/site-deploy/reflections/YYYY-MM-DD.md`.
2. Commit with message `reflection: YYYY-MM-DD — <one-line theme>`. Push.
3. If any proposals graduated to immediate work items, file them as `TaskCreate` entries or ship them in the same commit where appropriate.
4. Notify the user with `notify.sh` priority `default`, click-URL to the file on GitHub (since no /reflections.html yet — TODO: add one if this practice sticks).

## Anti-Patterns

- **Platitudes.** "We made good progress today" is worthless. Name what shipped, by commit SHA or file path.
- **Blame-free at the cost of specificity.** "Something went wrong in the pipeline" is a cop-out. Name the module and the decision chain that led there.
- **Reflection as homework.** If it's become a checkbox, delete the template line you're struggling to fill and keep the rest. A good 3-section reflection beats a padded 7-section one.
- **Reflecting in private.** Commit to the repo. Future agents read past reflections as context.
- **Same proposals every day.** If a concrete improvement has been in three reflections without shipping, either ship it or kill it.

## Cadence Reminder Mechanism

Cron at 23:00 UTC (covers most active-session timezones):
```
0 23 * * * root /usr/local/bin/notify.sh "Daily reflection time — reflections/$(date -u +%Y-%m-%d).md" "Platform reflection" default "https://github.com/csosin1/ClaudeCode/tree/main/reflections"
```

The active orchestrator chat sees this and produces the file. If no orchestrator is active, the notify is a gentle prompt to spawn / re-engage one.

## Integration

- `SKILLS/platform-stewardship.md` — reflections are stewardship at a coarser grain. Every reflection's "proposals graduating" feeds the stewardship flywheel.
- `SKILLS/root-cause-analysis.md` — incidents captured in reflections should already have `LESSONS.md` entries; the reflection summarizes, not replaces.
- `SKILLS/session-resilience.md` — if the orchestrator chat can't be reached when reflection is due, any sibling chat with the state files can pick it up.
```

### /opt/site-deploy/SKILLS/data-audit-qa.md

```markdown
# Skill: Data Audit & QA

## Guiding Principle

**Act like a skeptical professional auditor, not a code reviewer.** The code may produce exactly what it was written to produce — and still be wrong. Every load-bearing number must be traceable back to an external primary source, and every calculation must be re-derived from first principles, not copied from the implementation.

## When To Invoke

- **Before promoting a data-heavy dashboard from preview to live** for the first time.
- **Before any analysis influences a real-world decision** (investment call, customer-facing price, regulatory filing).
- **When the user asks for a data audit** — they'll typically name the project.
- **After any non-trivial data-pipeline change** — not the schema, but anything that reshapes, aggregates, or re-ingests.
- **Quarterly or at a user-specified cadence** for live dashboards with ongoing ingestion.

Invocation trigger can be as simple as: "audit Carvana Loan Dashboard at 10% sample."

## The Two Phases

Both phases run in parallel where possible. See `SKILLS/parallel-execution.md` for dispatch mechanics.

### Phase 1 — Universal Outlier Scan (100% coverage, cheap)

Every numeric field / chart / dataset in scope gets a fast outlier pass. Automated first, visual second.

- Statistical outliers: z-score > 3 or IQR × 3 on each numeric column.
- Distribution smell tests: unexpected zeros, unexpected NULLs, uniform-looking values in fields that should vary, monotonic series that aren't monotonic, % fields outside 0-100, negative values where nonnegative is required, dates outside a plausible window.
- Cross-field invariants: `net = gross − allowance`, `pct_total ≈ sum(pct_components)`, `count_distinct ≤ count`, `min ≤ mean ≤ max`, time-series deltas within a plausible band.
- Visual smell: chart-by-chart, look for discontinuities, spikes that coincide with ingestion dates (a.k.a. "data error that looks like a market event"), 100% flat lines where variation is expected.

Phase 1 produces a ranked list of suspicious points. Everything flagged graduates automatically into Phase 2 — it gets checked regardless of sample selection.

### Phase 2 — Random-Sample Deep Verification (user-specified %, expensive)

- **Ask the user for a default sample rate** if not provided. Suggest 10% as a starting point; smaller datasets may need higher %, massive ones lower.
- **Risk-weight the sample.** Headline, load-bearing fields (anything the user looks at first, anything feeding a decision) get a higher rate, typically 2-3× the default. Helper / scratch fields can get the default or lower. The skill declares the weighting up-front so the user can override.
- **Sample deterministically.** Seed the RNG with the audit date + dataset name. This makes the audit reproducible and lets follow-up audits avoid re-sampling the same rows unless intentional.

For each sampled data point, do these three things — in parallel across the sample, one agent per batch of ~10-50 points:

1. **Trace to source.** Follow the data backward through every hop until you hit an external primary source. SEC filing URL, proxy site's original HTML, SQL from the raw ingestion table, API response body. Record the hop chain.
2. **Re-derive the math.** If the value is computed, figure out what the calculation *should* be from the domain and available inputs, then do the math yourself (arithmetic, aggregation, ratio). **Do not copy the calculation from the implementation** — that defeats the audit. Compare your number to the reported number.
3. **Document stopping condition.** If source is unreachable (filing deleted, site 404, API rate-limited), record "verification stopped at layer N: <reason>." Do not silently pass or silently fail — honest partial verification is the output.

## Sample Rate & Weighting Template

Before sampling, write this to the audit report so the user knows exactly what got checked:

```
Audit: <project> <date>
Default sample rate: 10%
Risk-weighted overrides:
  - Headline fields (net_receivables, allowance_coverage, delinquency_total): 30%
  - MD&A-derived narrative fields: 20%
  - Helper/scratch columns: 5%
  - Outliers from Phase 1: 100% (auto-included, not counted against sample)
Sample seed: <project>-<YYYY-MM-DD>
Total data points in scope: <N>
Total sampled: <M>
```

## Halt-Fix-Rerun Loop (how findings become fixes)

**Don't find the same root cause fifty times.** A single upstream defect typically produces many symptoms. Finding all fifty symptoms in one pass and then fixing is wasteful — the fix invalidates the already-completed verification, and you spent compute cataloguing duplicates.

Instead, the audit runs as a **halt-fix-rerun loop**:

```
while iteration < MAX_ITERATIONS (default: 10):
    run Phase 1 (outlier scan, 100%)  →  if any: halt immediately
    run Phase 2 (risk-weighted random sample, parallel batches)
    as soon as the first batch reports a finding:
        stop dispatching new batches
        let in-flight batches finish their current point (graceful halt, not abort)
        collect all findings that naturally surface in the drain
    if no findings:
        AUDIT PASSES — record and exit
    group findings by probable root cause
    fix the highest-severity group first
    mark symptoms in AUDIT_FINDINGS.md as "resolved pending re-audit"
    iteration += 1

if iteration == MAX_ITERATIONS:
    audit stops, flag to user — a fix isn't actually fixing and needs human review
```

### Finding format

Each finding — whether it triggers the halt or surfaces in the drain — appends one entry to `AUDIT_FINDINGS.md` at the project root:

```markdown
## F-<nnn> — <one-line symptom>
- **Location:** <file / dashboard tab / dataset field>
- **Observed:** <reported value>
- **Expected:** <re-derived value, with calculation>
- **Source chain:** <trace>
- **Stopping condition:** <if verification couldn't reach primary source>
- **Severity:** critical / high / medium / low
- **Iteration:** <which pass found it>
- **Flagged by:** <agent id / date>
- **Status:** open
- **Root-cause group:** <identifier, filled in during grouping>
```

Severity rubric:
- **Critical**: headline number wrong, or the error changes a user's decision.
- **High**: non-headline number materially off (> 1% error on a $-denominated field).
- **Medium**: cosmetic but noticeable (off-by-cent rounding, slightly wrong timestamp).
- **Low**: audit noise, self-consistent minor quirk.

### Grouping by root cause

Before fixing, the orchestrator asks: "could these findings share an upstream cause?" Common patterns:
- Same column across different rows → likely a formula or ingestion bug affecting that column.
- Same row across different columns → likely a single bad input record.
- Same time bucket across ticker/entity → likely a timestamp parsing or period-alignment bug.
- Numerical offsets that look like unit mismatches (factor of 1000, factor of 100, currency) → likely a units-of-measure bug.

If the pattern is clear, fix all findings with one change to the upstream code. If findings look genuinely independent, they get fixed in severity order, one group per iteration.

### Fixing (serial, root-caused)

Per `SKILLS/root-cause-analysis.md`:
1. Spawn one Builder subagent per root-cause group. Each fix ships with a `LESSONS.md` entry explaining the upstream defect and a preventive rule if applicable.
2. Mark the symptoms this fix resolves: `Status: resolved pending re-audit` in `AUDIT_FINDINGS.md`.
3. Next iteration: the rerun either confirms `resolved → verified` or escalates to `failed-after-fix` (the fix didn't work; RCA task filed).

### Pass criteria

One full iteration completes with zero findings → AUDIT PASSES. The `AUDIT_FINDINGS.md` reflects every finding from every iteration, with resolution blocks showing what fixed what. Users and future auditors can read the history.

### Why halt on first finding?

- **Compute efficiency.** Finding duplicates of the same root cause is wasted work.
- **Correctness.** Findings collected *after* a fix are stale — they're about an obsolete version of the code.
- **Forces RCA.** You can't chain "just fix them all" band-aids; every iteration commits a real upstream fix.

### When NOT to halt

- **Low-severity findings** (purely cosmetic): the orchestrator may choose to continue the pass and batch-fix lows at the end, IF the user has indicated tolerance for this. Default is halt-on-any.
- **Outlier scan is fast enough** that it usually completes before a halt decision matters.
- **If the user specifies "run to completion and show me everything"** (useful for a scoping pass before deciding on a sample rate). In that mode the halt is suppressed and all findings are reported as advisory.

## Parallelization Mechanics

- **Phase 1** is mostly one agent per dataset / chart — the outlier math itself is fast.
- **Phase 2** fans out aggressively. Batch ~10-50 checks per agent (each check has overhead; too-fine batching wastes tokens). Dispatch all batches in one orchestrator message with multiple `Agent` tool-use blocks.
- Each agent's brief must be self-contained: which rows it owns, what the expected schema is, which external source to trace to, which columns need re-derived calculation, what output format to return.
- Returning agents append directly to `AUDIT_FINDINGS.md` — no merge step needed beyond deduplication.

Before fan-out, the orchestrator checks `/capacity.json`. If warn/urgent, cap concurrency to stay within RAM headroom.

## Output Artifact

At the end of the audit loop, the project's `AUDIT_FINDINGS.md` is the canonical record, and a one-page summary goes into the user-facing response:

```
Audit: <project>
Date: <YYYY-MM-DD>
Scope: <what was in scope>
Iterations run: <N>   (halt-fix-rerun loop; clean pass required to exit)
Total findings across all iterations: <F>
  - <critical> critical, <high> high, <medium> medium, <low> low
Root-cause groups fixed: <G> (one commit per group)
Unreachable sources: <count> (honest stopping conditions recorded)
Final sample (clean pass): <M> points checked, 0 findings
Status: PASS | FAIL-MAX-ITER
```

`FAIL-MAX-ITER` means the loop hit `MAX_ITERATIONS` without a clean pass — typically a fix that isn't actually fixing the root cause. This is a human-review signal, not a platform decision.

The full finding list lives in `AUDIT_FINDINGS.md` with URLs/line refs and resolution blocks showing which commit resolved which finding. Future audits re-read this file as prior-art.

## Anti-Patterns

- **Trusting the code.** Reading the implementation and saying "looks right" is not an audit. Re-derive from first principles using the domain, not the code.
- **Verifying against the ingestion layer instead of the source.** If we ingested SEC filings into our own DB and you verify against the DB, you've verified nothing — you've confirmed the DB matches itself. Always go one hop further back.
- **Fixing in parallel.** Parallel agents making code changes collide and corrupt each other's output. Find in parallel, fix serially under orchestrator control.
- **Glossing over stopping conditions.** "Couldn't find the filing, moving on" is a finding, not a pass. Record where verification stopped and why.
- **Uniform sampling on non-uniform risk.** If a user looks at 5 headline numbers on a dashboard, those 5 should get near-100% coverage regardless of the overall sample rate.
- **Auditing once and calling it done.** Data changes; re-audit on a cadence. Quarterly is typical for live pipelines.
- **Finding everything, then fixing in bulk.** This is what the halt-fix-rerun loop avoids. Finding N symptoms of one root cause wastes N-1 agent-runs of compute AND produces stale findings once the fix lands.
- **Fix-and-move-on within an iteration.** After a fix, the loop *reruns* — do not mark findings resolved without re-audit verification. A "fix" that doesn't pass re-audit is a worse bug than the original (false confidence).
- **Infinite looping.** `MAX_ITERATIONS` exists. If the loop can't converge, stop and escalate to the user — the fix is probably touching a symptom, not the cause.

## Integration

- `SKILLS/parallel-execution.md` — the dispatch primitives. Phase 2 is the canonical use case.
- `SKILLS/root-cause-analysis.md` — every finding's fix follows RCA, never a symptom patch.
- `SKILLS/capacity-monitoring.md` — check before a big fan-out.
- `SKILLS/non-blocking-prompt-intake.md` — user questions during an audit get their own subagents; the audit keeps running.
- `SKILLS/platform-stewardship.md` — patterns discovered during an audit that would prevent *future* classes of error become new CLAUDE.md rules or LESSONS.md entries.
```

### /opt/site-deploy/SKILLS/deploy-rollback.md

```markdown
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
```

### /opt/site-deploy/SKILLS/feature-branch-worktree.md

```markdown
# Skill: Feature-Branch Workflow (worktree-based)

## When To Use

Any task that's more than a small fix. "Small fix" = <~30 lines, one file, no cross-cutting concern — those can push directly to main from `/opt/site-deploy`. **Everything larger uses a worktree.**

## Why Worktrees (Not Branch-Checkout)

Multiple project chats share `/opt/site-deploy`. If chat A switches it to a feature branch to work, chat B's next commit lands on A's branch — we've seen this happen and had to cherry-pick to recover. Worktrees give each task its own directory on its own branch, leaving the shared checkout permanently on `main`.

## The Commands

- **Start a task:**
  ```
  start-task.sh <project> "<description>"
  ```
  Creates branch `claude/<project>-<slug>` and a worktree at `/opt/worktrees/<project>-<slug>` off origin/main. Prints the worktree path. Updates task-status.

- **Do the work:**
  ```
  cd /opt/worktrees/<project>-<slug>
  # edit, commit as usual
  ```
  Pushing the branch does NOT deploy — only main deploys.

- **Ship to preview:**
  ```
  finish-task.sh <project>
  ```
  Pushes the feature branch, merges into main via the canonical `/opt/site-deploy` repo, pushes main, removes the worktree. Auto-deploy updates the preview URL in ~5 s.

- **User says "ship it":**
  ```
  bash /opt/site-deploy/deploy/promote.sh <project>
  ```
  Promotes preview → live. See `SKILLS/deploy-rollback.md`.

## Invariant

`git -C /opt/site-deploy branch --show-current` must always return `main`. `start-task.sh` auto-corrects if it's not, but that's a smell worth investigating.

## Troubleshooting

- **Worktree won't delete** (after `finish-task.sh`): `git worktree prune` then retry. Usually means a stale lockfile.
- **Merge conflict on finish-task.sh:** resolve in the worktree, then re-run `finish-task.sh`.
- **Branch already exists:** `start-task.sh` will refuse rather than clobber. Delete the stale one (`git branch -D claude/<project>-<slug>`) or rename the new task.

## Integration

- `SKILLS/deploy-rollback.md` — what happens after `finish-task.sh`.
- `SKILLS/session-resilience.md` — commit + push every 10-15 min so crashes don't lose worktree work.
- `SKILLS/root-cause-analysis.md` — every LESSONS.md entry commits alongside the permanent fix.
```

### /opt/site-deploy/SKILLS/llm-vs-code.md

```markdown
# Skill: LLMs for Judgment, Code for Computation

## Guiding Principle

**A deterministic step inside a prompt is a tax. An LLM call inside a deterministic pipeline is a fragility.** Pick the right tool for the work. If the operation has a precise specification, write code. If it requires contextual judgment, use an LLM.

## The Decision Test

Ask two questions:

1. **Can I write a spec for this that produces the same output every time given the same input?**
   - Yes → code.
   - No → LLM.

2. **Does this require understanding nuance, context, or ambiguity that I can't enumerate?**
   - Yes → LLM.
   - No → code.

When both answers agree, the call is obvious. When they disagree, the tie-breaker is cost and reliability — code wins by default because it's cheaper, faster, and traceable; LLM is the exception that must justify itself.

## What Belongs Where

### Code (deterministic)

- Arithmetic, aggregation, joins, filters on exact values.
- Parsing well-specified formats: JSON, CSV, XML with schema, Protobuf, known-shape HTML tables.
- Known API calls with known parameters.
- File operations: copy, move, compress, checksum, diff.
- Protocol handling: HTTP, SQL, SMTP.
- Formula evaluation with defined variables.
- Statistical outlier detection (z-score, IQR bounds, monotonicity checks).
- Regex on known-format strings.
- Deploy / CI / ops automation.
- Any step where non-determinism would corrupt a data pipeline.

### LLM (subjective)

- Classification with fuzzy edges ("is this chain a gym competitor?" when competitiveness is contextual).
- Extraction from unstructured narrative (management commentary, risk-factor sections, freeform customer notes).
- Judgment calls under ambiguity ("which of these findings cluster under the same root cause?").
- Novel-strategy decisions (how to approach a new scraping target whose flow isn't known).
- Writing, summarizing, translating, explaining.
- Code review / spec review where the judgment itself is the output.
- Tie-breaking between implementation approaches when tradeoffs aren't numerical.
- Resolving ambiguity in a user's request.

## Transition Moments

LLMs discover patterns; code exploits them. Once an LLM has mapped out how a task works, migrate to code:

- **After N successful runs of the same LLM task, pattern-mine it.** If Claude has navigated a site's checkout flow 5 times with consistent steps, write the deterministic wizard from the mined pattern. See `car-offers/lib/carmax.js` for the working example — LLM-nav discovered the flow, the deterministic wizard shipped it, and the per-run cost dropped from minutes of tokens to ~45 seconds of headless Chrome.
- **After the schema stabilizes, code the parser.** If Claude has extracted the same fields from the same filing type 10 times, write the XBRL / regex parser. See the `carvana_abs` parser — label-anchored, handles all historical format variants, no LLM in the loop.
- **After the decision criterion stabilizes, code the classifier.** If the same 4 classification categories get the same LLM verdicts consistently, promote the rules to code with the LLM as a tiebreaker / fallback.

The meta-rule: **any time an LLM does the same well-defined thing twice, consider migrating.** Not every LLM use migrates — some tasks are irreducibly judgment-y — but unexamined LLM reliance accumulates cost and non-determinism.

## Anti-Patterns From Our Platform

- **Using Claude to sum a column.** Happened in an early audit iteration. A deterministic re-derivation would have taken 3 lines of Python and zero tokens.
- **Using Claude to format a timestamp.** `strftime` exists and costs nothing.
- **Using Claude to classify with a hard rule embedded in the prompt.** If the prompt says "classify as X if column A > 100 else Y," the LLM is just executing the rule — write the rule as code.
- **Writing a deterministic pipeline and then "having Claude double-check."** If the code is right, the LLM check is noise. If the code is wrong, fix the code. Don't use an LLM as a trust fallback; use unit tests.
- **Calling an LLM to parse error messages into categories.** Error categorization with a known enum is a dictionary lookup, not a prompt.

## Cost Math (Why This Matters)

Rough ballpark for our platform:

- **Deterministic Python function call:** ~1 ms, $0 (compute is paid per-hour anyway).
- **Claude Sonnet call with ~1k input / 500 output tokens:** ~2-5 seconds, ~$0.01.
- **Claude Opus call with 10k context:** ~10-30 seconds, ~$0.15.

A pipeline that runs an LLM call per row on a 10k-row dataset costs ~$100+ and takes ~10 hours. A deterministic equivalent costs ~$0 and takes seconds. This is where "why are we burning so much on this task" comes from.

## When LLMs Add Real Value

- **Bootstrapping.** You don't yet know the pattern; the LLM discovers it. Then migrate.
- **Long tail.** 95% of cases are captured by code; the 5% weird edge cases go to the LLM.
- **Human-facing text.** Summaries, explanations, error messages for non-technical users.
- **Judgment calls that genuinely lack a specification.** "Does this PR look risky?" "Is this customer's complaint legitimate?" "Which of these three phrasings reads more trustworthy?"

## Integration

- `SKILLS/data-audit-qa.md` — calculations are re-derived from first principles **in code, never copied from the implementation or re-asked of an LLM**. The audit is the canonical example of "deterministic verification over subjective re-check."
- `SKILLS/platform-stewardship.md` — migrating LLM → code after pattern stability is a stewardship move. Log it.
- `SKILLS/root-cause-analysis.md` — "the LLM got it wrong this time" is rarely the real root cause. Usually the task didn't belong on an LLM in the first place.
```

### /opt/site-deploy/SKILLS/long-running-jobs.md

```markdown
# Skill: Long-Running Jobs (systemd + heartbeat + watchdog)

## Guiding Principle

**Any job expected to run longer than 15 minutes must be durable against Claude session death, OOM, and droplet churn.** The job's lifetime and the chat's lifetime are independent. If you launch a multi-hour ingest via `nohup bash -c '...' &` from an interactive Claude Code shell, you have a single point of failure — when the Claude session goes stale (remote-control relay drops, tmux hiccup) you've lost observability, and one OOM takes the whole thing down with no alerting.

Three-layer pattern that avoids this:

1. **systemd** runs the job (survives session death, enforces memory caps, auto-restarts on failure).
2. **Heartbeat file** lets anything on the droplet see progress at a glance.
3. **Watchdog cron** reads heartbeats + systemd status, alerts via push notification on stale / failed jobs.

## When To Use

- Any ABS / SEC / data ingest scoped to more than ~15 minutes of wall time.
- Multi-deal / multi-file batch jobs with >10 items.
- Model-training runs.
- Any scrape / crawl / long-running Playwright session.
- **Short jobs (<15 min) are exempt** — a `nohup bash &` backgrounded from Claude is fine.

## The Pattern

### Layer 1 — Launch via systemd (not nohup bash)

Use `systemd-run` for transient services (no service file to install):

```bash
systemd-run \
    --unit=<project>-<job-name> \
    --description="<one-line description>" \
    --property=MemoryMax=1800M \
    --property=Restart=on-failure \
    --property=RestartSec=30 \
    /path/to/worker.sh
```

Key properties:
- `MemoryMax=` — cgroup cap. If the job exceeds this, the kernel kills it cleanly inside its own cgroup, leaving the rest of the droplet untouched. Set it to the peak you can tolerate given other tenants on the host.
- `Restart=on-failure` — if the worker exits with non-zero (e.g. OOM, crash), systemd restarts it after `RestartSec`. Worker MUST be idempotent — each restart should resume from durable state, not reprocess work already committed.
- `--unit=` — stable name so you can `systemctl status <unit>`, `journalctl -u <unit>`.

For services that need to survive forever (not ad-hoc), write a proper `.service` file under `/etc/systemd/system/` with the same properties.

### Layer 2 — Heartbeat file

Every long-running job writes `/var/log/<project>/heartbeat.json` at every unit of work completed (every item, every minute, whichever is more frequent). JSON schema:

```json
{
    "job": "<project>-<job-name>",
    "started": 1776260000,
    "last_tick": 1776261111,
    "items_done": 7,
    "items_total": 33,
    "item_current": "deal-2019-4",
    "status": "running",
    "stale_after_seconds": 1800,
    "systemd_unit": "abs-ingest-carmax",
    "log_path": "/var/log/abs-dashboard/ingest.log"
}
```

Required fields: `job`, `last_tick` (unix epoch), `status` ∈ {`running`, `done`, `failed`}.
Optional but strongly recommended: `items_done`, `items_total`, `item_current`, `stale_after_seconds` (per-job threshold for what counts as stale — default 20 min), `systemd_unit`.

Write atomically: `heartbeat.json.tmp` → `os.replace()`. Never a half-written heartbeat.

**Best:** embed the heartbeat write directly in the worker's main loop (after every item).
**Acceptable fallback** for an in-flight job you can't modify: run a log-tail watcher alongside (like `deploy/heartbeat_writer.py` for abs-dashboard).

### Layer 3 — Watchdog + push alerting

`/usr/local/bin/monitor-long-jobs.sh` runs every 5 min via `/etc/cron.d/monitor-long-jobs`. It:

1. Iterates every `/var/log/*/heartbeat.json` + `/opt/*/heartbeat.json`.
2. For each: if `status` is failed/done, alert once (dedup via `/var/lib/monitor-long-jobs/alert-<key>`).
3. Else if `now - last_tick > stale_after_seconds`, alert (stale).
4. Else if a `systemd_unit` is named and `systemctl is-active` reports failed, alert.
5. Alert = push notification via `/usr/local/bin/notify.sh` with priority `urgent` for failures, `default` for completions. Dedup: re-alert at most once per hour per job.

User gets a push on their phone when something's wrong — even if Claude is offline, even if the relay is stale.

## Minimum working example

```bash
# Worker script (abs-dashboard/deploy/ingest_kmx.sh) writes heartbeat each deal:
cat > deploy/ingest_kmx.sh <<'EOF'
#!/bin/bash
set -euo pipefail
HB=/var/log/abs-dashboard/heartbeat.json
DEALS="2019-4 2020-1 ... 2026-1"
total=$(echo "$DEALS" | wc -w)
done_count=0
for d in $DEALS; do
    python3 -c "
import json, os, time
hb = {'job': 'abs-ingest-kmx', 'last_tick': int(time.time()),
      'items_done': $done_count, 'items_total': $total,
      'item_current': '$d', 'status': 'running',
      'stale_after_seconds': 1800,
      'systemd_unit': 'abs-ingest-kmx'}
os.makedirs(os.path.dirname('$HB'), exist_ok=True)
with open('$HB.tmp', 'w') as f: json.dump(hb, f)
os.replace('$HB.tmp', '$HB')
"
    python3 -m carmax_abs.run_ingestion --deal "$d"
    done_count=$((done_count + 1))
done
# mark done
python3 -c "import json, time; json.dump({'job':'abs-ingest-kmx','last_tick':int(time.time()),'status':'done','items_done':$done_count,'items_total':$total}, open('$HB','w'))"
EOF
chmod +x deploy/ingest_kmx.sh

# Launch under systemd:
systemd-run --unit=abs-ingest-kmx \
    --description="CarMax ABS-EE loan-level ingest" \
    --property=MemoryMax=1800M \
    --property=Restart=on-failure \
    --property=RestartSec=60 \
    /opt/abs-dashboard/deploy/ingest_kmx.sh
```

## Anti-patterns (what kills multi-hour jobs)

- **`nohup bash -c '...' &` from Claude Code shell.** Wrapper dies when the parent tree has issues. No auto-restart, no heartbeat, no alerting.
- **Silent success = fine assumption.** "I'll just check back in 2 hours." That's 2 hours of blindness.
- **`>= 15 min job` dispatched without heartbeat.** You won't know it died until you look.
- **`systemd-run` without `MemoryMax=`** on a memory-pressured host. An unbounded job will OOM the droplet's other tenants.
- **No `Restart=on-failure`.** Auto-restart is free and eliminates an entire class of "had to restart it by hand" work.
- **Heartbeat every hour instead of every item.** Your stale-detection window needs to be smaller than your item duration. If you process one item per 15 min, heartbeat every item.

## Resumability checklist

Before launching, confirm:
- [ ] Every item's work is idempotent. Re-running an already-done item is a no-op or makes zero-cost updates.
- [ ] Progress is committed to disk (DB write, file write) at the end of each item, not only at the end of the run.
- [ ] A fresh start from a stopped run can skip already-done items (query DB for what's done; don't re-do).
- [ ] Heartbeat write happens AFTER commit, not before.

## Integration

- Companion: `SKILLS/session-resilience.md` — handles the "Claude session died mid-work" case. This skill handles "the job outlives the session."
- Companion: `SKILLS/capacity-monitoring.md` — before kicking off a big job, check `/capacity.json`. Don't launch multi-hour jobs when the droplet is already `urgent`.
- When any OOM occurs during a job: log to `LESSONS.md` with the peak RSS + trigger conditions, so `MemoryMax=` is tuned for next time.
- If the watchdog fires: the alert must identify the job, unit, and log path so the recipient can diagnose without logging in blind.

## Incident reference

2026-04-15 abs-dashboard: 33-deal CarMax ingest launched via `nohup bash -c '...' &`. Python OOMed during 2019-4 at 04:40 UTC (2.5 GB RSS, 4 GB host with other tenants). Bash wrapper also terminated shortly after. No watchdog, no alerting. Failure went undetected for ~9 hours until user asked about status manually. Fix: this skill. Cost: ~9 hours of lost ingest throughput + manual discovery + resume.
```

### /opt/site-deploy/SKILLS/memory-hygiene.md

```markdown
# Skill: Memory Hygiene

## Guiding Principle

**Cheap wins only, on a regular cadence.** Memory hygiene is flossing — small, routine, boring, cumulative. Not a quarterly refactor. If a fix takes a meaningful design change or measurable performance tradeoff, file it as a separate task; don't bundle it into the hygiene pass.

## When To Run

- **On-demand when `/capacity.html` goes `warn` or `urgent`** — every chat audits its own code.
- **Once a week as routine** — each chat picks one day and does a pass, even if nothing's red.
- **Before a heavy new feature** — check you're not already bloated before adding more.

## The Audit Checklist

Walk through these. Each item takes < 5 min to check.

### 1. Streaming vs bulk loads
- [ ] Any `pd.read_sql("SELECT * FROM t")` or `.fetchall()` on a table > 10k rows → convert to `chunksize=` or cursor iteration.
- [ ] `json.load(huge_file)` or `f.read()` on files > 50 MB → stream with `ijson` / line-by-line iteration.
- [ ] Loading a whole directory of files into memory before processing → iterate instead.

### 2. Open handles
- [ ] Every file / DB / HTTP client opened is closed (`with` blocks, not bare `open()`).
- [ ] SQLite connections are closed after use, not cached forever in module globals.
- [ ] Playwright browser / context / page objects closed in `finally:` blocks.

### 3. SQLite quick wins
- [ ] `PRAGMA journal_mode=WAL` for write-heavy DBs (reduces lock contention).
- [ ] `PRAGMA wal_checkpoint(TRUNCATE)` periodically — WAL files grow unbounded without it.
- [ ] `VACUUM` after bulk deletes.
- [ ] `PRAGMA cache_size = -50000` (50 MB cache) instead of the 2 MB default if you have the RAM; `-10000` (10 MB) if you don't. Negative = KB.
- [ ] `PRAGMA mmap_size = 134217728` (128 MB) for read-heavy DBs lets the kernel page-manage cache.

### 4. Pandas
- [ ] Chained `.copy()` / `.assign()` / `.apply()` that each duplicates the frame → combine with in-place ops or a single assign.
- [ ] Object-dtype columns holding short strings → cast to `category` where cardinality is low.
- [ ] `astype('int64')` columns that fit in `int32` / `int16` → downcast.
- [ ] Keeping the raw DataFrame after transforming it → `del raw; gc.collect()`.

### 5. Long-running processes
- [ ] Watchers / daemons that read into a list forever → bound the list, or rotate to disk.
- [ ] Caches with no eviction → add an LRU bound (`functools.lru_cache(maxsize=...)`).
- [ ] Log handlers without rotation → add `logging.handlers.RotatingFileHandler`.
- [ ] Streamlit / Flask processes that grow slowly → add a periodic `gc.collect()` or a restart-on-memory-threshold systemd directive.

### 6. Browser automation
- [ ] Playwright contexts not closed after each test → `browser.new_context()` → `context.close()` per scenario.
- [ ] Persistent user-data-dirs growing unbounded → periodic purge.
- [ ] Multiple concurrent browsers when one serial run would do.

### 7. Caches on disk (RAM proxy)
- [ ] Raw source files kept alongside parsed outputs → gzip or delete.
- [ ] Logs not rotated / compressed.
- [ ] Test artifacts (screenshots, traces) not cleaned.

## What NOT To Touch In A Hygiene Pass

These are real wins but aren't "basic hygiene." File as separate tasks:

- Database schema changes (partitioning, column pruning).
- Moving data to external storage (S3, Spaces).
- Switching libraries (e.g., DuckDB over SQLite).
- Rewriting in a lower-level language.
- Adding a cache layer (Redis, memcached).

If you find yourself wanting to do one of these, stop, file the task, and move on to the next cheap-win.

## How To Measure Before / After

Tiny overhead, honest signal:

```python
import resource, os
print(f"RSS before: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.1f} MB")
# ... work ...
print(f"RSS after:  {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.1f} MB")
```

For a service, compare peak RSS in `systemctl status <service>` before/after a deploy.

For the platform overall: note `curl -s https://casinv.dev/capacity.json | jq .ram.pct` before and after the pass.

## Output Of A Pass

After each hygiene pass, a short entry in the project's `PROJECT_STATE.md`:

> **Memory hygiene 2026-04-14:** Found X wins (list). Shipped Y. Deferred Z as separate tasks. Peak RSS dropped/unchanged.

If a single pass found zero wins *and* a prior pass found many, that's a signal the prior work is holding up. If zero wins three times in a row, the checklist has probably gone stale — update it.

## Integration

- Companion skills: `SKILLS/capacity-monitoring.md` (triggers on-demand audits), `SKILLS/root-cause-analysis.md` (when investigating a memory incident, start here).
- This is platform stewardship applied to memory — per `SKILLS/platform-stewardship.md`, regular small improvements compound.
```

### /opt/site-deploy/SKILLS/multi-project-windows.md

```markdown
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
```

### /opt/site-deploy/SKILLS/never-idle.md

```markdown
# Skill: Never Idle

## Guiding Principle

**The user's time is the scarce resource on the platform.** Do not end a turn waiting for permission when any useful work remains. Build in parallel with asks outstanding.

## Blocker Brief (at task start)

While the user is still paying attention, enumerate every permission, secret, external account, domain, or piece of information you'll need across the full task. Ask for them all in one batch. Examples:
- GitHub token scopes.
- API keys (Stripe, Anthropic, OpenAI, etc.).
- Third-party logins (Auth0, Cloudflare, SendGrid).
- DNS control.
- Billing setup.
- Access to existing data sources.

File the items via `user-action.sh add …` so they don't get buried in chat.

## Work Around Blockers

While waiting for answers:
- Scaffold files, write stubs and mocks, set up tests.
- Write docs and spec the integration.
- Research the library or API.
- Build the infrastructure that doesn't touch the pending items.
- Leave clean hooks (clearly marked `TODO: fill <ITEM>` or `os.environ["KEY"]`) so the blocking pieces slot in when answers arrive.

If you discover a new blocker mid-work, add it to the running brief, pivot to unblocked work, batch the new ask with any pending ones. Never stop and wait.

## Never Emit These Phrases

- "Want me to continue?"
- "Should I proceed?"
- "Tell me if …"
- "Let me know and I can …"

If a decision is genuinely irreversible or externally visible, state the plan explicitly and execute unless stopped.

## Legitimate Reasons To End A Turn

- Everything is blocked on user input AND no unblocked work remains.
- Task is complete and QA is green.
- Scope has exploded into work that warrants a revised estimate (call it out explicitly; don't just keep going silently past a 200k-token budget — see `SKILLS/user-info-conventions.md § Token-Cost Guardrail`).

## Integration

- `SKILLS/user-action-tracking.md` — how to file pending asks.
- `SKILLS/non-blocking-prompt-intake.md` — sibling rule for handling new prompts during active work.
- `SKILLS/user-info-conventions.md` — the token-cost and stuck-detector guardrails that override "never idle" when they trigger.
```

### /opt/site-deploy/SKILLS/new-project-checklist.md

```markdown
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
```

### /opt/site-deploy/SKILLS/non-blocking-prompt-intake.md

```markdown
# Skill: Non-Blocking Prompt Intake

## Guiding Principle

**The main thread is a coordinator, not an executor.** When a new user prompt arrives while other work is in flight, the chat hands it off to a fresh subagent and stays available for the next prompt. The user should never be stuck watching the chat "Canoodling…" for 18 minutes because two earlier subagents haven't returned.

## Why This Exists

Observed failure mode: the carvana-abs chat launched 3 parallel subagents for a data-quality audit. The user then fired two new prompts ("why only 3 agents" and "kmx note tabs are missing data"). Both sat in the queue for 18+ minutes because the main thread was blocked waiting on the in-flight subagents to finish.

The fix isn't to make subagents faster. It's to stop treating the main thread as something that must "finish" before taking the next input.

## The Decision (fast)

When a new prompt arrives, categorize it in one sentence, then act:

| Category | Example | Action |
|---|---|---|
| **Independent** | "Look at the KMX note tabs for missing data" while running a Carvana integrity audit | Spawn a subagent immediately. Don't block. Report subagent dispatch to the user in a sentence, then return to orchestrating in-flight work. |
| **Clarifying / refining** | "Actually focus on delinquency not FICO" while a builder is mid-extraction | Integrate into in-flight context. If the subagent is far down a wrong path, interrupt it and relaunch with the refined scope. |
| **Correcting / aborting** | "Stop", "undo", "that's wrong" | Interrupt in-flight work immediately (`esc` / task cancellation). Surface the correction. |
| **Read-only status** | "What's happening", "any blockers", "show me X" | **Always** spawn a subagent or answer from cache — never block on anything. Status questions are the #1 reason blocking feels broken. |

When in doubt, default to "independent → spawn a subagent." False-positive spawning costs a few thousand tokens; false-negative blocking costs the user's patience.

## How To Dispatch (the mechanics)

In a single assistant message:

1. Acknowledge the new prompt in one short sentence. ("Dispatching an agent for the KMX note-tab question.")
2. Call `Agent` with a tight, self-contained brief (per `SKILLS/parallel-execution.md` — the agent hasn't seen the conversation, so the prompt must stand alone).
3. In the *same* message, continue orchestrating in-flight work (report on subagents, check their progress, plan the merge).
4. When the new subagent returns, surface its result in a new turn.

The key is **one message, multiple tool-use blocks**. Spawning the agent and continuing with existing work happen in parallel, not sequentially.

## What Belongs In The Main Thread

Short:

- Routing decisions ("this goes to subagent X, this to subagent Y").
- Merging outputs from returning subagents.
- Writing the final user-facing response once things converge.
- Interrupting / redirecting subagents when new info invalidates their scope.

What does NOT belong in the main thread:

- Running tests.
- Reading large files.
- Deep code investigation.
- Anything that blocks for >30 seconds.

If the main thread is doing any of those, the next user prompt will feel like a hang. Delegate.

## Anti-Patterns

- **Queue-and-wait.** Letting user prompts sit unread until the current work finishes. The queue is fine as a transport; the chat's job is to drain it in real time by dispatching each one.
- **"Let me just finish this first."** No. Spawn, report, move on. "Finishing first" is how 18-minute silences happen.
- **Spawning a subagent for something that takes 10 seconds.** The orchestration overhead isn't worth it. Trivial answers come from the main thread directly.
- **Spawning a subagent without a self-contained brief.** The subagent doesn't have your conversation context. If the prompt is "look at the KMX tabs," the brief needs to say *which* tabs, *what* "look at" means, *where* the data lives, *what output format*. See `SKILLS/parallel-execution.md § How To Dispatch`.
- **Letting subagents accumulate silently.** Every ~10 min of no status back to the user, surface a one-line progress update. "3 subagents still running: A done, B 70% through, C just started."

## Quick Rubric For When To Spawn

If **all** of these are true, spawn an agent:
- The new prompt can be answered by reading/grepping/searching code or running a tool with a known answer.
- It doesn't require reverting or redirecting in-flight work.
- It's more than a trivial 1-line answer.

If **any** of these is true, don't spawn — handle in the main thread:
- Correcting or aborting in-flight work.
- Trivial answer ("yes", "running fine", "3 agents still going").
- Requires synthesis across multiple in-flight results.

## Integration

- Companion: `SKILLS/parallel-execution.md` — the dispatch mechanics. This skill is the *when*; parallel-execution is the *how*.
- When in-flight work is expensive and a new prompt arrives, this skill has priority: do not make the user wait for the current stack to drain.
- Orchestrator chats (windows named `timeshare-surveillance`, etc. when acting as orchestrators) follow the same rule — even more strictly, since they tend to have more concurrent work.
```

### /opt/site-deploy/SKILLS/parallel-execution.md

```markdown
# Skill: Parallel Execution

## Guiding Principle

**Never do work sequentially that can run in parallel.** Wall-clock time is the scarce resource for the user. Five independent things run in parallel finish in the time of the slowest one, not the sum.

## What This Skill Does

Tells agents when to parallelize operations, when to keep them sequential, and how to actually dispatch them correctly with the tools available.

## When To Parallelize

Parallelize by default whenever all of these hold:

- **Independence of inputs.** Neither operation needs the other's output.
- **Independence of state.** They don't write to the same file, database row, branch, or external resource.
- **Independence of order.** The final result is the same regardless of which finishes first.

Concrete cases that should almost always be parallel:

| Situation | How to dispatch |
|---|---|
| Multiple Bash / Read / Grep / Glob calls with no data dependency | Single assistant message with multiple tool-use blocks. |
| Audit / research queries across several files or repos | Multiple `Agent` tool calls (with `subagent_type: Explore`) in one message. |
| Builder work on independent files/features | Multiple `Agent` tool calls with different scopes in one message (see Parallel Builders note below). |
| Status polls / health checks across services | One message, one tool call per service. |
| Running tests for different projects that share no fixtures | Fork Playwright workers, or parallel bash invocations. |

## When To Keep Sequential

- **Pipe dependencies.** Output of step N is input to step N+1. Forcing parallelism here just re-serializes with bookkeeping overhead.
- **Shared mutable state.** Two agents editing `package.json` or touching the same database migration will corrupt each other.
- **Exploratory work where early findings should redirect later steps.** Running three speculative builds in parallel wastes two when the answer to the first invalidates the others.
- **Rate-limited external APIs.** Parallelizing into a 429 is worse than serial.

## How To Dispatch In Claude Code

Independent tool calls go in **one assistant message with multiple tool-use blocks** — not sequential messages. That's what actually runs them concurrently; calling them in separate turns serializes them with full round-trip latency between each.

For heavier work (research, building), fan out `Agent` calls the same way: one message, N tool-use blocks, each with its own scope and clear file-path ownership.

When the orchestrator dispatches subagents, it must:
1. List the file paths each subagent will touch.
2. Verify zero overlap.
3. Launch them all in one message.
4. After all return, merge outputs and run a single Reviewer + single QA pass.

## Common Pitfalls

- **False independence.** Two Builders both writing to a shared `tests/` file — looks independent, isn't. If either touches a file the other might, serialize them or split the file first.
- **Race on shared branch.** Multiple project chats writing to the same branch in the shared repo. Avoided by the worktree-based branch hygiene (`/opt/worktrees/<project>-<slug>/`); see `CLAUDE.md § Feature-Branch Workflow`.
- **Sequential out of habit.** Running `git status`, then `git diff`, then `git log` as three separate messages. They're independent — one message, three tool-use blocks.
- **Over-parallelization.** Dispatching 20 Agents at once when 3 would do. Each Agent costs tokens; fan out to the granularity that matters.
- **Missing the join.** Fanning out without a plan for how to merge the outputs back. Always know who merges.

## Efficiency Self-Check

At every decision point ask: "Is anything I'm about to do next independent of anything else I'm about to do next?" If yes and I was planning them as separate messages, that's a bug — batch them.

## Escalation

If work that should have run in parallel ran serially and wasted >5 minutes, note it in `LESSONS.md` with the missed-parallelization pattern, so it becomes a tell-tale for future agents.
```

### /opt/site-deploy/SKILLS/platform-stewardship.md

```markdown
# Skill: Platform Stewardship

## Guiding Principle

**A problem solved once should never need to be solved again.**

Every other rule in this file is mechanism in service of that principle. If a write-up, edit, or extraction makes the next encounter of the same problem cheaper, do it. If it doesn't, skip it.

## What This Skill Does

Keeps the platform improving with every session. Defines *where* to put different kinds of learning, *when* to trigger a write-up, and *how* to keep CLAUDE.md thin so it stays readable and authoritative.

## When To Use It

At the end of every non-trivial task, and any time you notice friction, duplication, or a one-time cost that could be amortized. This is not optional — it's the mechanism by which the platform compounds rather than stagnates.

## The Four Registers of Knowledge

Every learning goes in exactly one of these. Picking the wrong one dilutes the others.

| Register | What belongs there | Test |
|---|---|---|
| `CLAUDE.md` | **Rules** that apply to every agent on every task. Behavioral norms, invariants, safety guardrails. | If it doesn't start with "always", "never", or "before X, do Y", it probably doesn't belong here. |
| `SKILLS/<topic>.md` | **How-to** for a reusable pattern — library, service, technique, integration. | "Next time someone needs to do X, they read this and succeed without relearning." |
| `LESSONS.md` | **Incidents and gotchas** — specific things that broke, root causes, what to watch for. | Written in past tense. "In April 2026, X happened because Y. Now we Z." |
| `RUNBOOK.md` | **Per-project operational facts** — URLs, paths, env var names, health checks. | Grounded in a specific project's reality; updates when infra changes. |

If a piece of knowledge feels like it fits two registers, you're probably about to bloat one. Split it: the rule goes in CLAUDE.md as a one-liner, the detail goes in SKILLS/.

## Triggers That Demand a Write-Up

Whenever any of these happen, write or update an entry **in the same commit as the work**:

- You spent >30 minutes figuring out a non-obvious pattern, API quirk, or integration → `SKILLS/<topic>.md`.
- You used a new library or managed service for the first time on this platform → `SKILLS/<library>.md`.
- Something broke in production or nearly did → `LESSONS.md` with root cause + fix + preventive rule.
- You solved the same class of problem twice across projects → it's now a skill; write it.
- You discovered a CLAUDE.md rule is wrong, stale, or missing a clause → edit CLAUDE.md *in the same commit* as the work that proved it, so the cause and correction stay linked.
- You noticed the platform doing something inefficient that a 1-hour fix would eliminate forever → add a task to track it, or fix it inline if trivial.

## Keep CLAUDE.md Thin (Three Mechanisms, Not Just A Norm)

CLAUDE.md is the constitution. Power lives in SKILLS/. "Keep it thin" as a principle has been observed to drift; these three mechanisms enforce it.

### 1. Thinness gate on every CLAUDE.md edit

Before adding a line or a section, answer: **does this rule fire on every task, regardless of what the task is about?**

- **Yes** → CLAUDE.md. It's a universal constraint.
- **No** → It's situational (only at deploy time, only when creating a new project, only when handling credentials). Write a SKILLS file. **Do not add a CLAUDE.md pointer** unless the situational skill needs to fire *at task start* for task discovery.

### 2. Pointer parsimony by default

Not every SKILL gets a CLAUDE.md pointer. The default is NO pointer; SKILLS are discovered via `ls SKILLS/*.md` at task start (see `Skills Registry — Search, Use, Contribute Back` in CLAUDE.md). Add a pointer only when:

- The rule must fire at every task start regardless of task topic (e.g., `Parallel Execution`, `Restore Then Root-Cause`).
- The behavior is surprising and agents would otherwise skip it (e.g., `Capacity Awareness` before heavy work).
- Failure mode costs real money or breaks user trust (e.g., `Data Audit & QA` for number projects).

Everything else (secrets, deploys, worktrees, multi-project windows, new-project setup) lives in SKILLS only and is discovered when needed.

### 3. Paired-edit review — every CLAUDE.md change carries a trim

Line counts are a dumb proxy; a long CLAUDE.md of strictly always-on rules is fine, and a short one padded with situational pointers is bloat. The real enforcement is quality, applied every time something changes.

**Rule:** every CLAUDE.md edit ships with a review pass over the *existing* sections. Before committing your new edit, run the thinness gate (Mechanism 1) on at least three current sections picked at random or by "oldest untouched." Find at least one thing to trim, compress, delete a pointer for, or relocate to SKILLS. Ship that cleanup in the same commit as your new edit.

This creates compound improvement: every addition comes paired with a refinement, so CLAUDE.md gets *more refined* over time, not just larger. Five edits over a month = five sections re-evaluated and likely five small cleanups, without a scheduled "CLAUDE.md diet" that nobody gets around to.

### 4. Event-triggered deeper reviews

Beyond the paired-edit discipline, do a full CLAUDE.md sweep whenever:

- The user asks something like "is CLAUDE.md getting thick?" or "what belongs in SKILLS?" — they've noticed drift.
- A new SKILLS file lands that could absorb an existing CLAUDE.md section.
- Stewardship or session-resilience rules change (those sections often have gravity and drag others along).
- More than ~5 situational skills have been added since the last sweep (natural aggregation point).

The sweep reads every CLAUDE.md section top to bottom, applies the thinness gate, and relocates everything that fails. Ship as one commit titled "CLAUDE.md sweep: <date> — N sections relocated / compressed."

### What the extraction looks like when you do need a pointer

```
## <Section name>
<One-sentence rule>. See `SKILLS/<topic>.md`.
```

Never:
- Examples or code snippets in CLAUDE.md (belong in SKILLS).
- History or "we used to do X" (belongs in LESSONS.md).
- Step-by-step procedures (belong in SKILLS).
- Multi-paragraph explanations (belong in SKILLS).

## Periodic Review

At the end of any session that touched CLAUDE.md:
1. Re-read the changed section. Is any part of it a "how" rather than a "what"? Extract.
2. Check line count. If CLAUDE.md has grown >10% since last review without the number of always-on rules growing proportionally, something is getting fat — find it and trim.
3. Diff the SKILLS/ index mentally — is there a skill that was referenced three times this week but doesn't exist yet? Write it.
4. Check for CLAUDE.md pointers to situational skills. Each one is a candidate for deletion (the skill stays; the pointer goes).

## Efficiency-Seeking Mindset

Beyond bug fixes and feature work, every session should leave one artifact that makes future sessions cheaper: a new skill, a sharper rule, a deleted dead file, a script that removes a manual step, a trimmed CLAUDE.md section. If the session ended with no such artifact, the platform stood still — that's the failure mode to avoid.

## Anti-Patterns

- **Silent learning.** Figuring something out, shipping the fix, and not writing it down. The cost of the write-up is ~3 minutes; the cost of relearning is hours.
- **CLAUDE.md as dumping ground.** Rules should be crisp enough to read in 90 seconds. Long-form guidance lives in SKILLS.
- **Skill files that read like essays.** SKILLS/*.md are reference, not narrative. Structure: What it does / When to use / Required setup / Minimal example / Gotchas.
- **Duplicate knowledge.** Same guidance in two places means it'll drift. Single source of truth; link from everywhere else.
```

### /opt/site-deploy/SKILLS/python-script-path-hygiene.md

```markdown
# Python Script Path Hygiene (avoid /tmp/ shadowing stdlib)

## What this is about
CPython prepends the script's own directory to `sys.path[0]`. If any `.py` file in that directory has the same name as a stdlib module (`inspect.py`, `types.py`, `json.py`, `random.py`, etc.), it **shadows** the stdlib module — which silently breaks imports deep inside packages that depend on the stdlib version.

`/tmp/` is the most common footgun: stray `.py` files from other projects or debugging sessions accumulate there, and any Python script you later launch from `/tmp/` inherits their namespace.

## When this bites
- You run `python /tmp/my_script.py` and it crashes with an error like
  `AttributeError: module 'inspect' has no attribute 'signature'`
  inside a third-party package (`typing_extensions`, `bs4`, `pydantic`).
- The same script works fine from `/opt/project/` and you can't figure out why.
- Error appears deep in the import chain, nowhere near your code.

## When to use this skill
- Before writing a one-shot Python helper, ask: where does it live?
- When you see a baffling stdlib-attribute error that only reproduces from a specific directory.
- When auditing a project's launch scripts / cron jobs.

## The rule

**Never put Python scripts in `/tmp/`** (or any dir you don't own).  Put them in the repo root (`/opt/<project>/`) so `sys.path[0]` is a directory whose contents you control.

If you must run from `/tmp/`:
1. Use `python -I` (isolated mode) — disables `sys.path[0]` prepending plus several other user-site behaviors.
2. Or set `PYTHONSAFEPATH=1` before invocation (Python 3.11+) — same effect, just `sys.path[0]`.
3. Or `cd /opt/<project> && python -m my_module` — using `-m` means `sys.path[0]` is `''` (current dir), which you at least know.

Note: `cwd=/opt/<project>` alone is NOT sufficient. `sys.path[0]` comes from the SCRIPT's directory, not the process cwd.

## Minimum working example
```bash
# BAD — will pick up /tmp/inspect.py if it exists
cp my_helper.py /tmp/ && python /tmp/my_helper.py

# GOOD — pin sys.path[0] to your project
cp my_helper.py /opt/<project>/ && python /opt/<project>/my_helper.py

# GOOD — isolated mode if you really must run from /tmp
python -I /tmp/my_helper.py
```

## Detection / prevention
Add to health checks:
```bash
# Flag any long-running python process whose script is in /tmp
pgrep -al "python.*\s/tmp/" && echo "WARN: python running from /tmp — risk of stdlib shadowing"

# Scan /tmp for .py files with stdlib names
find /tmp -maxdepth 2 -name "*.py" -exec basename {} \; \
    | sort -u | grep -f <(python -c "import sys; print('\n'.join(sys.stdlib_module_names))")
```

## Incident reference
2026-04-14 abs-dashboard: reparse script at `/tmp/cmx_reparse.py` failed 3× before I spotted `/tmp/inspect.py` from another project. Cost ~15 min.  Moved script to `/opt/abs-dashboard/cmx_reparse.py`; immediately worked.  Full root-cause in `/opt/abs-dashboard/LESSONS.md`.
```

### /opt/site-deploy/SKILLS/remote-control-fallback.md

```markdown
# Skill: Remote-Control Fallback

## When To Use

When the Claude Code iOS / desktop app is stuck on "Remote Control connecting…" and won't load a session. The watchdog's `reactivate-remote.sh` auto-handles most of these within a minute — use this skill when you need to reach a session *before* the watchdog does, or when the watchdog's reactivation itself fails.

## Why It Happens

`/remote-control` session URLs depend on Anthropic's relay service. The chat itself is healthy in tmux; only the relay binding is broken. Common causes:
- Anthropic relay momentarily unreachable.
- Network blip between your phone and the relay.
- The CLI's `/remote-control` slash command hit a transient error.

## The Fallback Path

Open https://code.casinv.dev on any device — this is the droplet's `ttyd` web terminal. Then:

```
tmux attach -t claude
```

Joins the main tmux session. To go to a specific project window:

```
tmux attach -t claude \; select-window -t <project>
```

Detach with **Ctrl-B** then **D**.

## Sending Input From The Terminal

The ttyd terminal lets you type directly into the Claude Code CLI. iPhone keyboards on a terminal aren't ideal (punctuation is buried, autocorrect interferes), but this path doesn't depend on relays working.

## Manual Reactivation

If you have terminal access and want a clean remote-control URL:

```bash
/usr/local/bin/reactivate-remote.sh <project>
```

This:
1. Escapes any stuck slash-command menu.
2. Re-issues `/remote-control` in the target tmux window.
3. Captures the new URL.
4. Updates the bookmark at `/var/www/landing/remote/<project>.html`.

Tap the bookmark from your phone to reach the new URL.

## When Everything Fails

If ttyd itself is unreachable:
- SSH directly: `ssh root@159.223.127.125` (from a laptop — no iPhone SSH).
- `tmux attach -t claude` from the SSH session.
- If tmux session itself is gone, `systemctl restart claude-tmux` rebuilds it and `claude-respawn-boot.service` will fire to respawn project chats.

## Integration

- `SKILLS/session-resilience.md` — the automatic recovery path this is a fallback for.
- `SKILLS/multi-project-windows.md` — the overall architecture.
```

### /opt/site-deploy/SKILLS/residential-proxy.md

```markdown
# Skill: Residential Proxy (Decodo/Smartproxy)

## What This Skill Does

Routes Playwright browser sessions through Decodo residential proxies, making automated browser traffic appear as real household users. Used for scraping sites with bot detection (PerimeterX, Cloudflare, etc.) and for submitting multi-step web forms without getting blocked.

## When To Use It

Any project that needs to automate interactions with sites that block datacenter IPs or detect non-human browser behavior.

## GitHub Secrets Required

These are already configured in `csosin1/ClaudeCode`:

| Secret | Value |
|--------|-------|
| `PROXY_HOST` | `gate.decodo.com` |
| `PROXY_PORT` | `7000` (standard residential endpoint; ports 10001–10007 also work but without geo params) |
| `PROXY_USER` | `spjax0kgms` |
| `PROXY_PASS` | *(stored in GitHub Secrets — never hardcode)* |

On the droplet, these go in `/opt/<project>/.env`. Never commit credentials to git.

## Dependencies

```bash
npm install playwright playwright-extra puppeteer-extra-plugin-stealth
```

## Base Playwright Configuration — Rotating (Use for Scraping)

```javascript
const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const browser = await chromium.launch({
  headless: false, // set true for production
  proxy: {
    server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
    username: process.env.PROXY_USER,
    password: process.env.PROXY_PASS,
  }
});
```

## Base Playwright Configuration — Sticky Session (Use for Multi-Step Forms)

```javascript
// For sticky sessions, append session ID to username
// Same session ID = same IP throughout the form flow
const sessionId = Math.random().toString(36).substring(7);
const stickyUsername = `${process.env.PROXY_USER}-session-${sessionId}`;

const browser = await chromium.launch({
  headless: false,
  proxy: {
    server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
    username: stickyUsername,
    password: process.env.PROXY_PASS,
  }
});
```

## Human-Like Behavior Helpers

```javascript
// Random delay between actions
const delay = (min, max) => new Promise(r =>
  setTimeout(r, Math.floor(Math.random() * (max - min) + min))
);

// Type like a human
const fillField = async (page, selector, value) => {
  await page.click(selector);
  await delay(200, 600);
  for (const char of value) {
    await page.type(selector, char, {
      delay: Math.floor(Math.random() * 150 + 30)
    });
  }
};

// Use these between every action
await delay(800, 3000);
```

## Network Interception — Capture JSON API Responses

```javascript
// Set this up before navigating — captures pricing API calls
page.on('response', async response => {
  const url = response.url();
  if (url.includes('api.') &&
      response.headers()['content-type']?.includes('application/json')) {
    try {
      const json = await response.json();
      console.log(`[API INTERCEPT] ${url}`, JSON.stringify(json, null, 2));
      // Store json to your database here
    } catch (e) {}
  }
});
```

## Disposable Email Generation

```javascript
// Generate a throwaway email for form flows — no human needed
const getDisposableEmail = async (page) => {
  await page.goto('https://www.guerrillamail.com');
  await delay(1000, 2000);
  const email = await page.$eval('#email-widget', el => el.textContent.trim());
  return email;
};

// Check inbox for verification emails
const checkInbox = async (page, subjectContains) => {
  await page.goto('https://www.guerrillamail.com');
  await delay(2000, 4000);
  const emails = await page.$$('.mail_item');
  for (const email of emails) {
    const subject = await email.$eval('.subject', el => el.textContent);
    if (subject.includes(subjectContains)) {
      await email.click();
      return await page.$eval('.email_body', el => el.textContent);
    }
  }
  return null;
};
```

## Proxy Verification Test

```javascript
// Run this to confirm proxy is working before any project
const verifyProxy = async () => {
  const browser = await chromium.launch({
    proxy: {
      server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
      username: process.env.PROXY_USER,
      password: process.env.PROXY_PASS,
    }
  });
  const page = await browser.newPage();
  await page.goto('https://ip.decodo.com/json');
  const content = await page.textContent('body');
  console.log('Proxy verified:', content);
  await browser.close();
};
```

## Bandwidth Estimates

| Site | Per VIN |
|------|---------|
| AutoTrader listing page | ~2-3MB |
| CarMax offer flow end-to-end | ~5-10MB |
| Carvana offer flow | ~8-15MB |
| Driveway offer flow | ~5-10MB |
| **Per VIN across all 3 buyers** | **~20-35MB** |
| **3GB budget covers** | **~85-150 full VINs** |

## Known Site-Specific Notes

- **Carvana** — Uses PerimeterX. Stealth plugin + residential proxies handle it. Don't exceed ~20 VINs/day per IP.
- **CarMax** — Lightest bot detection of the three. Good site to test against first.
- **Driveway** — Lithia Motors. Moderate detection.
- **For all three:** Use sticky sessions during form submission, rotate between VINs.
```

### /opt/site-deploy/SKILLS/root-cause-analysis.md

```markdown
# Skill: Root-Cause Analysis

## Guiding Principle

**Restore service fast when needed — then always fix the root cause.** Patching and RCA are not alternatives; the patch buys time, the RCA prevents recurrence. Stopping at the patch is how incidents compound into outages.

## What This Skill Does

Defines how to respond when code, tests, infra, or a deploy breaks. Forces the investigation down to the actual cause, requires the fix target that cause, and captures the finding in `LESSONS.md` so no one ever re-investigates the same thing.

## When To Use It

Any unexpected failure: test red, build broken, deploy stuck, prod alert, data corruption, agent loop, silent degradation. "Unexpected" is the trigger — if the failure is surprising, you don't yet know the cause.

## The Investigation

Ask "why" until the answer is either a concrete defect you can fix, or an environmental invariant you can enforce. Five levels is a rough floor; more is fine.

```
Symptom:       Playwright test flakes with "element not visible"
Why #1:        The element exists but isn't rendered when we assert.
Why #2:        The React component that renders it depends on an async fetch.
Why #3:        The test doesn't wait for the fetch to complete.
Why #4:        We have no `waitFor(network idle)` hook; tests assume instant render.
Why #5:        The test harness was written when the page was static.
Root cause:    Test harness pattern is incompatible with async-rendered pages.
Fix:           Replace `expect().toBeVisible()` with `await expect().toBeVisible()` + testid-based waitFor; add a harness helper so other tests inherit the pattern.
NOT a fix:     Adding `await page.waitForTimeout(500)` before the assertion.
```

If you find yourself about to write any of these, you're patching, not fixing:

- `sleep N` / `waitForTimeout`
- `retry: N` without understanding why it fails
- `try { ... } catch { /* ignore */ }`
- `// TODO: figure out why this is needed`
- Pinning a dependency version you haven't audited
- Restarting the service as the resolution
- Catching an exception and returning a default

These are symptom suppressors. They let the failure recur silently, often in a worse form.

## Mandatory Write-Up

After fixing the root cause, append to `LESSONS.md` in the same commit:

```markdown
## YYYY-MM-DD — <one-line symptom>
**Root cause:** <the actual cause, 1-3 sentences>
**Fix:** <what changed and where — file:line>
**Preventive rule:** <what should have caught this earlier — a test, a lint rule, a CLAUDE.md clause, a runbook check>
```

The preventive-rule line is the compound-interest part. If the same class of bug could happen again, turn it into a rule, test, or guardrail. If it can't — say so explicitly ("one-off, environment-specific") so future readers don't invent a guardrail for a non-recurring problem.

## Patch → Restore → RCA (the normal flow for urgent breakage)

When prod is down or a user is blocked and the root cause will take time, you **patch to restore first**. That is the right call — users shouldn't wait for your investigation. But the RCA is not optional; it's the second half of the same incident.

1. **Patch to restore.** Apply the minimum change that makes it work again. Mark the site with `// HOTFIX <date>: RCA pending — <one-line symptom>` so it's visible in code review.
2. **File the RCA follow-up immediately.** Before moving to anything else: `TaskCreate` or `user-action.sh add` with a deadline (default: within 24h, sooner for recurring incidents).
3. **Do the investigation.** 5-whys ladder until you hit the real cause. Don't let the patch lull you into assuming you understand what happened — the patch proves the symptom stopped, not the cause.
4. **Land the permanent fix + LESSONS.md entry in the same commit.** Remove the HOTFIX comment.
5. **Close the follow-up only after the real fix is deployed and verified.**

A patch that ships without step 2 is invisible incident debt. A patch that ships without steps 3-5 is technical debt with a fuse on it.

## Anti-Patterns

- **"It worked after I restarted it."** The state that made it fail is still there; you just reset the clock. Investigate what got into that state.
- **"Flaky test."** There's no such thing. There are tests with unhandled non-determinism, and tests whose assertions don't match the actual contract. Both have root causes.
- **Incremental patches on the same symptom.** If you're touching the same file three times to fix the same class of failure, stop patching and audit the whole component.
- **Fixing the error message instead of the error.** Changing what the logs say without changing why.
- **Root cause in the wrong layer.** If the bug is in config, fixing the code that mis-reads config doesn't help — fix the config schema so it can't be mis-read.

## Integration

- Companion skills: `SKILLS/platform-stewardship.md` (learnings belong in the right register), `SKILLS/parallel-execution.md` (spawn Explore agents in parallel while investigating — multiple hypotheses tested at once).
- `LESSONS.md` entries get read by every Builder and Reviewer — this is how preventive rules actually prevent.
```

### /opt/site-deploy/SKILLS/sec-xbrl-extraction.md

```markdown
# Skill: SEC XBRL Extraction (Edge-Case Issuers)

## What This Does

Reliably pulls credit / receivables metrics from SEC EDGAR companyfacts JSON for issuers who report inconsistently in us-gaap — specifically timeshare lenders (HGV, VAC, TNL), but the patterns generalise to any non-bank consumer lender.

## When To Use

Any pipeline pulling `us-gaap` financial concepts from EDGAR for issuers outside the banking sector. Banks tag their loan-loss concepts religiously. Non-bank lenders (timeshare, auto finance, BNPL, specialty finance) often:

- Stop tagging a concept entirely after a few quarters and only disclose it in MD&A text.
- Use only the `…Net` form and never the `…Gross` form.
- Never tag the value at all even when they disclose it in the footnotes.

## Three Hard-Won Rules

### 1. Never use `AllowanceForDoubtfulAccountsReceivable` as an allowance fallback for a non-bank lender.

It's the *non*-product doubtful-accounts balance (B2B receivables, deposits in transit, etc.). For a timeshare lender it's $4–93M. The real timeshare ACL is $500M–$1B. The fallback gives you a value that LOOKS plausible until you sanity-check arithmetic. Ditto `AllowanceForLoanAndLeaseLossesReceivablesNetReportedAmount` for non-loan products.

**Use only:** `FinancingReceivableAllowanceForCreditLosses` (note the plural — `…ForCreditLoss` singular is rare and often a misspelling), `TimeSharingTransactionsAllowanceForUncollectibleAccounts` for timeshare specifically, and the issuer's own extension namespace if present.

### 2. Always cross-check `gross − allowance ≈ net`.

This three-line check catches the entire class of "wrong tag picked" bugs. Any divergence > max($5M, 0.5% × gross) means at least one of the three values is from a different reporting concept than the others.

```python
def _check_receivable_arithmetic(records):
    for r in records:
        g, a, n = r.get("gross_mm"), r.get("allowance_mm"), r.get("net_mm")
        if None in (g, a, n): continue
        tol = max(5.0, 0.005 * abs(g))
        if abs((g - a) - n) > tol:
            log.warning("xbrl cross-check %s %s: gross=%s allow=%s net=%s",
                        r["ticker"], r["period_end"], g, a, n)
```

Wire this into your merge step. Warning-only — don't drop the record, but the warning surfaces the bug in logs immediately rather than weeks later when someone notices the dashboard is wrong.

### 3. XBRL coverage degrades over time. Always have a narrative fallback.

For HGV: `FinancingReceivableAllowanceForCreditLosses` last reported 2021-Q2. `NotesReceivableGross` stopped 2022. After those dates the values are only in the 10-Q/10-K text tables.

The fix: a `balance_sheet` narrative section in your extractor that asks Claude to find these values in MD&A text when XBRL is null. Keyword patterns that work for timeshare:

```python
"balance_sheet": [
    r"Timeshare financing receivables",
    r"vacation ownership notes receivable",
    r"Notes receivable, net",
    r"Allowance for (credit losses|loan losses|financing receivable)",
    r"Financing receivables",
],
```

## Companyfacts JSON Tips

- Path: `https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit-padded>.json`. Cache to disk (10–30 MB per issuer); the SEC has a 10 req/sec limit and you don't want to re-download.
- Required header: `User-Agent: <name> <email>` — anything else gets a 403.
- A single tag's value list contains both 10-K (annual) and 10-Q (quarterly) entries, with overlapping `end` dates. Filter by `(form, fp)` when matching to a specific filing — `fp=Q1/Q2/Q3/FY`.
- For instant tags (allowances, receivables) match on `end` date == filing's `period_end`. For duration tags (provisions, originations) the same `end` works but you must also check `start` to confirm it's a quarterly vs YTD figure.

## Sanity Bounds

After extraction, flag any value outside:
- `*_pct` fields: must be in [0, 1]. Anything outside means the issuer reported in basis points or whole-number percent.
- Allowance coverage `allowance / gross`: < 0.5% or > 50% is suspicious for a consumer lender. Timeshare lenders cluster 8–25%.
- Annual delinquency 90+ DPD: typically 1–10%. > 15% is a fingerprint of pulling a YTD writeoff number instead of a stock balance.

## Minimum Working Example

In `xbrl_fetch.py`:

```python
def fetch_metric(facts, candidate_tags, period_end, scale=1e-6):
    """Walk candidates in order. Return first match for period_end."""
    for ns in ("us-gaap",) + tuple(facts.keys() - {"us-gaap"}):
        for tag in candidate_tags:
            entry = facts.get(ns, {}).get(tag)
            if not entry: continue
            for unit, vals in entry.get("units", {}).items():
                for v in vals:
                    if v.get("end") == period_end and v.get("form") in ("10-K","10-Q"):
                        return v["val"] * scale
    return None
```

Importantly: the `_break_across_tags` failure mode — where a per-tag inner loop breaks out of the outer loop on first miss — has bitten us at least once. Make sure your loop structure tries ALL candidate tags before giving up.

## Files In This Project

- `/opt/site-deploy/timeshare-surveillance/config/settings.py` — `XBRL_TAG_MAP`
- `/opt/site-deploy/timeshare-surveillance/pipeline/xbrl_fetch.py`
- `/opt/site-deploy/timeshare-surveillance/pipeline/sec_cache.py` — disk cache (filings + companyfacts + submissions)
- `/opt/site-deploy/timeshare-surveillance/pipeline/merge.py` — `_check_receivable_arithmetic`

## Required Env

- `EDGAR_USER_AGENT` (any string with name + email; see `settings.py`)
- `ANTHROPIC_API_KEY` (only for the narrative fallback)

## Cost

Free for SEC EDGAR. Caching the companyfacts JSON makes re-extraction zero-network and fully repeatable.
```

### /opt/site-deploy/SKILLS/secrets.md

```markdown
# Skill: Secrets

## When To Use

Any time you're handling credentials — API keys, passwords, tokens, connection strings.

## Rules

- **No credentials in git.** `.gitignore` includes `.env`. nginx denies `.env`, dotfiles, `.md`.
- Secrets live in `/opt/<project>/.env` on the droplet (gitignored), or GitHub Secrets for CI.
- For user-entered secrets from a phone, expose a `/setup` page in the app (basic-auth gated or behind a one-time token). Never ask the user to SSH.
- Every credential has a corresponding entry in the `account.sh` registry so there's one canonical record of what service it serves. See `SKILLS/accounts-registry.md`.

## Anti-Patterns

- **Committing `.env.example` with real values.** Template files must contain only placeholders.
- **Hardcoding credentials "temporarily for debugging."** These stay.
- **Storing secrets in `CLAUDE.md`, `RUNBOOK.md`, `PROJECT_STATE.md`, or any `.md` file.** All `.md` files are publicly readable if nginx config slips; assume they will be.
- **One credential shared across projects.** If two projects both need Anthropic API, each has its own `.env` with its own key — so revoking one project's access doesn't disturb the other.

## If A Credential Leaks

1. Revoke on the provider's dashboard immediately (don't rotate — revoke).
2. Issue a new credential.
3. `git log --all -p | grep -i <partial-cred>` to confirm it's not in any commit or branch. If it is: force-push a scrubbed history and rotate everything that ever touched that repo.
4. LESSONS.md entry covering root cause (how did it slip past .gitignore / review / pre-commit?) and preventive rule.

## Integration

- `SKILLS/accounts-registry.md` — register every credential's service there.
- `SKILLS/security-baseline.md` — the overall security posture this operates within.
```

### /opt/site-deploy/SKILLS/security-baseline.md

```markdown
# Skill: Security Baseline

## When To Use

Before shipping anything user-facing. Before any auth, payment, data-exposure, or inbound-request handling. As the Reviewer subagent's mandatory checklist.

## The Baseline

These are non-negotiable. Failing any of these is a Reviewer FAIL.

- **Sanitize user input.** No string-concat into shell commands or SQL. Use parameterized queries, `subprocess.run([...])` lists (never `shell=True` with user data), and proper escape layers.
- **Dependency audit after adding deps.** `npm audit` / `pip-audit` runs on add; block on high/critical. Do not waive without a LESSONS.md note explaining why.
- **No custom auth.** Auth0, Clerk, or Supabase Auth only. HTTPS (Let's Encrypt) before any login ships.
- **Stripe for payments.** Checkout or Payment Links only — never custom card forms. Verify webhook signatures with the Stripe SDK, not by hand.
- **Row-level scoping on user-data queries.** A missing `WHERE user_id=…` is a critical failure. Code review checks this explicitly.
- **Firewall:** 80, 443, 22 only. Root SSH disabled, key auth only.
- **Secrets** per `SKILLS/secrets.md`.

## Reviewer Subagent Hook

The Reviewer reads this list before approving any PR. A PR that:
- Adds a new endpoint that handles POST without CSRF / auth,
- Adds a SQL query without parameterization,
- Introduces a new dep without `audit` output,
- Commits a `.env` or file matching credential patterns,

gets FAIL with the specific line and rule number violated.

## Common Omissions

- **No rate limiting** on public endpoints that hit an external API or DB. Add at nginx (`limit_req_zone`) or at the app layer.
- **Error messages leaking internals.** User-facing errors should be generic; detail goes to logs with a correlation ID.
- **Missing CSRF** on state-changing forms when sessions are cookie-based.
- **Assuming HTTPS** without HSTS on the response.
- **Logs containing PII or credentials.** Redact before writing.

## Integration

- `SKILLS/secrets.md` — secrets-specific rules.
- `SKILLS/accounts-registry.md` — every auth provider / payment processor gets registered.
- `SKILLS/root-cause-analysis.md` — security incidents always get RCA + LESSONS.md; preventive rules go into this skill file.
```

### /opt/site-deploy/SKILLS/session-resilience.md

```markdown
# Skill: Session Resilience

## Guiding Principle

**Any remote chat session can fail at any time — including the orchestrator.** Build every chat to be recoverable. The failure modes are distinct, the recoveries are distinct, and a session that vanishes should produce at most two minutes of user disruption — never lost work.

## The Failure Modes (and what happens under each)

| Failure | What's lost | What survives | Recovery |
|---|---|---|---|
| **Remote-control URL goes stale** (Anthropic relay blips, slash-command fails) | UX access on user's phone | tmux session, claude process, JSONL, all running tool calls | Watchdog detects missing "Remote Control active" status, runs `reactivate-remote.sh`, refreshes bookmark. Auto-recovers within 1 min of cron. |
| **Claude CLI process crashes** (OOM, uncaught bug) | In-flight tool calls | JSONL on disk, tmux window (empty), data, commits | Respawn cron or boot service runs `claude-project.sh` with `--continue`; chat resumes from JSONL. ~30-60 s downtime. |
| **Tmux window killed** (accidental, process reap) | Same as above | JSONL, data | Same — respawn cron recreates within 5 min. |
| **Droplet reboots / resizes** | In-flight tool calls across all chats; ~60-120 s of bookmark blip | Everything on disk | `claude-respawn-boot.service` runs 15 s after `claude-tmux.service`; every expected project chat comes back with `--continue`. Bookmarks refresh as URLs are captured. |
| **JSONL file corruption** (rare — duplicate writers) | The corrupted session's chat history | Other chats' JSONLs, data | Manual: identify the good jsonl by line count / content, move the corrupted one aside, restart window with `--continue`. |
| **Orchestrator chat dies mid-orchestration** | In-flight orchestration decisions, in-memory state | Everything on disk — including `PROJECT_STATE.md`, `AUDIT_FINDINGS.md`, `CHANGES.md`, cron, all other chats | Any other chat can pick up orchestrator role by reading the state files. The respawn cron brings the dead orchestrator back within 5 min with full history. |

## The Three Mandatory Habits

Because any chat can die, every chat at all times must:

1. **Keep `PROJECT_STATE.md` current.** If a chat dies and a resume reads the JSONL, the last few messages may be mid-tool-call. `PROJECT_STATE.md` is the ground-truth handoff document. Update it when focus changes, decisions land, or new open questions emerge — not at the end of the day. "Every 30 min of active work or on any meaningful transition" is the cadence.

2. **Commit and push frequently during long work.** Uncommitted edits in a worktree are lost if the worktree gets trashed during recovery. Every ~10-15 min of real work: commit, push. Branches on origin are the backup.

3. **Don't hold load-bearing state in conversation memory.** If a number, decision, or intermediate result matters, write it to `PROJECT_STATE.md`, `AUDIT_FINDINGS.md`, `CHANGES.md`, or a JSON file — not "I'll remember." You might not.

## Automatic Resilience (what the platform does without you)

- **`claude-watchdog.sh`** (every minute): scans tmux panes for each expected project. Detects `Remote Control active` status. If missing, calls `reactivate-remote.sh` to re-issue `/remote-control` and refresh the bookmark. After 3 failed attempts, escalates `urgent` notify to user.
- **`claude-respawn.sh`** (every 5 min): checks every expected project has a live tmux window. If missing, runs `claude-project.sh` with `claude --continue`, which resumes from the most recent JSONL.
- **`claude-respawn-boot.service`** (on droplet boot, +15 s): brings every expected chat back after a reboot / resize.
- **`/etc/claude-projects.conf`** lists every expected chat. Add / remove / rename entries to reflect the current project roster.

## Manual Recovery Playbook

When a chat appears "lost" from the user's perspective:

1. **Don't assume death.** Check first:
   - `tmux list-windows -t claude -F '#I #W'` — window still alive?
   - `ps -ef | grep claude` — claude process still alive?
   - `curl -s https://casinv.dev/liveness.json` — what does the watchdog see?
   - `ps -ef | grep <project-process>` — any project-owned background work still running?

2. **Recover the cheapest thing first.** If the tmux window is alive but remote-control is stale, run `reactivate-remote.sh <project>`. User gets new URL by re-tapping their bookmark.

3. **If the chat process is dead but the JSONL is fine:** `claude-project.sh <project> <cwd>` (or wait for the 5-min respawn cron). `--continue` resumes from the JSONL. Full conversation preserved.

4. **If the user has truly lost UX access and wants to transfer context to a sibling chat:** see the "Handoff" section below.

5. **Background processes are independent.** Killing a chat does not kill its subprocesses (Python ingestions, Playwright drivers, etc.). Verify any ongoing work is still running via `ps` before assuming it's dead.

## Handoff Playbook (chat A → chat B)

When the user wants chat B to take over chat A's work:

**Option 1 (preserves full history — preferred if possible):**
1. Kill chat B's current tmux window (drop its fresh JSONL).
2. Move chat B's fresh JSONL aside (rename to `.bak`).
3. Kill chat A's tmux window so its writer is released.
4. Identify chat A's JSONL in `/root/.claude/projects/-<cwd-slug>/` (usually the largest/most-recent).
5. Spawn a new window named B with `claude --continue` (same CWD) — it picks up chat A's JSONL.
6. Activate `/remote-control`, update bookmark at `/var/www/landing/remote/B.html`.
7. Update `/etc/claude-projects.conf`: remove A, add/keep B.
8. Update `/opt/site-deploy/deploy/projects.html` PROJECTS key to match B.

**Option 2 (just transfers state summary — simpler):**
1. Build a handoff brief from chat A's `PROJECT_STATE.md`, `CHANGES.md`, recent commits, running processes.
2. Send the brief to chat B via `tmux send-keys`.
3. Chat B reads the brief, acks, continues.

Option 1 is better when full history matters (audits, long investigations, complex in-flight decisions). Option 2 is faster and cleaner when chat B can pick up from just the state files.

## Checking Your Own Resilience Before Going Deep

Before starting a multi-hour investigation or big batch job, spend 60 seconds:

- Is `PROJECT_STATE.md` current with today's plan? If not, write it.
- Is there any uncommitted work? Commit.
- Would someone reading just `PROJECT_STATE.md` + recent commits understand what you're doing and why? If not, fix the doc.
- Is the project in `/etc/claude-projects.conf`? If not and it's a stable project, add it.

This takes a minute and saves the user 18 minutes of "canoodling" and a painful handoff if you die mid-task.

## Anti-Patterns

- **Assuming "stuck" = "dead."** The watchdog says "stuck" when a single activity has run >10 min. That's a flag, not a verdict. Check the process list before killing anything.
- **Killing tmux windows to "reset" a misbehaving chat.** This loses in-flight tool calls unnecessarily. `Escape` to interrupt is almost always better than `tmux kill-window`.
- **Rebuilding context in conversation rather than from files.** If you're re-explaining the project to yourself in a long prompt because "I can't remember," the `PROJECT_STATE.md` failed you — fix that, don't work around it.
- **Hot-editing `/etc/claude-projects.conf` without testing.** A typo here can prevent boot respawn. `bash -n /usr/local/bin/claude-respawn.sh` catches nothing; check with `awk '!/^#/ && NF{print $1}' /etc/claude-projects.conf`.

## Integration

- `SKILLS/platform-stewardship.md` — resilience is stewardship for the lifecycle of a chat.
- `SKILLS/root-cause-analysis.md` — when a chat dies, RCA the cause (was it OOM? hang? specific tool? relay?) so it doesn't recur.
- `SKILLS/non-blocking-prompt-intake.md` — a dying chat with a queued user prompt should hand off rather than silently lose it.
- `SKILLS/capacity-monitoring.md` — capacity pressure is the most common underlying cause of chat deaths.
```

### /opt/site-deploy/SKILLS/sqlite-multi-writer.md

```markdown
# SQLite across multiple writers — avoid WAL

## Purpose
Any project where a SQLite file is written by more than one process (a long-lived service + operator CLI tools + a background worker) needs to be careful about `journal_mode`. WAL's speed wins come with a subtle failure mode that silently eats data when processes restart uncleanly.

## The trap
`journal_mode = WAL` is the default recommendation for most SQLite deployments — it's fast, it allows concurrent reads during writes, it's the right answer for a single-process-writes scenario (one server + many readers). Every tutorial reaches for it.

But WAL writes go to `<db>.db-wal` first, and only land in the main `.db` file on **checkpoint**. Checkpoints happen either automatically (every ~1000 pages) or when the last connection closes. If three different processes write concurrently:

1. Service opens DB at startup, begins writing rows to WAL.
2. Operator CLI runs `node -e "insertOffer(...)"` — opens DB, writes to the *same* WAL file, closes.
3. Service restarts (deploy, SIGTERM). Its open WAL entries may not be checkpointed.
4. New service instance opens DB — sees main db file, sees WAL file, tries to recover.
5. If the WAL's state is inconsistent (split writes, missing pages, truncated on improper close), recent writes silently disappear. The newly-opened DB looks "fresh minus some rows."

Hours of silent data loss, no error messages.

## The fix
Use `journal_mode = DELETE` (SQLite's default, pre-WAL). Every COMMIT lands in the main `.db` file immediately via a brief exclusive lock. Standard file-locking serializes writes across any number of handles:

```js
const db = new Database(path);
db.pragma('journal_mode = DELETE');
db.pragma('synchronous = FULL');  // trade throughput for durability
```

You trade ~2–5× write throughput for absolute durability. At our typical load (tens of writes/second), this is invisible.

## When to prefer WAL anyway
- **Single process, many threads/connections.** A Node service with a connection pool; a Python app with several workers; a Go service. These all share one OS process and its transaction log behaves cleanly. WAL is the right answer here.
- **Read-heavy workloads where concurrent reads during a write matter.** WAL lets readers proceed without blocking; DELETE mode doesn't. Not relevant if you're writing infrequently.

## When to NEVER use WAL
- Service + operator CLI scripts that each open their own handle.
- Service + cron scripts that write to the DB.
- Multi-process workers.
- Anywhere a developer can run `sqlite3 the.db 'INSERT...'` or `node -e 'insertOffer(...)'` against a live db.

## Other precautions (orthogonal to journal_mode)

- **Short-interval backup cron.** `*/10 * * * * cp the.db backups/the-$(date +%Y%m%d-%H%M).db` takes 2 seconds to set up and makes every wipe recoverable. Install on day one.
- **Never keep live db files inside your rsync destination for a deploy pipeline.** Put them in a sibling path: `/opt/project-data/db/` or similar. If the deploy ever accidentally fails the exclude, the data is nowhere near the target.
- **Don't name your dev scratch db the same as prod.** We had `/opt/site-deploy/car-offers/offers.db` (dev scratch from CLI tests) sitting right next to the source dir that gets rsynced to runtime. Rsync excluded `*.db`, but one typo in the exclude would have copied scratch over prod.

## Reference implementation
`car-offers/lib/offers-db.js` after commit 448190d — canonical example of journal_mode=DELETE + synchronous=FULL + a 10-min backup cron. Any new project copying its offers-db pattern inherits the safe defaults.

## Failure-mode signatures to recognize
- "The database seems to reset every time I deploy."
- "Rows I inserted via CLI are missing after a service restart."
- Service logs show "database disk image is malformed" on startup.
- `.db-wal` file sitting alongside `.db` with a newer mtime than `.db`, and you just restarted.

All of these point at a concurrent-writer WAL race. Move to DELETE mode.
```

### /opt/site-deploy/SKILLS/user-action-tracking.md

```markdown
# Skill: User-Action Tracking

## Guiding Principle

**Never ask the user for something manual and then assume it's done.** If the action isn't programmatically verifiable by you, it belongs in the tracker, not buried in the chat.

## What This Skill Does

Tracks manual actions the user must perform (account signups, clicking UI buttons, pasting credentials, approving external requests) so they can't be forgotten. Produces a mobile-visible to-do list at `https://casinv.dev/todo.html` with a counter badge on the projects dashboard.

## When To Use It

Any time you're about to tell the user "please do X" where X happens outside the terminal. Examples:
- "Sign up for a Stripe account and paste the publishable key here."
- "Go to the Cloudflare DNS panel and add a TXT record."
- "Authorize the Gmail OAuth prompt when it opens."
- "Add the admin user in the Supabase dashboard."
- "Enable the Google Maps API in your Cloud Console."

## How To Use It

### Add a pending action

```bash
/usr/local/bin/user-action.sh add \
  <project-slug> \
  "<short title, one line>" \
  "<numbered step-by-step instructions, \\n separated>" \
  "<how you will verify — what you'll run or check to confirm done>"
```

Returns an action id (e.g. `ua-3a8edadb`). A push notification fires to the user's phone.

Example:
```bash
/usr/local/bin/user-action.sh add \
  timeshare-surveillance \
  "Add SMTP app-password for alert emails" \
  "1. Go to https://myaccount.google.com/apppasswords\n2. Create a password for 'timeshare-alerts'\n3. Paste it at https://casinv.dev/timeshare-surveillance/admin/" \
  "I'll GET /admin/ping and confirm SMTP_PASSWORD is set in .env"
```

### Check what's pending at the start of a session

Always run this at the top of any session before assuming prior asks are complete:
```bash
/usr/local/bin/user-action.sh remind
```

If anything in the list is relevant to the current session, attempt verification before doing new work that depends on it.

### Mark done — only after verification

```bash
/usr/local/bin/user-action.sh done <id>
```

**Before calling `done`, you must verify independently.** Curl the endpoint, read the env var, query the service's API, whatever the `verify_by` field described. Don't trust "I did it" from the chat — verify.

### Cancel if no longer needed

```bash
/usr/local/bin/user-action.sh cancel <id>
```

## Rules

1. **One action per ask.** If you need the user to do three things, file three actions. Individually trackable, individually verifiable.
2. **Steps must be runnable by a non-technical person on iPhone.** Plain prose, one action per numbered step, plain URLs (no markdown formatting — iOS tap detection chokes on it).
3. **Verification must be something *you* can run.** Not "confirm with me." A curl, a grep, an API check, an explicit page load that returns 200.
4. **Check the list at session start.** `user-action.sh remind` before deciding whether past asks are complete.
5. **Don't batch-close.** Each `done` is one verification. If you haven't verified, don't call done.

## Anti-Patterns

- **Assuming completion from chat context.** "They said they did it last session" ≠ done. Verify.
- **Vague verification.** `verify_by: "confirm with user"` is useless; that's exactly what the tracker is avoiding.
- **Bulk-cancelling stale entries.** If something's been pending a week, nudge the user once, don't silently cancel.
- **Adding the same action twice.** Check `user-action.sh list` first.

## Integration with Other Tools

- Notifies the user via `notify.sh` on every `add` and `done` — they see it on their phone immediately.
- Counter badge on `https://casinv.dev/projects.html` shows pending count.
- State is at `/var/www/landing/pending-actions.json`, served at `/pending-actions.json`.
- Companion: `SKILLS/accounts-registry.md` for tracking signed-up services themselves.
```

### /opt/site-deploy/SKILLS/user-info-conventions.md

```markdown
# Skill: User-Information Conventions

## Guiding Principle

**The user's attention is the scarcest resource on the platform.** Design every interaction as if they walked away five minutes ago and are coming back to check in. Make it trivial for them to understand current state, trivial for them to decide what's next, and impossible for a failure to go unsurfaced.

## When To Use

- Starting any non-trivial task (scope-upfront + status-file).
- Completing a task (done-signal + cost summary).
- Hitting a blocker (stuck detector).
- Anywhere a notification would save the user from having to check.
- End-of-session cleanup.

## Scope Upfront

Before starting any non-trivial task, say how long it'll take. "~15 min", "~1 hr", "~3 hr with multiple iterations." The user may walk away between prompt and completion — they need to know when to check back.

## The Task-Status File

Canonical source of "what's happening right now" for the projects dashboard.

```bash
/usr/local/bin/task-status.sh set "<project>" "<name>" "<stage>" "<detail>"    # when starting
/usr/local/bin/task-status.sh done "<project>" "<name>" "<summary>; ~42k tokens" <preview_url>  # when finished
/usr/local/bin/task-status.sh clear "<project>"                                 # when fully handed off
```

Writes to `/var/www/landing/tasks.json`. The user taps `https://casinv.dev/projects.html` to see status anytime. Don't skip `done` — the completion badge is how they know to check.

## Cost Visibility

Always include approximate token cost in the `done` summary:
```bash
task-status.sh done <project> "<name>" "completed; ~42k tokens" "<preview_url>"
```
The dashboard surfaces this per project. Users should be able to tell which tasks are cheap and which are expensive over time.

## Notifications

Push via `notify.sh`:
```bash
/usr/local/bin/notify.sh "<message>" "<title>" <priority> "<click-url>"
```
Priorities:
- **`urgent`** — hard blockers needing input NOW (droplet failing, credential leaked, user action needed).
- **`high`** — task done and awaiting review, or a milestone crossed.
- **`default`** — routine progress updates, job completions.

Preview deploys auto-notify via the webhook — no manual notify needed. For discrete milestones beyond deploy, call directly.

## Token-Cost Guardrail

If a single task exceeds ~200k tokens or has burned through that much without reaching QA-green, stop and surface the scope blowout via `notify.sh` with `urgent` priority. Do not spiral. User decides whether to continue, abort, or re-scope.

## Stuck Detector

If the same fix is attempted twice without progress (e.g., same test failure after two edits to the same file), stop. Update `/tasks.json` via `task-status.sh set "<project>" blocked "<what's blocking>"` and notify. **Never attempt a third identical fix.** Something deeper is wrong — investigate or escalate.

## GitHub Actions QA

Read QA run results:
```bash
gh run list --branch main --limit 5
gh run view <id>
```
`GH_TOKEN` is pre-configured in the environment.

## Context Compaction

Long sessions degrade response quality. At natural checkpoints (task done, big milestone, end of a QA iteration cycle), run `/compact` to trim conversation history. **Always before continuing to a new task in the same window.**

## Anti-Patterns

- **Silent completion.** Task done but no `task-status.sh done`, no notify. The user doesn't know to check.
- **Surprise scope blowouts.** Estimated 15 min, it took 3 hours, first the user hears is the completion notify. Update `task-status` halfway through with a revised ETA.
- **Burying an ask in a long response.** If the user needs to do something, `user-action.sh add` it — don't embed in prose.
- **Over-notifying.** Every tool call is not a notification. Milestones only. Otherwise the user's phone becomes noise.

## Integration

- `SKILLS/user-action-tracking.md` — the companion for asks that need the user's manual action.
- `SKILLS/platform-stewardship.md` — "problem solved once, never again" applies here too; surface patterns that save future informing overhead.
- `SKILLS/session-resilience.md` — status files + PROJECT_STATE.md survive chat death; they're the reliable communication surface.
```

=============================================================================
## 4. LESSONS.md
=============================================================================

### /opt/site-deploy/LESSONS.md

```markdown
# Lessons Learned

Append an entry when something breaks in a way that wasn't obvious from the code. Builders and Reviewers read this before starting a task.

## Format

```
## [YYYY-MM-DD] [short title]
- **What went wrong:**
- **Root cause:**
- **What to do differently:**
```

## 2026-04-14 — offers.db rows disappeared after preview redeploys (WAL race)
- **What went wrong:** Multiple service restarts during a working session silently wiped data from offers.db. Rows that were visible via sqlite3 at 16:28 UTC were gone by 16:35 UTC after a deploy/restart, despite the deploy script excluding `*.db` from rsync. Cost ≈45 min of debug + re-insert work and would have been worse without the 10-min backup cron installed earlier that session.
- **Root cause:** offers-db.js opened the database with `journal_mode = WAL` while THREE different handles wrote to it concurrently: (1) the long-lived Express service, (2) ad-hoc `node -e` operator scripts doing manual insertOffer/UPDATE consumers, (3) panel-runner invocations. In WAL mode, each writer's commits go to `offers.db-wal` first and only reach the main `offers.db` file on checkpoint. When the service was SIGTERM'd during a preview redeploy, it had an open DB handle whose WAL was not yet checkpointed; uncommitted WAL entries from the operator handles (which had close-flushed into the same shared WAL) were lost when the new service instance started and either truncated or ignored them.
- **Fix committed alongside the restore:** `lib/offers-db.js` now opens with `journal_mode = DELETE` + `synchronous = FULL`. Every COMMIT lands in `offers.db` immediately, and standard SQLite file-locking serializes writes across all handles. Trivially slower, zero data-loss. Commit 448190d. Also removed stray `/opt/site-deploy/car-offers/offers.db*` files from the source dir (leftover from prior CLI tests) so rsync can never pick them up.
- **Preventive rule (adopt in other projects): don't use WAL mode if multiple processes write to the same SQLite file.** WAL is for one-writer-many-reader workloads. Any project with an operator CLI + a service + a background worker should prefer `journal_mode = DELETE` (the SQLite default) and accept the modest throughput cost. Also: install a short-interval backup cron from day one — takes ten seconds, saves hours of debug. Skill doc: `SKILLS/sqlite-multi-writer.md`.

## 2026-04-13 — never POST to /api/setup from a builder without dry_run

- **What went wrong:** While testing the new /setup extension I ran a local Node instance in the worktree and POSTed a fake `{mturkAccessKeyId, ...}` body to `/api/setup`. The handler's sibling-mirror logic then wrote my fake values into `/opt/car-offers/.env` AND `/opt/car-offers-preview/.env`, wiping the real 18-char `PROXY_PASS` and the real `PROJECT_EMAIL` on both instances. When systemd restarted the services they booted with blank credentials.
- **Root cause:** Two problems compounded. (1) The handler's feature — mirroring to both sibling `.env` files — does exactly what it's supposed to but is unsafe in any test context where a bad test run can clobber real creds. (2) My local test node server was also bound to a port that the live service uses for its own workflow (3599 in this case), so stray `curl` calls from a terminal accidentally hit the wrong process.
- **What to do differently:** Any `POST /api/setup` test or local probe MUST pass `dry_run:true` (or `?dry_run=1`). The handler now honors this: it validates and returns the same shape but does not persist. Playwright tests in `tests/car-offers.spec.ts` all set `dry_run:true`. When you need to test the real persist path, do it against an isolated test directory — never point `__dirname` at or near `/opt/car-offers`. Recovery is possible (gcore + `strings | grep PROXY_PASS=` on the live node process) but only as long as the live service hasn't restarted yet.

## 2026-04-13 — patchright evaluate() runs in an isolated world

- **What went wrong:** Wrote a fingerprint unit test that set `window.__fp = result` from a `<script>` tag in the page, then read it back via `await page.evaluate(() => window.__fp)`. Always returned `undefined`, even though `document.title` (set on the same line) reflected the change.
- **Root cause:** Patchright (and Playwright with `useWorld: 'utility'`) runs `page.evaluate` in an *isolated* world — the same DOM, but a separate JS global object. `window.__fp` set in the page's main world is NOT visible to `evaluate`. Patchright does this by default to avoid the CDP `Runtime.enable` leak.
- **What to do differently:** When a fixture script must communicate with Node, write to a DOM attribute (`document.body.setAttribute('data-fp', JSON.stringify(out))`) and read it from Node via `page.getAttribute('body', 'data-fp')`. DOM is shared; window globals are not.

## 2026-04-13 — Object.defineProperty on Navigator.prototype isn't enough alone

- **What went wrong:** Stealth init script used `Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => 12 })` to spoof CPU count. Page still saw `2` (the patchright-injected value).
- **Root cause:** Navigator instances can have own-properties that shadow the prototype. Patchright (and likely Playwright itself) installs an own-property on `navigator` for some fields. A prototype-only override loses to an own-property.
- **What to do differently:** Always override at BOTH levels — `Object.defineProperty(Navigator.prototype, name, ...)` AND `Object.defineProperty(navigator, name, ...)` — and make both `configurable: true` so the second call doesn't throw. Helper:
  ```js
  const defNav = (name, value) => {
    try { Object.defineProperty(Navigator.prototype, name, { get: () => value, configurable: true }); } catch(e){}
    try { Object.defineProperty(navigator, name, { get: () => value, configurable: true }); } catch(e){}
  };
  ```

## 2026-04-13 — `addInitScript` + `+`-concatenated try/catch is fragile

- **What went wrong:** Built the stealth init script as one giant `'try { ... ' + 'foo;' + 'bar;' + '} catch(e){}'` string concatenation. Page silently ignored the script — `window.__stealthApplied = true` (the very first statement) was never set, but no error surfaced because `addInitScript` swallows page-side syntax errors silently.
- **Root cause:** The script had a syntax error (a try without a matching catch on the same logical line) but `addInitScript` runs the script via `eval`-style injection and a syntax error means *the whole script never runs*, with no error propagated to Node. There's no console listener early enough to catch it either.
- **What to do differently:** (1) Build the init script as a single template literal with real newlines, not string concatenation. (2) Always validate the generated script's syntax in Node BEFORE injecting: `try { new Function(scriptStr); } catch(e) { throw new Error('init script syntax: ' + e.message); }`. (3) Add a marker statement at the very top of the init script (`window.__stealthApplied = true`) so tests can verify the script ran at all, separately from verifying individual patches.

## 2026-04-13 — concurrent agent sessions racing on a shared git worktree

- **What went wrong:** Mid-edit, the local branch repeatedly reset itself, files reverted to older content, and `cd` between bash invocations would land on a different branch than the prior command was on. Ate ~30k tokens of unnecessary cherry-picks and stash dances.
- **Root cause:** Multiple parallel Claude sessions were running in different tmux windows against the same `/opt/site-deploy/` worktree. Each session was checking out its own branch, blowing away in-flight work in the other sessions' working tree.
- **What to do differently:** Long multi-file edits in shared-worktree environments should (a) commit-and-push aggressively after each logical chunk so origin survives the race, (b) use `git worktree add` to spin up a per-session worktree, or (c) do all writes + commit in one atomic Bash invocation chained with `&&`. Option (a) is the cheapest and worked here.

## [2026-04-14] Overpass attic queries silently return 0 for bbox+tag historical queries

- **What went wrong:** Built a 4-year quarterly historical backfill on the assumption that Overpass's `[date:"YYYY-MM-DDTHH:MM:SSZ"]` attic header would give us point-in-time OSM data for our existing country-bbox + `leisure=fitness_centre`/`sports_centre` queries. Shipped it, ran it against the main `overpass-api.de` mirror. First quarter (2022-06-30) completed in 26 min and returned only 256 locations across all six countries (vs 41,754 present-day). Dashboard trend column showed mostly blank.
- **Root cause:** The main Overpass instance accepts the `[date:]` attic header syntactically (returns 200) but returns 0 elements for bbox+tag queries — **silently**, not as an error. Confirmed via four direct tests: `[date:"2025-04-01"]` → 0 elements, `[date:"2026-04-01"]` (asking attic for "now") → 0 elements, plain query (no attic) → 2,844 elements, small-bbox attic → rate-limited. Attic on the public mirror is effectively unusable for our query shape at any time range. Official Overpass docs hint at this ("attic is limited on the public instances") but don't say it fails silently. The one quarter we collected actually got its 256 locations via a different code path — fallback mirror or retry without attic — which further masked the issue until we inspected the numbers.
- **What to do differently:**
  1. **Before committing hours of wall-clock to a batch run against a new-to-us external API, run a one-query smoke test and sanity-check the element count against a baseline.** A 15-second curl would have shown 0 elements and saved the full build cycle. Adding this as a general rule in `SKILLS/external-api-smoke-test.md`.
  2. **Treat silent empty responses as failures.** The builder's `collect_snapshot` returns success when the element count is tiny — should warn/halt when historical count is <5% of present-day, because that's a near-certain silent-fail signature.
  3. **For OSM historical data specifically:** the usable paths are (a) Wayback Machine scraping of chain store-locator pages for the ~20 chains we actually care about, (b) Geofabrik planet-file history extracts processed offline with osmium (heavy: ~50GB/snapshot), or (c) chain financial disclosures. Pick (a) for Basic-Fit competitive tracking — aligned with the actual signal we need.

## 2026-04-15 — zram missing from stock DigitalOcean Ubuntu kernel

**Symptom:** `apt install zram-tools && systemctl start zramswap` → service fails with
`modprobe: FATAL: Module zram not found in directory /lib/modules/6.8.0-107-generic`.

**Root cause:** DO's default Ubuntu 22.04 cloud kernel ships a stripped modules
set. `zram` isn't in the base `linux-image-*` package — it's in
`linux-modules-extra-$(uname -r)`, which isn't installed by default.

**Fix:** `apt-get install -y linux-modules-extra-$(uname -r)` then the
service starts cleanly. `modprobe zram` confirms the module loads.

**Preventive rule:** future droplets that need optional kernel modules
(zram, nbd, dummy, ipvs, etc.) should install `linux-modules-extra-$(uname -r)`
before `apt install`-ing the tool that depends on them. Add to the
new-droplet bootstrap checklist once we have one.

## 2026-04-16 — Carvana Loan Dashboard overnight OOM; chat respawned but didn't notice dead ingestion

**Symptom:** User arrived in the morning to find carvana-abs-2 "working" (dispatching agents) but the carmax ingestion that was supposed to complete overnight had died silently. The chat didn't realize the ingestion was gone.

**Root cause (compound):**
1. **OOM kill at 02:19 UTC.** Markov model loaded all covariate data at once → 912 MB Python process on a 4 GB box with 5 Claude chats (1.2 GB) + zram. Kernel OOM-killed the Python process + the Claude CLI in the same tmux cgroup scope.
2. **Ingestion ran as `nohup &`, not `systemd-run`.** No MemoryMax cap, no auto-restart, no heartbeat. `SKILLS/long-running-jobs.md` prescribes `systemd-run` but was never applied to this job. Third incident with this root cause.
3. **Respawned chat didn't verify background work survived.** `claude-project.sh` sent "read PROJECT_STATE.md" but not "check if your background processes are still alive." Chat resumed from JSONL, continued dispatching new agents, never noticed the ingestion was dead.
4. **No project-progress cron.** Watchdog checks "is the chat alive?" not "is the project making progress?" An overnight stall went undetected for hours.

**Fix:**
1. `project-checkin.sh` — new cron every 30 min. Detects: busy chat with stale PROJECT_STATE.md (>60 min), idle chat with in-progress task (should be doing something), dead long-running jobs. Sends status-check prompt + notifies.
2. `claude-project.sh` updated: post-spawn prompt now includes "check if background processes from prior work are alive via `ps`." Catches the respawn-after-OOM blind spot.
3. OOM fix already committed by the carvana-abs-2 chat (`0e7ab53`: chunked covariate loading, 5 deals/batch).

**Preventive rule:** Long-running jobs (>15 min) MUST use `systemd-run` with `MemoryMax` per `SKILLS/long-running-jobs.md`. Agents that launch `nohup ... &` for >15-min processes are violating the skill. The project-checkin cron is the oversight mechanism. PROJECT_STATE.md must be updated every 30 min during active work — stale state during active work is now an alertable condition.
```

=============================================================================
## 5. RUNBOOK.md
=============================================================================

### /opt/site-deploy/RUNBOOK.md

```markdown
# Runbook — site-deploy
Last updated: 2026-04-12

## Droplet
- IP: 159.223.127.125
- OS: Ubuntu 22.04 LTS
- Backups: DigitalOcean automated backups
- SSH: key-based, root disabled

## Projects

### Landing Page
- URL: http://159.223.127.125/
- Server path: /var/www/landing/
- Process: static (nginx)
- Deploy: auto-deploy syncs `deploy/landing.html` → `/var/www/landing/index.html`

### Games (Static)
- URL: http://159.223.127.125/games/
- Server path: /var/www/games/
- Process: static (nginx)
- Deploy: auto-deploy syncs `games/` → `/var/www/games/`

### Carvana Hub
- URL: http://159.223.127.125/carvana/
- Server path: /var/www/carvana/
- Process: static (nginx)
- Deploy: auto-deploy syncs `carvana/` → `/var/www/carvana/`

### Car Offer Comparison Tool
- Live:    https://casinv.dev/car-offers/
- Preview: https://casinv.dev/car-offers/preview/
- Server paths: /opt/car-offers/ (live) and /opt/car-offers-preview/ (preview)
- Process: two systemd units — `car-offers.service` on port 3100 (live) and `car-offers-preview.service` on port 3101 (preview), both running `node server.js`
- Browser stack: Patchright-patched Chromium, headed on Xvfb :99 (deploy-script-managed). Persistent profile at `<path>/.chrome-profile/`, sticky Decodo session at `<path>/.proxy-session` (23h TTL).
- Dependencies: patchright, playwright, dotenv, express (plus `playwright-extra` + `puppeteer-extra-plugin-stealth` still in package.json as fallback — active code path is Patchright)
- Env vars (in `/opt/car-offers{,-preview}/.env`): `PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, `PROXY_PASS`, `PROJECT_EMAIL`, `PORT`
- Deploy script: `deploy/car-offers.sh` (preview-first; promote via `deploy/promote.sh car-offers`)
- Health check: `curl -sf https://casinv.dev/car-offers/ | head -c 200`
- Diagnostics endpoint: `/api/last-run` returns last Carvana attempt's wizard log + proxy diag
- **Shared-infra deps:** `/etc/nginx/sites-available/abs-dashboard` (nginx location block); `car-offers.service` + `car-offers-preview.service` + `xvfb.service` systemd units; `/var/log/car-offers/` logrotate; 5-min uptime cron.

### Gym Intelligence
- URL: http://159.223.127.125/gym-intelligence/
- Server path: /opt/gym-intelligence/
- Process: systemd `gym-intelligence.service` (port 8502 live) + `gym-intelligence-preview.service` (port 8503 preview)
- Dependencies: flask, anthropic, httpx, thefuzz
- Env vars: `ANTHROPIC_API_KEY`
- Deploy script: `deploy/gym-intelligence.sh`
- **Shared-infra deps:** nginx location blocks `/gym-intelligence/` (live) and `/gym-intelligence/preview/`; systemd units `gym-intelligence.service` + `gym-intelligence-preview.service`; `/var/log/gym-intelligence/` logrotate; 5-min uptime cron.

### Timeshare Surveillance
- URL: https://casinv.dev/timeshare-surveillance/
- Preview: https://casinv.dev/timeshare-surveillance/preview/
- Setup page: https://casinv.dev/timeshare-surveillance/preview/admin/ (paste SMTP creds here from phone; live equivalent at /timeshare-surveillance/admin/)
- Server paths: /opt/timeshare-surveillance-live/ and /opt/timeshare-surveillance-preview/
- Process: two systemd pairs per instance — `timeshare-surveillance-watcher{,-preview}.service` (EDGAR poller) and `timeshare-surveillance-admin{,-preview}.service` (Flask setup page on ports 8510 live / 8511 preview)
- Dashboard: static HTML served directly by nginx from `<path>/dashboard/index.html`
- Dependencies: anthropic, flask, requests, python-dateutil
- Env vars (in `/opt/timeshare-surveillance-{live,preview}/.env`): `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL`, `ADMIN_TOKEN`
- Deploy script: `deploy/timeshare-surveillance.sh`
- Weekly cron: `0 6 * * 0 /opt/timeshare-surveillance-live/watcher/cron_refresh.sh`
- Health check: `curl -sf https://casinv.dev/timeshare-surveillance/ | grep -q 'Timeshare'`
- **Shared-infra deps:** nginx location blocks `/timeshare-surveillance/` (live) + `/timeshare-surveillance/preview/`; four systemd units (`-watcher` + `-admin`, live + preview); weekly cron `0 6 * * 0` on live watcher; `/var/log/timeshare-surveillance/` logrotate; 5-min uptime cron.

### Carvana ABS Loan Dashboard
- URL: https://casinv.dev/CarvanaLoanDashBoard/
- Preview: https://casinv.dev/CarvanaLoanDashBoard/preview/
- Checkout: /opt/abs-dashboard/ (same repo as site-deploy, second clone)
- **Branch tracking: `claude/carvana-loan-dashboard-4QMPM`** — `/opt/auto_deploy.sh` pulls the feature branch, NOT main. This is an architectural deviation that predates our branch-hygiene rules. PR #1 on csosin1/ClaudeCode tracks the same branch. (Note: prior RUNBOOK claimed "now tracking main" — incorrect; corrected 2026-04-16.)
- Served from: /opt/abs-dashboard/carvana_abs/static_site/{live,preview}/ (static HTML generated by the pipeline; not in git)
- Process: static (nginx)
- Generation pipeline: `/opt/auto_deploy.sh` runs every 30s via `auto-deploy.timer`; full pipeline does ingestion/model/PDF/preview generation via `/opt/abs-venv/` Python env
- Deps: weasyprint system libs; python deps in `/opt/abs-venv/` from `carvana_abs/requirements.txt`
- **Shared-infra deps:** nginx location blocks `/CarvanaLoanDashBoard/` (live) + `/CarvanaLoanDashBoard/preview/`; `/opt/auto_deploy.sh` + `auto-deploy.timer` (shared across repo); `/opt/abs-venv/` shared Python env; `/var/log/auto-deploy.log`. **This project's auto-deploy is the one variant from the standard flow — worth normalizing eventually.**

## Auto-Deploy
- Push to `main` → GitHub webhook → nginx → Python listener on `127.0.0.1:9000` → deploy in 2–3s
- Fallback: 5-minute timer
- Main script: `/opt/auto_deploy_general.sh` (copied from `deploy/auto_deploy_general.sh`)
- Project scripts: `deploy/<project>.sh` (sourced by main script)
- Webhook listener: `/opt/webhook_deploy.py` (`webhook-deploy.service`)
- Webhook secret: `/opt/.webhook_secret` (chmod 600)
- Deploy log: `/var/log/general-deploy.log`
- Webhook log: `/var/log/webhook-deploy.log`

## nginx
- Config: `/etc/nginx/sites-available/abs-dashboard`
- Version file: `deploy/NGINX_VERSION`
- Reload: `sudo systemctl reload nginx`

## QA
- Trigger: every push to `main`
- Workflow: `.github/workflows/qa.yml`
- Tests: Playwright at 390px mobile and 1280px desktop
- Results: GitHub Actions tab; screenshots uploaded as artifacts

## Known Cleanup
- **abs-dashboard checkout** at `/opt/abs-dashboard/` is the same GitHub repo as site-deploy, just cloned to a second path with its own 30s timer that runs the dashboard generation pipeline. Both checkouts now track `main`. Full normalization (moving the generation pipeline into `deploy/carvana-abs.sh` under the general deploy, retiring the second checkout, and deleting `/opt/abs-venv/`) is still pending — deferred because it touches the ingestion/model/PDF pipeline with live-traffic risk.
- Rollback tag for the unify-on-main step: `rollback-pre-unify-20260412-190105` in `/opt/abs-dashboard`.

## Rebuild From Scratch
1. Provision Ubuntu 22.04 LTS droplet on DigitalOcean
2. Install nginx, node 22, python3
3. Clone repo to `/opt/site-deploy/`
4. Copy `deploy/auto_deploy_general.sh` → `/opt/auto_deploy_general.sh`
5. Install `webhook-deploy.service` on port 9000 with `/opt/.webhook_secret`
6. Install a 5-minute timer/cron that runs `/opt/auto_deploy_general.sh` as fallback
7. Run `deploy/update_nginx.sh` to configure nginx routes
8. Push to `main` to trigger deploys (installs deps, creates services)
9. Verify all URLs return 200
```

=============================================================================
## 6. ADVISOR_CONTEXT.md (the orientation doc, included for single-file reading)
=============================================================================

### /opt/site-deploy/ADVISOR_CONTEXT.md

```markdown
# Advisor Context — casinv.dev Platform

_Author: infra orchestrator. Last written: 2026-04-16._

**Purpose of this document:** give an external advisor (or a fresh Claude session acting as one) enough context to reason about the platform without re-discovering everything. This is a snapshot, not a living doc — check the referenced paths for current state.

---

## 1. Who the user is, and how they work

- Solo operator. Runs an investment firm (C.A.S. Investment Partners); this platform is for personal-investment research and a few side experiments.
- **Non-technical, iPhone-primary.** Prompts on the phone, taps links, checks dashboards. No desktop, no terminal, no IDE.
- Claude does the technical work end-to-end: write code → deploy → verify → report. User's role is direction + approval.
- Explicit preferences (documented in `/opt/site-deploy/CLAUDE.md`):
  - **Thin CLAUDE.md + thick SKILLS/** — master CLAUDE.md is 96 lines. Situational guidance lives in 28 skill files under `SKILLS/`.
  - **LLMs for judgment, code for computation.** If an operation is deterministic (arithmetic, known-format parsing, defined endpoint), write code. If it needs contextual judgment (ambiguous input, narrative extraction), use an LLM.
  - **Parallel everything.** Never serialize independent work.
  - **Non-blocking prompt intake.** Main thread coordinates; subagents execute. User prompts never block on in-flight work.
  - **Restore, then root-cause.** Patch to restore service if urgent, but always follow with RCA + LESSONS.md entry. Never stop at the patch.
  - **Challenge the approach.** When a request has a simpler alternative (managed service, library, different architecture) that saves >30% of the effort or eliminates a failure mode, propose it — recommend one, don't menu.
  - **Never idle.** Don't end a turn waiting for permission when useful work remains.
  - **No surprise bills.** Claude Max plan is $200/mo flat; user explicitly does not want usage-based billing anywhere in the stack (avoids AWS Lambda, Browserless, metered cloud services).
  - **URLs must be plain in user messages.** iOS link detection breaks if URLs are wrapped in `**` or `[text](url)` or backticks.

---

## 2. Physical infrastructure — current

**One droplet, DigitalOcean Premium Intel:**
- IP: 159.223.127.125
- Specs: 2 vCPU / 4 GB RAM / 70 GB NVMe SSD
- Cost: $32/mo
- Running as root (solo-operator; no multi-user concerns)
- OS: Ubuntu 22.04 LTS
- nginx front-door; systemd for services; cron for automation
- Let's Encrypt TLS (HSTS preloaded via `.dev` TLD)

**Current capacity (as of snapshot):**
- RAM: 69% (2.85 / 4.11 GB) — `ok` individually but `warn` overall due to swap
- Swap: 31% (1.29 / 4.2 GB total, including zram) — `warn`
- Disk: 74% (52.9 / 71.7 GB) — `warn` (growing from CarMax data ingestion)
- Load: 0.34 (1-min) on 2 cores — idle
- Overall: `warn`

**Capacity infrastructure:**
- `zram` swap enabled (1.9 GB, LZ4, priority 100) — ~800 MB effective RAM headroom.
- Disk swap: 2 GB file, priority -2 (fallback under zram).
- `vm.swappiness = 100` — prefer swapping idle pages.
- `/usr/local/bin/capacity-check.sh` writes `/var/www/landing/capacity.json` every 5 min; fires phone notifications on threshold breach (warn/urgent).

**Known capacity incidents:**
- **2026-04-15 02:19 UTC**: kernel OOM killed a 912 MB Python process (Markov model covariate load) + cascaded to the Claude CLI in the same tmux cgroup. LESSONS.md has the full RCA. Fix: chunked covariate loading committed (0e7ab53); `project-checkin.sh` cron shipped afterward so a similar silent stall would be caught in ≤30 min not 9+ hours.
- Frequently runs hot around car-offers multi-browser runs + abs-dashboard ingestion concurrent with several active Claude chats.

---

## 3. Platform architecture — the orchestration model

**Multi-project Claude Code chats running in a persistent tmux session.** One chat per project, plus one orchestrator.

```
tmux session "claude"
├── window 0: bash (terminal)
├── window 1: car-offers                  cwd: /opt/car-offers
├── window 6: gym-intelligence            cwd: /opt/gym-intelligence
├── window 7: timeshare-dashboard         cwd: /opt/timeshare-surveillance-preview/dashboard
├── window 8: carvana-abs-2               cwd: /opt/abs-dashboard
├── window 9: infra (orchestrator)        cwd: /opt/infra/       ← this agent
└── window 3: timeshare-surveillance      cwd: /opt/timeshare-surveillance-preview  (vestigial;
                                            same process as `infra` — rename happens on next respawn)
```

**The orchestrator (`infra` chat) role:**
- Owns shared infra (CLAUDE.md, SKILLS/, helpers/, deploy scripts, cron, nginx, systemd, /var/www).
- Does NOT own any project source code.
- Explicit scope rules in `/opt/infra/CLAUDE.md`: allow-list + forbid-list, plus "if a platform change needs project-code changes, dispatch to the project chat, never touch directly."
- Commit target is always `/opt/site-deploy/` via explicit `git -C`.

**Project chats:**
- Each owns its own `/opt/<project>/` directory, `tests/`, deploy script under `deploy/<project>.sh`, systemd units, nginx location blocks.
- Each maintains its own `PROJECT_STATE.md` (dynamic: current focus / last decisions / open questions / next step).
- Each uses git worktrees at `/opt/worktrees/<project>-<slug>/` for feature-branch work, so the shared `/opt/site-deploy/` stays on main.

**Remote-control URLs & bookmarks:**
- Each chat has a stable bookmark at `https://casinv.dev/remote/<project>.html` that redirects to whatever underlying session URL is current.
- URLs change when chats crash/respawn; bookmark redirects update automatically.
- `claude-project.sh <project> <cwd>` spawns a new chat, activates `/remote-control`, writes the bookmark.

**Watchdog / respawn machinery:**
- `/usr/local/bin/claude-watchdog.sh` — every 1 min. Scans tmux panes: detects `esc to interrupt` for busy/stuck classification, checks `Remote Control active` status, auto-calls `reactivate-remote.sh` when stale.
- `/usr/local/bin/claude-respawn.sh` — every 5 min. Reads `/etc/claude-projects.conf`, spawns any missing windows (via `claude --continue` when prior JSONL exists).
- `claude-respawn-boot.service` — oneshot on droplet boot, runs `claude-respawn.sh` 15s after `claude-tmux.service` so chats come back post-reboot within ~30-60 s.
- `/usr/local/bin/project-checkin.sh` — every 30 min. Project-level progress check (busy+stale-PROJECT_STATE, idle-with-in-progress-task, dead long-job heartbeats). 2-hour cooldown per chat to avoid self-reinforcing loops.

**Long-running job contract** (`SKILLS/long-running-jobs.md`):
- Jobs expected to run >15 min MUST use `systemd-run` with `MemoryMax=` + `Restart=on-failure`.
- Must emit a heartbeat to `/var/www/landing/jobs/<name>.json` every 2-5 min.
- Watchdog escalates: stale heartbeat 5-20 min = default notify; >20 min or PID gone = urgent notify.
- **Known gap**: the `carmax_abs.run_ingestion` that caused the 02:19 OOM was launched as `nohup &`, not systemd-run. Migration to the proper pattern is a pending item for carvana-abs-2.

---

## 4. Project portfolio

### 4.1 Car Offers (`/opt/car-offers/`)
- **URL:** https://casinv.dev/car-offers/ (live) + `/preview/`
- **Purpose:** browser-driven automation that pulls valuation offers from Carvana / CarMax / Driveway on a panel of real VINs (29 consumers with realistic profiles).
- **Stack:** Node.js + Patchright (patched Chromium) + Playwright + Decodo residential proxy. LLM-nav via browser-use for unknown site flows; deterministic wizards for mapped flows.
- **Status:** CarMax wizard fully working (6 real runs, 3 outcome states). Carvana wizard blocked by Cloudflare Turnstile — needs CapSolver API key (pending user action). Driveway blocked by fingerprint-level detection — needs Prolific or Browserbase.
- **Memory footprint:** up to 2.5 GB when running multi-browser Carvana retries.

### 4.2 Gym Intelligence (`/opt/gym-intelligence/`)
- **URL:** https://casinv.dev/gym-intelligence/
- **Purpose:** competitive-tracking dashboard for Basic-Fit (European gym-market investor research). Identifies competitor gym chains, tracks location counts by country over time.
- **Stack:** Flask + vanilla JS mobile-first dashboard. OSM/Overpass for location data. Anthropic Claude for competitor classification (≥4-location floor to bound cost).
- **Status:** Live dashboard working. Recent 4-year quarterly backfill done (DE share 18.5% → 23.8% directional finding). 145 chains still `unknown` classification, cheap rerun queued.
- **Memory footprint:** small (~100 MB Flask).

### 4.3 Timeshare Credit Dashboard / Surveillance (`/opt/timeshare-surveillance-preview/` and `-live/`)
- **URL:** https://casinv.dev/timeshare-surveillance/
- **Purpose:** automated SEC EDGAR credit-surveillance pipeline for timeshare receivable ABS from Hilton Grand Vacations (HGV), Marriott Vacations (VAC), Travel+Leisure (TNL). Pulls 10-Q/10-K filings, extracts credit metrics via XBRL (structured) + Claude on narrative snippets, diffs against prior periods, emails alerts on credit deterioration.
- **Stack:** Python watcher + Flask admin page + static HTML dashboard. XBRL-first extraction (per SKILLS/sec-xbrl-extraction.md), falls back to narrative-Claude for fields not in XBRL (delinquency %, FICO, vintage).
- **Status:** Stable. Known issue: delinquency/FICO/vintage fields null across current 2025-Q3 10-Qs; narrative-snippet extraction may not be locating the right HTML sections. Deferred.
- **Separate chat:** `timeshare-dashboard` (window 7) owns the dashboard UI layer specifically; `timeshare-surveillance-preview` chat is the pipeline.

### 4.4 Carvana Loan Dashboard / ABS (`/opt/abs-dashboard/`)
- **URL:** https://casinv.dev/CarvanaLoanDashBoard/ + `/preview/`
- **Purpose:** ABS (asset-backed securities) loan-performance dashboard for Carvana auto-loan ABS deals + CarMax CarMax Auto Owner Trust (CAOT). SEC EDGAR ingestion + loan-level performance analytics (delinquency curves, loss buildups, vintage comparisons).
- **Stack:** Python ingestion pipeline + SQLite DBs (~10 GB) + generated static HTML. Dashboard is a Python-generated multi-page site (not Streamlit).
- **Status:** Carvana fully shipped (16 deals, 417k loans, Bayesian loss models live). CarMax currently mid-ingestion (37 deals planned, intermittent — OOM'd last night at deal 5/37). Pipeline currently NOT running post-OOM; carvana-abs-2 has the ball.
- **Scale:** `/opt/abs-dashboard/carmax_abs/db/*.db` total ~6.5 GB + ingested XML filings compress gzipped ~1 GB. Biggest data-footprint project on the droplet.

### 4.5 Landing + minor static (`/var/www/landing/` etc.)
- **URL:** https://casinv.dev/
- **Purpose:** project index page + a few static pages (dashboards: `/projects.html`, `/capacity.html`, `/todo.html`, `/accounts.html`, `/telemetry.html`, `/jobs.html`).
- **Games** (`/games/`): toy static games (Banana Blaster, Snake, Dino Dash).
- **Carvana Hub** (`/carvana/`): mini landing page for Carvana-related tools.

### 4.6 Planned (not yet built)
- **Compliance app** (PII-handling, internal or client-facing TBD) — user wants this on its OWN isolated droplet, strict separation from other apps. Decision pending on what exactly it does, which drives HIPAA/GDPR/SOC scope.

---

## 5. The rules system

### 5.1 CLAUDE.md (96 lines, `/root/.claude/CLAUDE.md` + `/opt/site-deploy/CLAUDE.md`)
Behavioral constitution loaded automatically into every Claude Code session. Intentionally thin — contains always-on rules that fire on every task. Situational guidance is in `SKILLS/*.md`, discovered via `ls SKILLS/` at task start.

**Key sections:**
- User Context, URLs-plain
- Clarify Before Building, Challenge the Approach
- Every Task Passes Three Gates (Build / Review / QA → user "ship it" → promote)
- Spec Before Any Code
- Parallel Execution, Non-Blocking Prompt Intake
- Project Isolation (shared paths never modified from a project chat)
- Continuous Platform Improvement, Skills Registry (search-use-contribute)
- Autonomy
- LLMs for Judgment, Code for Computation
- Restore, Then Root-Cause
- User Actions & Accounts (file manual asks in `user-action.sh`, register accounts in `account.sh`)
- Capacity Awareness, Session Resilience
- Memory Hygiene, Data Audit & QA
- Keep-the-User-Informed, Never Idle
- Git (branch from `origin/main` only; never branch off another feature branch)
- Shared-Infra Smoketest (run `projects-smoketest.sh gate` before any commit to `/etc/nginx`, `/etc/systemd`, `/etc/cron*`, `/var/www/`)

### 5.2 SKILLS/ (28 files, varying lengths)
Reference-quality playbooks. Invoked by `ls SKILLS/` and reading the relevant one when starting a task. Full list:

```
accounts-registry              data-audit-qa              non-blocking-prompt-intake       secrets
anthropic-api                  deploy-rollback            parallel-execution               security-baseline
browser-use-internals          feature-branch-worktree    platform-stewardship             session-resilience
capacity-monitoring            llm-vs-code                python-script-path-hygiene       sqlite-multi-writer
daily-reflection               long-running-jobs          remote-control-fallback          user-action-tracking
                               memory-hygiene             residential-proxy                user-info-conventions
                               multi-project-windows      root-cause-analysis
                               never-idle                 sec-xbrl-extraction
                               new-project-checklist
```

Notable ones:
- **platform-stewardship**: the meta-skill. "A problem solved once should never need to be solved again." Defines four registers of knowledge (CLAUDE.md / SKILLS / LESSONS / RUNBOOK), paired-edit review for CLAUDE.md edits (every change carries a trim), event-triggered deeper reviews.
- **data-audit-qa**: halt-fix-rerun loop for verifying number-intensive dashboards. Agents fan out to check data against primary sources; on first finding they halt gracefully; orchestrator groups by root cause and fixes upstream; audit reruns. Exits on clean pass or MAX_ITERATIONS.
- **long-running-jobs**: the systemd-run + MemoryMax + heartbeat pattern. Authored in response to silent-ingestion-death incidents.
- **session-resilience**: failure modes (remote-control stale / CLI crash / tmux killed / reboot / JSONL corruption / orchestrator death) with automatic-recovery and manual-playbook coverage.
- **llm-vs-code**: decision framework for what belongs in code vs LLM. Includes cost math and transition-moment heuristics (when LLM patterns stabilize, migrate to code).

### 5.3 LESSONS.md (`/opt/site-deploy/LESSONS.md`)
Incidents: symptom / root cause / fix / preventive rule. Builders and Reviewers read it first. Current notable entries: overnight OOM RCA, zram kernel-module gotcha.

### 5.4 RUNBOOK.md (`/opt/site-deploy/RUNBOOK.md`)
Per-project static operational facts: URLs, paths, env var names, health checks, systemd units, nginx blocks, cron entries. Recently extended with per-project "Shared-infra deps" subsections.

### 5.5 Reflections (`/opt/site-deploy/reflections/YYYY-MM-DD.md`)
Daily end-of-day reflection by the orchestrator. Template: What shipped / What broke / Patterns / External best practices / Concrete improvements / What I'd do differently / Work items. First one written 2026-04-15. Cron fires reminder at 23:00 UTC.

---

## 6. Recent major decisions (shape everything downstream)

1. **Thin CLAUDE.md refactor (2026-04-15)** — master went from 215 → 96 lines. 8 situational playbooks moved to new SKILLS files. Enforcement: paired-edit review (every CLAUDE.md edit ships with a trim of ≥1 existing section) + event-triggered sweeps. User explicitly rejected an arbitrary line-count cap in favor of quality-based review.
2. **Infra agent isolation (2026-04-16)** — orchestrator moved from `/opt/timeshare-surveillance-preview/` (a project dir it had been sitting in by accident) to `/opt/infra/` with strict allow/forbid path lists. Never edits project source; dispatches to project chats instead.
3. **CLAUDE.md ownership rule (2026-04-16)** — master is infra-owned + loaded globally; per-project CLAUDE.md (if it exists) is project-chat-owned and scope-restricted to true overrides; **cross-project harness propagation is a non-task**. This was the fix to an advisor prompt that had proposed replication.
4. **Worktree-based branches (2026-04-14)** — feature branches live in `/opt/worktrees/<project>-<slug>/` so `/opt/site-deploy/` stays on `main`. Prevents cross-project branch collisions.
5. **Project-checkin cron (2026-04-16)** — fills the gap the overnight OOM exposed: watchdog checked "is the chat alive?" but not "is the project making progress?" Now checks PROJECT_STATE freshness, idle-with-in-progress-task, and dead long-job heartbeats.
6. **zram for RAM headroom (2026-04-15)** — added 1.9 GB compressed in-memory swap, LZ4, priority 100. Bought ~800 MB effective RAM for idle-chat cold pages.
7. **Telemetry + user-action tracker (2026-04-15 / 04-14)** — `tokens.json` per-chat consumption, `skills-usage.json` per-skill access counts, `pending-actions.json` + `accounts.json` for user-tasks & third-party-service registry. Rendered at `/telemetry.html`, `/todo.html`, `/accounts.html`.

---

## 7. Pending decisions (advisor input helpful)

1. **PR #1 on csosin1/ClaudeCode** (`claude/carvana-loan-dashboard-4QMPM`, 67 unique commits).
   - Open since 2026-04-01. 2079 files changed, 218k insertions.
   - **Key finding:** `/opt/site-deploy/deploy/auto_deploy.sh` pulls this feature branch directly (not main). The deployment IS the branch. This is an architectural deviation from the standard "main = preview, promote.sh = live" pattern.
   - Options: (a) merge the branch into main to normalize (cosmetic — live deploy unaffected since auto_deploy.sh still points at branch); (b) leave as-is (the branch is effectively the production line); (c) refactor auto_deploy.sh to track main + finish-task.sh the branch.
   - Awaiting user call.

2. **Droplet migration — Option B adopted.** Plan: spin up a new prod droplet (16 GB / 8 vCPU recommended, Premium Intel, ~$128/mo), migrate apps one at a time (timeshare-surveillance first → gym-intelligence → carvana-abs → car-offers last), keep Claude + orchestration on the current droplet which becomes dev.
   - User has not yet provisioned the prod droplet.
   - SSH key for the infra agent already generated and ready (`/root/.ssh/id_ed25519`, public key visible in earlier conversation).

3. **Compliance droplet** — planned third small droplet for a future PII-handling compliance app. Architecture discussion deferred until user specifies what the app does.

4. **Cloud Resource Names** — user may want to take control of `casinvestmentpartners.com` domain from a consultant for use with the compliance app. Diagnostic info gathered: registrar is name.com, whois-redacted, expires 2026-08-01.

5. **Stale CLAUDE.md in abs-dashboard** — `/opt/abs-dashboard/CLAUDE.md` is 752 lines, 719 of which don't match current master (it's a fork of an older master, not project-specific overrides). Cleanup dispatched to carvana-abs-2 with diff-first discipline: surface valuable content missing from master (so infra can promote to master) before deleting. Status: dispatched, in progress.

6. **Long-running-jobs migration for carmax ingestion** — the ingestion that OOM'd last night is still launched via `nohup &` rather than `systemd-run` per the skill. Carvana-abs-2 owns the migration.

---

## 8. Known quirks / gotchas

1. **abs-dashboard deploys from feature branch, not main.** See item 1 above. Any architecture proposal involving "standardize on main-only deploys" has to account for this or change it explicitly.
2. **abs-dashboard is a second checkout of the same repo.** `/opt/abs-dashboard/` clones `csosin1/ClaudeCode` at the Carvana-dashboard feature branch; `/opt/site-deploy/` is the canonical clone at main. Both paths can exist in git-diff-land at the same time; when committing from infra, always use `git -C /opt/site-deploy` explicitly.
3. **`/opt/timeshare-surveillance-preview/` is a deploy target, not a git repo.** Auto-deploy writes into it. Editing files there is lost on next deploy. This was the root of the "orchestrator drifted into a project dir" issue.
4. **GitHub default branch appears to be set to a feature branch** (e.g., `claude/banana-target-game-Nr0fL`, which refused deletion because it's `origin/HEAD`). Should probably be `main`; cosmetic DO-console fix.
5. **Claude Max plan rate limits, not API billing.** Telemetry `/tokens.json` shows "API-equivalent cost" — useful for prioritizing LLM-to-code migrations but NOT the user's Anthropic bill, which is flat $200/mo.
6. **The zram kernel module isn't in stock DO Ubuntu 22.04.** Requires `apt install linux-modules-extra-$(uname -r)`. LESSONS.md entry covers this.
7. **Remote-control URL can go stale silently** — the underlying CLI process stays alive but the Anthropic relay binding dies. Watchdog auto-detects + calls `reactivate-remote.sh`; user just re-taps the stable bookmark.
8. **When respawning a chat after OOM, the resumed chat may not realize its background processes died.** Fixed by updating `claude-project.sh` post-spawn prompt to require `ps` verification of prior background work.

---

## 9. Operational tooling reference

**CLIs (`/usr/local/bin/`, all wrapped by helpers versioned at `/opt/site-deploy/helpers/`):**

| Tool | Purpose |
|---|---|
| `claude-project.sh <project> <cwd>` | spawn a chat window |
| `end-project.sh <project>` | close a chat window (refuses without PROJECT_STATE update) |
| `reactivate-remote.sh <project>` | re-issue `/remote-control` on a stale window |
| `start-task.sh <project> "<desc>"` | create feature branch + worktree |
| `finish-task.sh <project>` | merge feature branch + cleanup worktree |
| `user-action.sh add/list/remind/done/cancel` | pending user-task tracker |
| `account.sh add/list/show/cancel` | accounts/subscriptions registry |
| `task-status.sh set/done/clear` | per-project dashboard status |
| `notify.sh "msg" "title" priority "url"` | iPhone push via ntfy |
| `projects-smoketest.sh [report\|gate]` | hits every project URL, 200 check |
| `branch-audit.sh` | weekly stale/behind-branch report |
| `capacity-check.sh` | writes capacity.json + threshold notifies |
| `claude-watchdog.sh` | per-minute chat-health scan |
| `claude-respawn.sh` | respawn missing chat windows |
| `project-checkin.sh` | per-30-min project-progress check |
| `chat-telemetry.py` | per-chat tokens + per-skill usage |

**Cron schedule (`/etc/cron.d/claude-ops`):**
```
* * * * *       claude-watchdog.sh        (every minute)
*/5 * * * *     claude-respawn.sh         (every 5 min)
*/5 * * * *     capacity-check.sh         (every 5 min)
*/30 * * * *    chat-telemetry.py         (every 30 min)
*/30 * * * *    project-checkin.sh        (every 30 min)
0 9 * * 1       branch-audit.sh           (Mondays 09:00 UTC)
17 * * * *      projects-smoketest.sh     (every hour, report-only)
0 23 * * *      daily reflection reminder (23:00 UTC)
```

**Mobile-visible dashboards (all at `https://casinv.dev/*.html`):**
- `/projects.html` — per-project cards with live/preview/remote-control links, liveness badge, counter for pending todos, usage badge
- `/capacity.html` — RAM/swap/disk/load with severity banner
- `/todo.html` — pending user actions
- `/accounts.html` — third-party subscriptions with monthly total
- `/telemetry.html` — per-chat token intensity + per-skill usage
- `/jobs.html` — long-running job heartbeats (when jobs are registered)
- `/liveness.json` / `/capacity.json` / `/tokens.json` etc. — underlying JSON

---

## 10. Costs + business context

- **Anthropic:** $200/mo (Claude Max, flat). User explicitly wants this fixed.
- **DigitalOcean:** $32/mo (current droplet). Option B adds a new ~$128/mo prod droplet and later a ~$16/mo compliance droplet.
- **GitHub:** repo at `csosin1/ClaudeCode` — free tier, `GH_TOKEN` configured as env var on the droplet.
- **Domains:** `casinv.dev` (active, primary for dashboards); `casinvestmentpartners.com` (held by a consultant — user wants control; see pending decision #4).
- **Third-party:** Decodo residential proxy (~$150/mo, used by car-offers).
- **Rough expected total after migration:** $32 + $128 + $16 + $150 + ~$200 = ~$525/mo.

---

## 11. Where to find things

```
/opt/site-deploy/                       master repo (csosin1/ClaudeCode main)
├── CLAUDE.md                           master behavioral rules (96 lines)
├── LESSONS.md                          incidents + RCAs
├── RUNBOOK.md                          per-project operational facts
├── ADVISOR_CONTEXT.md                  ← this file
├── SKILLS/                             28 reusable playbooks
├── reflections/                        daily reflection files
├── helpers/                            versioned copies of /usr/local/bin tooling
├── deploy/                             deploy scripts + landing pages
└── <project>/                          per-project source (e.g., carvana_abs/, car-offers/)

/opt/infra/                             infra-agent home
├── CLAUDE.md                           scope-narrowed rules
├── PROJECT_STATE.md                    dynamic state
└── README.md                           narrative

/opt/<project>/                         deploy targets + project working dirs
/opt/worktrees/<project>-<slug>/        feature-branch worktrees

/etc/claude-projects.conf               expected-chat-windows registry
/etc/cron.d/claude-ops                  all platform cron entries
/etc/systemd/system/claude-*.service    tmux + respawn services

/var/www/landing/                       published dashboards + JSON
/var/run/claude-sessions/               watchdog/respawn state files
/root/.claude/projects/                 Claude Code JSONL conversation histories (per project)
/root/.ssh/id_ed25519                   infra-agent SSH key (public part added to DO as "claude-orchestrator@dev-droplet-2026-04-15")
```

**Live URLs to poke at for current state:**
- https://casinv.dev/projects.html — dashboard index with live state
- https://casinv.dev/capacity.json — current capacity
- https://casinv.dev/liveness.json — per-chat status
- https://casinv.dev/tokens.json — per-chat token intensity
- https://casinv.dev/pending-actions.json — user's todo list
- https://casinv.dev/accounts.json — subscriptions registry
- https://github.com/csosin1/ClaudeCode — repo (main + feature branches)
- https://github.com/csosin1/ClaudeCode/tree/main/SKILLS — all skills
- https://github.com/csosin1/ClaudeCode/tree/main/reflections — daily reflections

---

## 12. How to give advice here without stepping on things

- **Route advice through the user or the infra agent.** Don't try to dispatch directly to project chats — they're busy with their own work and context-switching is expensive.
- **The user likes concrete recommendations, not menus.** "Do X because Y" beats "Here are five options, which do you prefer?"
- **Respect the thin-CLAUDE.md invariant.** Any proposal that adds a CLAUDE.md section should also identify what moves to SKILLS, or better yet: suggest the whole thing as a SKILLS file with no CLAUDE.md pointer.
- **Respect project isolation.** Proposals that would require the infra agent to edit project source, or require one project to touch another's files, will be rejected on principle.
- **Grounded beats clever.** The user caught two prior cases where an advisor proposed replication patterns or governance that didn't fit the platform. Always check: does this fit our current architecture? If not, say so explicitly.
- **Token cost is a real signal** — even though it's not billed per-token, it's a proxy for LLM-dependency that we're trying to reduce. Proposals that add LLM calls should justify why they can't be code.

---

_This document is a snapshot. For current state, read the files under `/opt/site-deploy/` and query the live endpoints. Anything stated here may be stale within a day — check before acting on it._
```

=============================================================================
## 7. REFLECTIONS
=============================================================================

### /opt/site-deploy/reflections/2026-04-15.md

```markdown
# Daily Reflection — 2026-04-15

_Authored by orchestrator (timeshare-surveillance window) after a ~30-hour session that spanned 2026-04-14 → 2026-04-15._

## What shipped

**Platform rules & skills (highest leverage work of the day):**
- CLAUDE.md refactor: 215 → 100 lines (later 103). 8 situational sections relocated to new SKILLS files; no rules removed.
- 20 SKILLS files now exist, up from 3 at start of session. New ones: `platform-stewardship`, `parallel-execution`, `non-blocking-prompt-intake`, `root-cause-analysis`, `session-resilience`, `data-audit-qa`, `memory-hygiene`, `capacity-monitoring`, `user-action-tracking`, `accounts-registry`, `long-running-jobs` (by carvana-abs-2), `llm-vs-code`, `new-project-checklist`, `deploy-rollback`, `secrets`, `security-baseline`, `multi-project-windows`, `remote-control-fallback`, `feature-branch-worktree`, `user-info-conventions`.
- CLAUDE.md rules codified today: Challenge the Approach, Parallel Execution, Non-Blocking Prompt Intake, Platform Stewardship, Skills Registry (search/use/contribute), Restore-Then-RCA, User Actions & Accounts, Capacity Awareness, Session Resilience, Memory Hygiene, Data Audit & QA (halt-fix-rerun loop), LLMs for Judgment / Code for Computation.

**Infrastructure:**
- Watchdog extended to detect stale remote-control and auto-reactivate (`reactivate-remote.sh`). Escalating-notify on 3 consecutive failures.
- Respawn cron + `claude-respawn-boot.service` for post-reboot chat recovery.
- Capacity monitor + `/capacity.html` dashboard with severity banner, threshold-based notify, debouncing.
- `user-action.sh` + `account.sh` + `/todo.html` + `/accounts.html` — user-action tracker and subscriptions registry.
- Feature-branch workflow moved to git worktrees (`/opt/worktrees/<project>-<slug>`) so shared `/opt/site-deploy` stays on main.
- Liveness badges on `/projects.html` (busy / idle / stuck / archived + activity + elapsed).
- Paired-edit review mechanism for CLAUDE.md (replaces arbitrary line cap).

**Project-level:**
- Carvana Loan Dashboard context handoff: original `carvana-abs` window lost remote-control silently while background ingestion kept running; killed that window, spawned `carvana-abs-2` with `claude --continue` resuming from the original 8 MB JSONL — full history preserved, not summarized. `claude-projects.conf` and projects.html updated.
- Memory hygiene passes shipped material wins: RAM 91% → 54%, swap 99% → 69%, disk 82% → 47%. Car-offers cleaned 11 orphan Xvfb displays + 16 stale Playwright profile dirs. Carvana chat gzipped ~360 MB of SEC filing HTML cache.
- Car-offers confirmed Carvana's finalize page is a Turnstile-blocked hard wall; CapSolver integration committed, gated on user-action for API key.

## What broke or degraded (incidents worth RCA)

1. **Carvana remote-control died silently.** Tmux + Python ingestion (PID 365790) kept running; user's phone bookmark pointed at a dead session URL for unclear duration. Watchdog didn't notice because it checked for missing tmux, not missing remote-control binding. **Root cause:** watchdog's mental model of "alive" was incomplete. **Fix shipped:** `reactivate-remote.sh` + watchdog extension now auto-reactivates. Preventive rule in `SKILLS/session-resilience.md`.

2. **Droplet thrashing from 91% RAM / 100% swap for hours** before anyone noticed. Orchestration felt sluggish; token burn was artificially suppressed by I/O waits. **Root cause:** no capacity monitor existed until ~02:00 UTC today. **Fix shipped:** `capacity-check.sh` cron + notify thresholds. **Preventive:** CLAUDE.md "Capacity Awareness" rule requires checking `/capacity.html` before heavy work.

3. **Ingestion job failed silently earlier in the day** — user discovered only this morning, losing hours. **Root cause:** ingestion was launched as `nohup ... &` with no heartbeat or external monitor. **Fix shipped:** `SKILLS/long-running-jobs.md` prescribes systemd-run + `MemoryMax` + heartbeat-file + watchdog cron. **Open gap:** existing running ingestions haven't been migrated to the new pattern yet. Migration task for carvana-abs-2.

4. **Carvana chat was "unresponsive" for 18 min** with 2 queued user messages while 3 parallel subagents ran. **Root cause:** main thread blocked waiting on in-flight subagents — no non-blocking intake discipline. **Fix shipped:** `SKILLS/non-blocking-prompt-intake.md` + CLAUDE.md rule. Main thread is now explicitly a coordinator.

5. **Cross-chat branch collision** — car-offers chat left `/opt/site-deploy` on a feature branch; subsequent commits from this chat landed there instead of main, required cherry-pick to recover. **Root cause:** shared git checkout. **Fix shipped:** feature-branch workflow migrated to git worktrees so shared repo stays on main.

6. **CLAUDE.md bloated silently** to 215 lines over the session. User caught it, not the orchestrator. **Root cause:** default-to-CLAUDE.md instinct + no enforcement + add-never-subtract culture. **Fix shipped:** paired-edit review + pointer parsimony + event-triggered sweeps in `SKILLS/platform-stewardship.md`.

## Patterns I'm noticing

- **Reactive resilience.** Every resilience mechanism shipped today was in response to a visible failure. The platform isn't broken but it learns through failure. We could go proactive: chaos-kill a chat per week, assert recovery, find the gap before the user does.

- **Orchestrator as attention bottleneck.** All user prompts land here; I dispatch; responses funnel back. If this chat dies, nothing routes until respawn. Alternative model: project chats independently subscribe to user-action/task queues; orchestrator is a coordinator, not a gatekeeper. Worth exploring when the load justifies it.

- **Skills accumulate faster than they get used.** 20 SKILLS at end of day vs. 3 at start. Most have been referenced once by their author and never again. Unknown whether agents are actually consulting `ls SKILLS/*.md` at task start or relying on memory. We have no telemetry. Could add a simple log (stat access times; grep history) to see which skills earn their keep.

- **Long-running jobs are still fragile.** Even after shipping `SKILLS/long-running-jobs.md`, the migration from `nohup &` to `systemd-run` hasn't happened for the ingestion that motivated the skill. Knowing the pattern and applying it are different problems. Existing jobs need explicit retrofit.

- **The user-actions queue is a real discovery.** 13 pending actions visible at once; most are car-offers credential signups. Without the queue, these were invisible and chats assumed them complete. Already paid for itself.

- **Compound stewardship is working.** Carvana-abs-2 independently wrote `SKILLS/long-running-jobs.md` in response to the same incident I was about to write it for. Multiple chats shipping skills without explicit direction is the stewardship rule working as intended.

## External best practices worth considering

Researched quickly against what I know of industry SRE / agent-orchestration patterns — candidates for adoption:

- **Error budgets per project.** Declare "< 5 min of downtime per project per month is acceptable." Track against it. Makes resilience investment prioritizable (which project burns its budget fastest?). Would give a principled basis for "worth upgrading" vs "not worth it."
- **Chaos engineering / game days.** Periodically + deliberately kill things (a chat, the droplet, a cron) to verify recovery. Netflix's Chaos Monkey pattern, sized for our scale. Cost: ~1 hr/month of agent time. Benefit: finds gaps before the user does.
- **Runbook per alert type.** Every `notify.sh urgent` ships with a one-page `SKILLS/runbook-<alert>.md` explaining what to check, what to fix, escalation path. Today many alerts are "X is wrong — good luck." Runbooks make the alert actionable.
- **Architecture Decision Records (ADR).** Lightweight "we chose X because Y in situation Z" records. Currently decisions are scattered across CLAUDE.md, SKILLS, LESSONS, PROJECT_STATE. ADR would centralize the "why we're doing it this way" for future agents. Probably overkill for our scale but worth considering.
- **Service-level objectives on the user's actual experience.** Not "droplet uptime" but "time-from-user-prompt-to-first-agent-response." Would have caught the 18-min "canoodling" failure faster than infrastructure metrics did.
- **Cost-per-task budgets with automatic escalation.** `task-status.sh done` already includes a token tally; CLAUDE.md already has a 200k-token guardrail; we don't enforce or track it. Next step: per-project budget declared up front, warning at 50%, auto-halt-and-notify at 100%.

## Concrete improvements to propose (ranked by leverage)

1. **Chaos-kill weekly cron.** `/usr/local/bin/chaos-kill.sh` picks one random project chat (never orchestrator) during business hours, kills its tmux window, measures recovery time, notifies with result. One commit. ~45 min of work. High confidence this surfaces at least one bug within the first month. *Leverage: high, effort: low.*

2. **Per-chat daily token meter.** Extend watchdog to read each JSONL's size delta over 24h. Publish to `liveness.json` as `tokens_today` per chat. Surface on `/projects.html`. Makes cost pattern visible. Motivates the LLM-vs-code migrations. *Leverage: medium, effort: medium.*

3. **Skills-usage telemetry.** Log every `Read`/`Grep` tool call against `/opt/site-deploy/SKILLS/*.md` across all chats. Weekly report: which SKILLS were actually consulted, which are dead letters. Dead ones become candidates for pruning. *Leverage: medium, effort: low. Requires hook into tool calls.*

4. **Runbooks for every urgent-priority alert type.** Audit current notify.sh call sites; ensure each has a `click` URL pointing to a `SKILLS/runbook-*.md` with concrete recovery steps. Today the click URLs go to dashboards, which often don't tell you what to *do*. *Leverage: high when alerts fire, effort: medium (~10 alert types to write up).*

5. **User-visible daily digest.** `/digest.html` auto-generated from the day's site-deploy commits + major notify.sh events. User taps once, sees "here's what happened overnight." Complements the reflection (which is for agents). *Leverage: medium, effort: medium.*

6. **Retrofit existing long-running jobs to the long-running-jobs skill pattern.** Concretely: the current `carmax_abs.run_ingestion` should be wrapped in `systemd-run` with `MemoryMax`, write heartbeat, be under watchdog. Task for carvana-abs-2. *Leverage: high when it saves the next silent failure, effort: low per job.*

## What I'd do differently if today restarted

- **Start with the reflection discipline.** Having this file framework at 8am would have shaped the day — every new rule / skill proposal passes through "does this solve a real observed failure, or am I pattern-matching?"
- **Batch the CLAUDE.md rule additions instead of trickling.** I added ~10 new CLAUDE.md rules across ~15 commits today. Each commit was well-scoped, but the cumulative effect was the bloat the user caught at night. A rule-addition pass followed by a doc-review pass would have caught it sooner.
- **Invest in telemetry earlier.** We now have capacity, liveness, tasks, pending actions, accounts. We don't yet have token-per-chat or skill-usage. The earlier we have data, the earlier decisions are evidence-based rather than vibes-based.

## Rule / skill proposals graduating to work items

- Write `SKILLS/daily-reflection.md` (playbook for this practice, shipping today).
- `/usr/local/bin/chaos-kill.sh` + weekly cron (new).
- Retrofit `carmax_abs.run_ingestion` under `systemd-run` per `long-running-jobs.md` (task for carvana-abs-2).
- Add per-chat token meter to watchdog (extension).
- Audit notify.sh alerts and ensure each has a linked runbook.

---

_Next reflection: 2026-04-16 evening. If something material changes before then — an incident, a rule-shift, a user ask that exposes new structure — reflect on it then, don't wait._
```

=============================================================================
## 8. PROJECT_STATE files (per project)
=============================================================================

### /opt/infra/PROJECT_STATE.md

```markdown
# Infra Orchestrator — Project State

_Last updated: 2026-04-16 (session restart ack) by infra agent_

## Current focus
Preparing the platform for Option-B migration: move apps (timeshare-surveillance, gym-intelligence, carvana-abs, car-offers) to a new prod droplet; keep Claude + orchestration on the current droplet. Scope-narrowing infra agent to `/opt/infra/` with strict CLAUDE.md.

## Last decisions
- Dev/prod split will happen per Option B. Stable apps migrate first; car-offers last.
- Infra agent now lives at `/opt/infra/` with strict scope (SKILLS / CLAUDE.md / helpers / deploy scripts / cron / nginx / systemd only — never project source).
- tmux window will rename from `timeshare-surveillance` to `infra` on next respawn. `/etc/claude-projects.conf` updated to reflect the new identity.
- Project chats have been asked to prep for migration: commit pending work, finalize PROJECT_STATE, inventory background processes and systemd/nginx/cron dependencies, gracefully halt subagents.

## Open questions
- PR #1 (Carvana, 67 unique commits on `claude/carvana-loan-dashboard-4QMPM`): auto_deploy.sh pulls that branch, not main. Merge-to-main would be cosmetic but would normalize the arrangement. **Awaiting user decision.**
- New prod droplet: size TBD (recommend 8 vCPU / 16 GB Premium Intel, ~$128/mo); creation is a user action on DO console.
- Droplet shutdown / infra changes: user considering; will happen before migration executes.
- Compliance droplet (third box for PII app): deferred; architecture discussion ongoing.

## Next step
Once user confirms the infra-agent setup and the project chats ack migration-prep, either (a) proceed with droplet shutdown/resize as user plans, or (b) spin up new prod droplet and start timeshare-surveillance pilot migration. Whichever comes first.

## Known state
- Orchestrator now lives in tmux window `infra` (window #9); rename transition complete. Bookmark `casinv.dev/remote/infra.html` exists.
- Leftover tmux window `timeshare-surveillance` (window #3) still present but not in `/etc/claude-projects.conf`. Retirement is a user decision per infra CLAUDE.md — not acted on.
- No background processes owned by this chat (orchestrator only; no daemons, no subagents running).
- No in-flight work; all prior commits pushed to `/opt/site-deploy` main.
```

### /opt/car-offers/PROJECT_STATE.md

```markdown
# Car Offers — Project State

_Last updated: 2026-04-16 ~06:30 UTC — idle, blocked on 3 user-actions._

## Current focus
Idle. All hypothesis-testing complete. CarMax works (6 offers in DB). Carvana and Driveway blocked on infrastructure the user needs to set up. No active processes.

## Last decisions (carried from 2026-04-14 session)
- **CarMax is solved.** LLM-nav + deterministic wizard both produce real offers. 3 outcome types observed: firm offer, estimate-range, deferred-to-email.
- **Carvana Turnstile ~50% auto-resolve** via H2 (warmup + 60s dwell on finalize). But email validation rejects all non-existent persona emails, and backend returns "couldn't value" for some VINs even when Turnstile clears. Needs: (1) **CapSolver** for reliable Turnstile ($10 prepay, ua-12d7d9f0), (2) **real email domain** for SMTP-validated persona addresses (ua-3be8cf33).
- **Driveway structurally blocked** at fingerprint layer (Whoops modal on VIN submit). All 6 hypotheses tested (warmup, buyer-first, sign-in-path, mobile-UA, Google-referrer, dwell) — none bypassed it. Needs: **Browserbase** cloud browser ($10 prepay) or alternative stealth stack.
- **Mid-flight LLM swap** built and merged (commit 4ac9964). `--model-early` / `--model-late` / `--llm-switch-at-step` flags on run_site.py.
- **offers.db journal_mode=DELETE** permanently (commit 448190d). No more WAL-race wipes. 10-min backup cron at `/opt/car-offers-data/db-backups/`.

## Open questions
- H7 test (example.com email) cleared Turnstile but backend still said "couldn't value" the 2023 Nissan Rogue. Either Carvana genuinely can't value via automated submissions from our stealth profile, or there's a secondary risk-score signal we haven't identified.
- Whether CapSolver alone is sufficient or we also need real persona emails to get past both walls simultaneously.

## Next step
Waiting on user to complete any of these user-actions (prioritized):
1. `ua-12d7d9f0` — CapSolver signup + API key (10 min, $10, unblocks Carvana Turnstile)
2. `ua-3be8cf33` — Persona email domain (15 min, $12/yr, unblocks Carvana email validation)
3. Browserbase signup (10 min, $10, unblocks Driveway)

Once ANY arrives, I wire it in (~15 min) and resume hypothesis testing.

## Memory hygiene 2026-04-14
- **Found:** 11 orphan Xvfb displays (:100–:110, ~120 MB RAM residual), 16 stale llm-nav Chromium profile dirs (~700 MB disk, ~200 MB page-cache RAM), 2 MB of uncompressed old run logs, DB not VACUUMed, backup dir had 8 files (well under any threshold).
- **Shipped:** killed all :100–:110 Xvfbs, purged `car-offers/llm-nav/profiles/` (consumer profiles at `/opt/car-offers-preview/.chrome-profiles/` untouched), gzipped logs >1MB older than 30 min, VACUUM + PRAGMA wal_checkpoint + PRAGMA optimize on `offers.db`, dropped kernel page cache. **Before: RAM 82.7% / swap 93% / urgent. After: RAM 63.5% / swap 49.6% / warn.** ~1 GB of swap reclaimed; 700 MB disk.
- **Deferred (not my scope):** top CPU consumer is `abs-dashboard/cmx_reparse.py` at 79% — belongs to carvana-abs project, not car-offers.

## Current focus
Resize aborted by user; work resumes on the 4GB droplet. CapSolver integration module written + committed (commit 50722b3 on main) — ready to wire into LLM-nav the moment the API key is provided. Root finding: **Carvana Turnstile is a hard wall**, 3 independent runs all completed every wizard step and got stuck on the finalize-page challenge that never auto-resolves in 120s. No amount of behavioral tuning beats it without a solver. User-action `ua-12d7d9f0` filed for CapSolver signup.

## Last decisions (this session)
- **LLM-nav via browser-use + Claude Sonnet 4.5** is the established mechanism for cracking unknown site flows. Harness at `/opt/site-deploy/car-offers/llm-nav/run_site.py`, committed to branch `claude/car-offers-llm-nav-harness`.
- **CarMax has 3 real outcomes**, all observed: `ok` (firm dollar amount), `estimate_range` (CarMax wants photos, gives range), `deferred_offer` (CarMax promises to email the offer later). Deterministic wizard at `/opt/site-deploy/car-offers/lib/carmax.js` now polls 90s for late-hydrating SPA and handles all 3 outcomes (commit 5858823, merged to main + deployed preview).
- **offers.db persistence fixed permanently** — commit 448190d switched `journal_mode = DELETE` + `synchronous = FULL`. LESSONS.md + SKILLS/sqlite-multi-writer.md document the RCA (WAL race across multiple writers). Also a 10-min backup cron at `/opt/car-offers-data/db-backups/`.
- **Panel rebuilt with real VINs from `data/kmx_vins.xlsx`** — 29 consumers, none fabricated. Zip spread NE / South / Midwest / West / Mountain.
- **VIN enrichment pipeline** works: NHTSA vPIC full decode + Recalls + EPA MPG + DDG search, cached per VIN at `llm-nav/enrichment/<vin>.json`. First 12 VINs enriched; 17 new panel members enrichment was running pre-resize (check `logs/enrich-wave2.log` status on resume).
- **Persona bios deepened** — `run_site.py`'s PERSONAS dict now has full name / email / phone / DOB / street / DL state+number / employment / years-at-address per zip. Phone numbers are NANP-fictional until Twilio is provisioned.
- **Capacity rule adopted** — the 4 Carvana runs in flight at shutdown drove capacity to `urgent` (swap 93%). The 16GB resize is the fix; user-action `ua-2ecb0630` filed.

## Open questions
- **Carvana finalize block** — known from the first Consumer 1 attempt to be (a) email validation rejecting `caroffers.tool@gmail.com` and (b) Cloudflare Turnstile escalating when the agent clicks the checkbox. Current retry prompts use realistic persona emails (`catherine.b.smith@gmail.com` style) + explicit no-click-Turnstile rule. Also AutoCheck mileage mismatch caused validation error for Consumer 2 (seeded 73648, AutoCheck says 92412). Consumer 1 mileage locked at AutoCheck truth (60624). 4 Carvana retries were in flight when killed at shutdown. Relaunch after resize.
- **Driveway structural block** — confirmed fingerprint-level (same Whoops modal across 3 different consumers + IPs + VINs). Next step likely Prolific baseline (~$50, needs user's Prolific token still pending) OR Browserbase cloud browser.
- **Deferred-offer flow on CarMax** — 3 of 6 CarMax runs ended in deferred (CarMax asks to email offer). Not a bug, real market behavior. Logged correctly in DB as `status=deferred_offer`.
- **Real emails not yet set up** — user is unavailable to do Cloudflare DNS or AWS Route 53 domain registration. `SKILLS/persona-email.md` lays out the path. mail.tm fallback available but untested against Carvana's blacklist.

## Next step after resize + resume
1. Verify all 6 offers still in DB (backup at `/opt/car-offers-data/db-backups/offers-backup-*.db` if needed).
2. Re-launch Carvana retries on consumers 1, 2, 3, 5 (profiles still aged; IPs sticky).
3. In parallel: fire CarMax on consumers 7–29 using the deterministic `/api/carmax` endpoint (not LLM-nav — we have the wizard working). Should complete all ~23 in ~45 min with 8-10 concurrent on the beefier droplet.
4. Enrich any still-pending VINs; tail `llm-nav/logs/enrich-wave2.log` to confirm all 29 done.
5. Drive the user-actions list as credentials land.

---

## Reference (survives across sessions)

### Panel (29 consumers, all real VINs from `data/kmx_vins.xlsx`)
Consumers 1–12 documented in the consumers table of `/opt/car-offers-preview/offers.db`. 13–29 added this session from spreadsheet rows 2019–2023 years, stratified.

### Offers captured so far
| ID | VIN | Site | Status | $ |
|---|---|---|---|---|
| 1 | 5LMCJ2C94KUL47822 (2019 Lincoln MKC) | carmax | ok | **$8,600** |
| 2 | 5N1AZ2CJ2PC122146 (2023 Nissan Murano) | carmax | deferred | — |
| 3 | 1HGCV2F9XNA008352 (2022 Honda Accord) | carmax | ok | **$25,200** |
| 4 | JA4AZ3A34LZ021352 (2020 Mitsubishi Outlander) | carmax | range | $6,334–11,200 (mid $8,767) |
| 5 | 1C4JJXP66NW280595 (2022 Jeep Wrangler 4xe) | carmax | deferred | — |
| 6 | 5N1BT3ABXPC880615 (2023 Nissan Rogue) | carmax | deferred | — |

### Key URLs
- **Preview:** https://casinv.dev/car-offers/preview/
- **Panel UI:** /car-offers/preview/panel
- **Compare UI:** /car-offers/preview/compare
- **Debug gallery:** /car-offers/preview/debug/
- **Setup page:** /car-offers/preview/setup
- **Capacity:** https://casinv.dev/capacity.json + /capacity.html
- **Todo:** https://casinv.dev/todo.html

### Branches
- `main` (8c84143 → 819fdac current) — stable deploy target.
- `claude/car-offers-llm-nav-harness` — WIP pushed pre-resize; contains llm-nav harness + vin_enrich + knowledge files + 2 SKILLS docs.
- `claude/car-offers-humanloop-clients` (99d35a5) — still awaiting merge (morning decision).
- `claude/car-offers-wizards-from-debug` (f10f846) — Builder A's wizard rebuild; CarMax `#ico-continue-button` fix is already on main from the 5858823 polling commit.

### Live-action user items
Use `user-action.sh remind` for the full list. 9 items pending including MTurk funding, Prolific token paste, Twilio, Route 53 domain, and the droplet resize that's happening right now.
```

### /opt/gym-intelligence/PROJECT_STATE.md

```markdown
# gym-intelligence — Project State

_Last updated: 2026-04-13 by gym-intelligence session_

## Current focus
Idle. Last completed work (2026-04-12): added `MIN_LOCATIONS_FOR_CLASSIFICATION = 4` floor to `classify.py` (commit c412728) so refreshes only spend Claude tokens on chains that actually move Basic-Fit's competitive landscape, not the ~31k OSM single-location noise.

## Last decisions
- **Classification floor = 4 locations.** Pre-floor, the classifier matched all ~31k unclassified chains per refresh (~$220, 17+ hrs). Floor of 4 covers ~22% of clubs across 391 chains for ~$3. Set in `classify.py:19`.
- **Flask + vanilla JS, not Streamlit.** Mobile-first single-page dashboard at `/gym-intelligence/`. Streamlit was replaced (commit ee243ee) for fast iPhone loads.
- **Preview-first deploy retrofit.** Live (port 8502) and preview (port 8503) are separate systemd units sharing source from `/opt/site-deploy/gym-intelligence/`; live is only updated via `deploy/promote.sh gym-intelligence`.

## Open questions
- **145 chains with ≥4 locations remain `competitive_classification = 'unknown'`.** Did the prior pass leave them unknown because Claude couldn't decide, or because the run was interrupted? Re-run on these specific IDs would be cheap (<$0.50) before deciding whether to widen the prompt or mark them manually.
- **Preview is drifted from source.** Source `classify.py` (Apr 13, has the floor) hasn't been rsynced to `/opt/gym-intelligence-preview/classify.py` (still Apr 6 content) — no `gym-intelligence.sh` deploy has run since 2026-04-12 19:30 per `/var/log/general-deploy.log`. Looks like an auto-deploy infra issue (deployed `/opt/auto_deploy_general.sh` is older than the repo copy). Out of scope for this project chat to fix; flagged in CHANGES.md.

## Next step
Await user request. If they ask to act on the preview drift, run `REPO_DIR=/opt/site-deploy LOG=/tmp/gym-deploy.log bash /opt/site-deploy/deploy/gym-intelligence.sh` to manually sync preview, then verify  http://159.223.127.125/gym-intelligence/preview/  serves the new code.
```

### /opt/abs-dashboard/PROJECT_STATE.md

```markdown
# Carvana Loan Dashboard — Project State

_Last updated: 2026-04-14 (pre-resize checkpoint)_

## Current focus
**All 9 audit items resolved — data trusted and live.** Full audit per SKILLS/data-audit-qa.md completed 3 iterations to clean-pass. Post-fix audit (1,395-tuple sample + 3-cell spot-check) reconfirmed data trusted after display changes landed. Live dashboard regenerated + promoted with all fixes. Fix commits:
- `bc40ba5` Carvana parser (reserve row + early-cycle)
- `84a7ebb` CarMax parser (tranche class-name + Ending Balance reserve)
- `1037f00` lex-date sort (dist_date_iso column + 11 query rewrites)
- `346ec51` CarMax 2025-2 re-ingest (PK-collision from stale issuer header)
- `0413c62` dashboard renderer (CarMax Notes & OC tab + restatement flag + DQ tail suppression)
- `1a91324` post-fix audit report

**PK-collision follow-up: RESOLVED** (`40b815d`). Both parsers now resolve (deal, distribution_date) PK collisions explicitly: amendments win over plain filings, later filing_date wins ties, and a 30-day stale-header guard skips writes when extracted distribution_date disagrees egregiously with filing_date. All 26 orphan filings re-ingested: **26 → 0**. Collision decisions logged to `<issuer>_abs/db/ingestion_decisions.log` for future audit. No regressions detected.

**All prior data issues closed.** Data trusted, live dashboard updated, 7 commits of fixes in this session.

**HALTED for infra migration (shutdown-safe).** Markov process killed at user's request pending infra work. No in-flight compute; all code pushed.

**State snapshot when paused:**
- CarMax loan-level: 37/37 deals, 3.1M loans. Audit clean. F-019 fixed (2019-3 loan_loss_summary recomputed).
- Deal_terms: 65/67 deals extracted. Audit: 4 parser bugs fixed (a175004). 2021-N1 $40B bug corrected, DQ triggers extracted, note structures cleaned.
- Markov: code committed (30e3546), last run OOM'd mid-forecast after 25 of 53 deals. Fix applied: offload all_latest dict to disk (temp SQLite) during forecast phase so RAM stays < 500 MB. **NOT YET VERIFIED E2E** — process killed before completing with the fix.
- Residual-economics tab: LIVE with logistic-regression placeholders (commit 54a3556). Will auto-upgrade to real Markov forecasts when deal_forecasts table is populated on next regen.
- Dashboard DBs and live site reflect everything EXCEPT the Markov forecasts.

**Resume playbook (post-infra):**
1. `cd /opt/abs-dashboard && nohup /opt/abs-venv/bin/python unified_markov.py > /var/log/abs-dashboard/markov_run.log 2>&1 &` — relaunch Markov (idempotent: rebuilds from DB).
2. Wait ~3hr (training ~80min + offload 2min + forecasts ~90min + save 2min).
3. Re-export dashboard DBs: `/opt/abs-venv/bin/python -m carvana_abs.export_dashboard_db && /opt/abs-venv/bin/python -m carmax_abs.export_dashboard_db`
4. Regenerate + promote: `/opt/abs-venv/bin/python carvana_abs/generate_preview.py && /opt/abs-venv/bin/python carvana_abs/generate_preview.py promote`
5. Dispatch final QA audit (MAX_ITER=10).
## Memory hygiene 2026-04-14
Found 2 wins: (1) `export_dashboard_db.py` in both issuers materialized 417k-row `loans` table via `fetchall()` → converted to chunked cursor iteration (10k/batch). Peak RSS on export dropped to ~38MB. (2) WAL checkpoint on both 3GB source DBs — already clean (0 frames). Deferred as separate tasks: `.copy()` chains in `generate_dashboard.py` (intentional chart-data isolation, needs careful audit); `pd.read_sql_query` full-table load in `default_model.py:206` (417k-row loan frame — chunksize conversion is a small refactor, not hygiene); no `lru_cache` anywhere (cache-layer add, out of scope).

## Last decisions
- **Deal-weighted Markov training** + Bayesian log-normal conjugate calibration shipped for Carvana (commit `8e5e5f1` on branch `claude/carvana-loan-dashboard-4QMPM`, plus `8c84143` for Bayesian). Vintage-blind baseline; vintage effect emerges through calibration overlay.
- **CarMax pool-level parser fully label-anchored** (handles 2014-era, 2017-era, 2024-era variants + late-period format drift). Pool-level reparse hit 100% `cumulative_net_losses` coverage (was 7% before). Pending commit in this checkpoint.
- **CarMax ABS-EE linker** now handles `cart<deal>.xml` naming convention (Carvana uses `ex102-*.xml`).
- **Halt rule for capacity**: when `casinv.dev/capacity.json .overall == urgent`, stop adding load, notify. Today's capacity hit "urgent" (swap 93% — other-project pressure, not mine) so I killed my CarMax XML ingest + scheduled Builder agents. Concrete upgrade rec (now in progress): droplet 4GB → 16GB DigitalOcean.
- **Outstanding user action `ua-231508a8`**: Cloudflare cache-purge token. Still unresolved; dashboard still uses `?v=N` cache-bust workaround.

## Open questions
- After resize: rerun CarMax XML ingest for remaining 29 post-2017 deals (~1,400 files × ~1min each at rate-limit). With 16GB RAM + 4 cores, can consider running multiple workers in parallel per deal group to cut wall time.
- `carmax_abs/conditional_markov.py` (~840 lines, untracked): appeared in working tree — origin unclear, possibly from an earlier Builder agent that I didn't commit. Will audit and reconcile with `carvana_abs/conditional_markov.py` post-resize rather than deleting blindly. **Safety-preserved in this checkpoint commit.**
- Remaining 9 CarMax certs with failed reparse (DB-locked during concurrent XML ingest). Easy rerun once system is idle.

## Next step (post-resize clean restart)
1. `bash -lc "ps aux | head -30 && free -h && curl -s https://casinv.dev/capacity.json | python3 -m json.tool | head -10"` — verify droplet is healthy.
2. Re-queue CarMax XML ingestion:
   `export SEC_USER_AGENT='Clifford Sosin clifford.sosin@casinvestmentpartners.com' && nohup /opt/abs-venv/bin/python -m carmax_abs.run_ingestion > /tmp/cmx_absee.log 2>&1 &`
3. Re-run the 9 residual CarMax cert reparses:
   `/opt/abs-venv/bin/python /opt/abs-dashboard/cmx_reparse.py` (working-dir must be `/opt/abs-dashboard` so `inspect.py` isn't shadowed by `/tmp/inspect.py`).
4. Once ALL 33 post-2017 deals have loan-level data: reconcile `carmax_abs/conditional_markov.py` with the Carvana version; run CarMax model pipeline; save to `carmax_abs/db/dashboard.db` `model_results`; update dashboard to show CarMax Bayesian buildup; promote + commit + push.
5. File LESSONS.md entry about the `/tmp/inspect.py` shadowing gotcha (cost ~15 min debug).
6. If `ua-231508a8` is resolved (CF token): remove the `?v=N` cache-bust workaround.

## Known good live state
- Branch `claude/carvana-loan-dashboard-4QMPM`, tip commit TBD (this checkpoint).
- Live URL: https://casinv.dev/CarvanaLoanDashBoard/
- Shipped: full Carvana Bayesian loss-buildup; vintage-blind deal-weighted Markov; CarMax per-deal tabs + CarMax-only + Carvana-vs-CarMax comparison (pool-level, with loan-level placeholders).
- Daily ingest cron at 14:17 UTC: `/opt/abs-dashboard/deploy/cron_ingest.sh`.

## File paths (for any fresh session)
- Conditional Markov (Carvana, SHIPPED): `carvana_abs/conditional_markov.py`
- Conditional Markov (CarMax, UNVERIFIED): `carmax_abs/conditional_markov.py`
- Dashboard renderer (issuer-aware): `carvana_abs/generate_dashboard.py`
- CarMax config (49 deals): `carmax_abs/config.py`
- CarMax ingestion modules: `carmax_abs/ingestion/*.py`
- CarMax reparse helper: `cmx_reparse.py` (repo-root, per `/tmp/inspect.py` gotcha)
- Cloudflare cache-purge script: `deploy/cf_purge.sh` (no-op pending `ua-231508a8`)
```

### /opt/timeshare-surveillance-preview/PROJECT_STATE.md

```markdown
# Timeshare Surveillance (pipeline) — Project State

_Last updated: 2026-04-16 22:30 UTC by orchestrator_

## Current focus
Orchestrator-only work this session. No timeshare-surveillance pipeline activity. Today's work was all platform-level: RCA of the overnight Carvana OOM incident, shipping `project-checkin.sh` cron + 2-hour cooldown fix, critiquing an advisor proposal about Git merge lifecycle / PROJECT_STATE.md / shared-infra protection (user reviewing my counter-plan now).

## Last decisions
- `project-checkin.sh` cron (every 30 min) now runs with a 2-hour per-chat cooldown. Checks: busy+stale-PROJECT_STATE, idle+in-progress-task, dead long-job heartbeats. Commit `ea4fa53` (initial) + `5d89de7` (cooldown fix).
- `claude-project.sh` post-spawn prompt now requires the chat to `ps`-check prior background processes on respawn. Catches the respawn-after-OOM blind spot that bit carvana-abs-2 overnight.
- LESSONS.md entry for the overnight OOM written — compound cause (OOM + nohup-not-systemd + no progress cron + stale PROJECT_STATE).
- Stale `tasks.json` entries cleared for timeshare-surveillance, infra, timeshare-dashboard.
- Critiqued the "advisor" proposal (Git merge lifecycle / PROJECT_STATE.md structure / shared-infra protection / propagate-to-every-project): surfaced conflicts with existing infra to the user; proposed modified plan awaiting approval.

## Open questions
- User's response to the modified advisor-plan counter-proposal. Specifically: should we close / merge the two stale GitHub PRs (#1 Carvana dashboard, #2 GitHub Pages)? Should we ship `projects-smoketest.sh` as an auto-run before shared-infra commits?
- Droplet resize / dev-prod-compliance split still pending user decision.
- Still no systemd-run migration for carmax ingestion — ingestion is currently NOT running. Next time it launches, carvana-abs-2 should use `systemd-run` per `SKILLS/long-running-jobs.md` (third OOM avoided).
- 13 pending user-actions in `casinv.dev/todo.html` — mostly car-offers credentials (MTurk, Prolific, AWS SES, CapSolver, Twilio) + droplet resize + Cloudflare cache-purge token.

## Next step
Wait for user direction on the advisor counter-plan. If no direction lands: start on the most independent of the proposed items — `projects-smoketest.sh` (small, useful regardless of the larger plan). Also do a weekly branch-audit cron since that's a genuinely missing piece.
```

### /opt/timeshare-surveillance-preview/dashboard/PROJECT_STATE.md

```markdown
# Timeshare Credit Dashboard — Project State

_Slug: `timeshare-dashboard`. Last updated: 2026-04-16 14:05 UTC._

## Current focus
Data audit halt-fix-rerun loop, iteration 4 in progress. Iter-3 re-extraction running with delinquency keyword fix (commit 91d9f1c). Watcher queued for Phase 1 auto-scan on completion.

## Last decisions
- **Iter-3 Group D fix (commit 4dbeb54):** tightened balance_sheet prompt ("one net-only figure → return as net, null gross"), added merge guardrail nulling gross when gross==net and allowance>$50M. Eliminated TNL/VAC gross=net bug.
- **Iter-3 Group D residual (HGV 2022+ cross-check 1-3.5%):** marked as known scope mismatch (originated-only narrative gross vs all-pool XBRL net). Filed Task #11 for the real fix (sum pools). Not blocking the audit loop.
- **Iter-3 Group E fix (commit 91d9f1c):** delinquency keyword patterns replaced. `r"aging"` → `r"\baging\b"` + table-header-specific patterns ("30-59 days", "90 or more", "non-accrual"). Should fix HGV/VAC 0% delinquency coverage.
- **HGV/TNL weighted_avg_fico_origination = 0%:** confirmed NOT a bug — these issuers don't disclose a single weighted-average; they give buckets (which we extract at 73-83%).

## Open questions
- Will the new delinquency patterns actually improve HGV/VAC 90+ DPD coverage? Depends on whether the best-match scorer now picks the real aging table.
- Capacity still urgent — each re-extraction adds ~$5 Claude API. Monitor.

## Next step
When iter-3 re-extraction finishes → run Phase 1 scan → if delinquency coverage improved to ≥50%, move to Phase 2 (sample verification). If still <50%, diagnose further.
```

### /opt/timeshare-surveillance-live/PROJECT_STATE.md

```markdown
# timeshare-surveillance-live — Project State

_Last updated: 2026-04-13 17:50 by orchestrator backfill_

## Current focus
<1–2 sentences: what we're working on right now and why. If nothing active, write "idle".>

## Last decisions
- <decision + 1-line rationale>

## Open questions
- <blocker / question awaiting user input, or unresolved trade-off. Remove section contents if none.>

## Next step
<the single next concrete action — file path + what to do. If idle, write "await next user request".>
```

=============================================================================
## 9. MEMORY (per-session persistent memory files)
=============================================================================

Claude Code's memory system: each session directory under /root/.claude/projects/<slug>/memory/ holds a MEMORY.md index and individual feedback/project/reference/user entries. These survive across conversations.

### Global orchestrator memory (/root/.claude/projects/-root/memory/)

#### /root/.claude/projects/-root/memory/MEMORY.md

```markdown
- [User profile](user_profile.md) — non-technical iPhone user; Claude owns technical decisions and never asks the user to run commands
- [Autonomy preference](feedback_autonomy.md) — don't ask for step-by-step approvals; decide and execute, only pause for live-traffic risk
- [URL formatting rule](feedback_urls.md) — never wrap URLs in markdown; iOS link detection grabs the formatting characters and 404s
```

#### /root/.claude/projects/-root/memory/feedback_autonomy.md

```markdown
---
name: Autonomy preference
description: Low-stakes environment; never idle waiting for input, batch blockers upfront, only pause for truly irreversible actions
type: feedback
originSessionId: b28a7faf-a82b-4b3c-b6b7-968f2aea2e0b
---
The user does not want to babysit. This is a personal/low-stakes environment — do not treat routine ops as high risk, and never end a turn waiting for permission when unblocked work remains.

**Why:** The user has stated explicitly: "This is not high stakes." "Do your project. And don't ask me for help." "The key is not to get hung up waiting for me." Their time is the scarce resource; idling defeats the point of delegation.

**How to apply — just do it, no approval needed:**
- File edits (code, config, docs, including CLAUDE.md / LESSONS.md / .md anywhere), refactors, installs, migrations within the project
- Git commits, pushes to `main`, branch switches, merges, tag creation
- Running deploys the pipeline already automates
- Starting/stopping/restarting systemd services, nginx reloads, cron edits
- Choosing between reasonable interpretations when scope is ambiguous — pick one and note it

**Never idle. Batch blockers upfront.**
- At task start, enumerate every permission/secret/external-account/info needed. Ask for them all in one batch while the user is still engaged.
- While waiting for answers: keep working on everything unblocked. Scaffolding, tests, stubs, infra, research.
- If a new blocker surfaces mid-work: add to the running ask list, pivot to unblocked work, don't pause.
- Never emit "should I proceed?", "want me to continue?", "let me know if…" phrasing. Act; report.

**Pause only when:**
- Task is complete and QA green
- Everything that can be done is done AND remaining work is blocked on user input
- Genuinely irreversible/externally-visible action warrants a headline + execute (still not a question)
- Scope explosion discovered — surface revised estimate, then keep working unless told to stop

**Irreversible-only escalations:** data deletion that can't be restored, force-pushing over published history, public-facing actions with real-world consequences (email send, payment, DNS), security-sensitive changes (firewall open to world, auth changes). Everything else: just do it.

**Always leave a rollback path** (git tag, backup) before any non-trivial change so autonomy stays safe.
```

#### /root/.claude/projects/-root/memory/feedback_urls.md

```markdown
---
name: URL formatting rule
description: Never wrap URLs in markdown — iOS link detection on the user's iPhone grabs surrounding characters and sends them to the server as 404s
type: feedback
originSessionId: b28a7faf-a82b-4b3c-b6b7-968f2aea2e0b
---
Never wrap URLs in any markdown formatting in responses to the user.

**Why:** The user prompts from an iPhone. iOS's URL auto-link detection grabs surrounding punctuation like `**`, `)`, `]`, backticks, and periods, and includes them in the tap target. This produces requests like `GET /remote.html**` that 404 on the server. The user has been burned by this twice and has explicitly asked me to stop.

**How to apply:**
- Write URLs bare, on their own line, with a space before and after.
- Never use bold: NOT `**https://casinv.dev/x**` — write `https://casinv.dev/x` plain.
- Never use markdown links: NOT `[link](https://casinv.dev/x)` — write the URL itself.
- Never use inline code: NOT \`https://casinv.dev/x\` — just plain.
- Never put punctuation immediately after a URL unless there's a space: NOT `Go to https://casinv.dev/x.` — write `Go to https://casinv.dev/x` then start a new line or sentence.
```

#### /root/.claude/projects/-root/memory/user_profile.md

```markdown
---
name: User profile
description: User is non-technical, prompts from iPhone, relies on Claude's judgment for technical decisions
type: user
originSessionId: b28a7faf-a82b-4b3c-b6b7-968f2aea2e0b
---
The user is non-technical and prompts from an iPhone. They explicitly rely on Claude's judgment for technical decisions.

**How to collaborate:**
- Own technical decisions. Don't make the user pick between implementation options they can't evaluate.
- Explain trade-offs in plain terms only when they affect product outcomes (cost, time, capability). Recommend one path.
- Never ask the user to run commands, read logs, paste output, or verify URLs — do it and report.
- Keep responses mobile-readable: short, plain text, no wide tables, plain clickable links.
- The user has set up a DigitalOcean droplet at 159.223.127.125 with a multi-project deploy pipeline; they operate it through Claude.
```


### This chat's memory (/root/.claude/projects/-opt-timeshare-surveillance-preview/memory/)

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/MEMORY.md

```markdown
- [PROJECT_STATE.md convention](project_state_convention.md) — four-section per-project continuity file; globally enforced via claude-project.sh + end-project.sh gates as of 2026-04-13
- [Challenge the approach](feedback_challenge_approach.md) — recommend the simpler path (Clerk vs custom auth, SQLite vs Postgres, webhook vs polling) before executing literally
- [Skills search-use-contribute loop](feedback_skills_loop.md) — check SKILLS/ + open-source first; write SKILLS/*.md back after any >30 min pattern discovery
- [Platform stewardship](feedback_platform_stewardship.md) — solve once never twice; keep CLAUDE.md thin, push power into SKILLS/; every session leaves an improvement artifact
- [Parallelize whenever independent](feedback_parallelize.md) — independent tool calls in one message with multiple tool-use blocks; serial out of habit is a tax
- [User actions + accounts](feedback_user_actions_accounts.md) — file manual asks in user-action.sh, register services in account.sh, verify before marking done
- [Restore then root-cause](feedback_rca.md) — patch-to-restore when urgent; RCA + LESSONS.md entry is always mandatory, never optional
- [Memory hygiene](feedback_memory_hygiene.md) — weekly cheap-wins pass (streaming, closed handles, WAL checkpoints, bounded caches); big refactors file separate tasks
- [Non-blocking prompt intake](feedback_non_blocking_intake.md) — main thread is coordinator; new prompts mid-work spawn fresh subagents, never block on in-flight work
- [Data audit & QA](feedback_data_audit_qa.md) — skeptical-auditor pass for number-heavy projects: outlier scan + risk-weighted sample, trace to primary source, re-derive math, change-queue fixes
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_challenge_approach.md

```markdown
---
name: Challenge the technical approach, not just execute
description: User wants agents to flag when there's a simpler/cheaper/better path than what was asked
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
When the user requests a technical thing, assume they're describing the desired outcome — not prescribing the method. Before executing literally, ask: is there a managed service, simpler tool, or dramatically cheaper pattern that delivers the same outcome? If yes, surface it in plain English and recommend one.

**Why:** User is non-technical, iPhone-only. They can't easily tell when their framing of a request leads to over-engineering. Default execution of "what was asked" produces expensive wrong builds.

**How to apply:**
- Use the ~30% bar: only speak up when the alternative saves >30% of the time/cost or eliminates a meaningful failure mode. Don't pedantically suggest alternatives for trivial requests.
- Framing: "You asked for X. Y delivers the same outcome with Z less effort/cost because reason. Going with Y unless you object."
- Assume they will accept the simpler path — don't present it as a menu of tradeoffs for them to adjudicate.
- Encoded in both /opt/site-deploy/CLAUDE.md and /root/.claude/CLAUDE.md under "Challenge the Approach, Not Just the Execution" as of 2026-04-14.
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_data_audit_qa.md

```markdown
---
name: Data audit & QA — skeptical auditor mindset for number-heavy projects
description: Outlier scan + risk-weighted random sample; trace to primary source; re-derive math; root-cause fix via change queue
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
For number-intensive projects (Carvana Loan Dashboard, Timeshare surveillance, any dataset-driven output that feeds a decision), run a data-audit pass before trusting the numbers. Act like a skeptical professional auditor, not a code reviewer.

**Two phases** run inside a **halt-fix-rerun loop**:
1. Universal outlier scan — 100% coverage, fast.
2. Random-sample deep verification — user-specified default %, risk-weighted so headline fields get 2-3× coverage. For each sampled point: trace back to external primary source, re-derive calculations from first principles (never copy from implementation).

Honest stopping conditions when source is unreachable — "verification stopped at layer N" is a finding, not a pass.

**Loop mechanics:** On the first finding, agents halt gracefully (let in-flight batches finish their current sample point, don't abort). Orchestrator groups findings by probable root cause (same column, same row, same period, unit mismatch patterns), then fixes the highest-severity group with one Builder subagent per group. Findings are marked "resolved pending re-audit." Loop reruns from scratch. Exits on a clean pass. `MAX_ITERATIONS` bound (default 10) catches flawed fixes that don't converge.

Why halt-on-first: one root cause often produces many symptoms. Finding N symptoms and fixing in bulk wastes compute AND invalidates earlier findings when the fix ships.

**Why:** User asked to codify this; demonstrated need from Carvana Loan Dashboard where data-quality audits are a recurring need. Key distinction: checking is massively parallelizable, fixing must be orchestrated to avoid collision.

**How to apply:**
- Ask the user for default sample rate if not provided; suggest 10%.
- Batch Phase 2 checks ~10-50 per subagent.
- Check /capacity.json before fanning out heavily.
- Full playbook: `/opt/site-deploy/SKILLS/data-audit-qa.md`.
- Encoded in both CLAUDE.md copies as of 2026-04-14 under "Data Audit & QA."
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_memory_hygiene.md

```markdown
---
name: Memory hygiene — weekly cheap wins, not quarterly refactors
description: Routine flossing-grade memory cleanup; triggers weekly + whenever /capacity.html goes warn
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
Every project chat does a memory-hygiene pass weekly and on-demand whenever `/capacity.html` goes warn. Scope is strictly cheap wins: streaming queries, closed handles, closed browsers, SQLite WAL checkpoint + VACUUM, bounded caches, log rotation, gzipped raw caches. Not refactors.

**Why:** User observed that capacity-urgent events today happened because no one was doing routine cleanup. Small cumulative wins on a cadence keep the box healthy; a quarterly refactor comes too late. Also: users can't tell the difference between "carefully optimized" and "routinely hygienic" — both just feel like "the platform works."

**How to apply:**
- 7-category checklist in `/opt/site-deploy/SKILLS/memory-hygiene.md`. Walk through in <30 min.
- Skip (file separate task): schema changes, S3/Spaces migrations, library swaps, cache-layer additions. Anything with a real performance tradeoff or design decision.
- Measure before/after via `resource.getrusage(RUSAGE_SELF).ru_maxrss` or `systemctl status <service>` peak RSS.
- Log each pass in PROJECT_STATE.md: "Memory hygiene YYYY-MM-DD: found X, shipped Y, deferred Z."
- Encoded in both CLAUDE.md copies as of 2026-04-14 under "Memory Hygiene."
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_non_blocking_intake.md

```markdown
---
name: Non-blocking prompt intake — main thread is coordinator, not executor
description: New user prompts mid-work spawn fresh subagents instead of blocking; status questions always spawn
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
When a new user prompt arrives while subagents or other work is in flight, hand it off to a fresh subagent immediately (if independent). Don't make the user wait for the in-flight stack to drain. The main thread's job is routing, merging, and writing final answers — not executing long tool calls.

**Why:** Observed carvana-abs sitting "unresponsive" for 18 minutes with two queued user messages while three subagents ran. The user's experience is "the chat is broken" even though tons of work is happening. Behavioral fix, not code.

**How to apply:**
- Decision: independent → spawn immediately; clarifying → refine in place; correcting → interrupt; status/read-only → always spawn.
- Dispatch mechanics: one message with multiple tool-use blocks (Agent spawn + continued orchestration of in-flight work). See `SKILLS/parallel-execution.md § How To Dispatch`.
- Spawn a subagent for anything that takes >30 seconds or requires deep reading; trivial answers come from main thread directly.
- Every ~10 min of no user-facing output, surface a one-line progress update so long silences don't accumulate.
- Full playbook: `/opt/site-deploy/SKILLS/non-blocking-prompt-intake.md`.
- Encoded in both CLAUDE.md copies as of 2026-04-14 under "Non-Blocking Prompt Intake."
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_parallelize.md

```markdown
---
name: Parallelize whenever independent
description: User requires parallel operations by default; sequential is the exception
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
**Never do work sequentially that can run in parallel.** Independent tool calls go in a single assistant message with multiple tool-use blocks. Research agents, builder subagents, status polls, independent bash commands — all fan out.

**Why:** Wall-clock time is the user's scarce resource. Five independent operations run concurrently finish in the time of the slowest, not the sum. Serial execution out of habit is a silent tax on every session.

**How to apply:**
- Decision test: if neither operation needs the other's output AND they don't touch the same mutable state AND order doesn't matter, they're independent → parallel.
- Dispatch mechanics: one assistant message with multiple tool-use blocks. Separate messages = serial with full latency between each.
- Full playbook lives in `/opt/site-deploy/SKILLS/parallel-execution.md` (when to parallelize, when to serialize, pitfalls).
- Encoded in both CLAUDE.md copies as of 2026-04-14 (commit 051a7b5).
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_platform_stewardship.md

```markdown
---
name: Platform stewardship — solve once, capture, improve
description: Every session must leave the platform better; problems solved once never resolved. Playbook lives in SKILLS/platform-stewardship.md
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
**Core principle: a problem solved once should never need to be solved again.**

Every session should leave one artifact that makes future sessions cheaper — a new skill, a sharper rule, a removed manual step, a trimmed doc. If a session ends with no such artifact, the platform stood still. That's the failure mode.

**Why:** User's goal is compounding capability, not per-task output. They want the platform to actively seek out efficiency gains and preserve learnings so nothing is relearned. They also explicitly want CLAUDE.md thin — it's the constitution, power lives in SKILLS/.

**How to apply:**
- Four registers of knowledge: CLAUDE.md (rules), SKILLS/ (how-to), LESSONS.md (incidents), RUNBOOK.md (per-project facts). See `/opt/site-deploy/SKILLS/platform-stewardship.md` for decision table and triggers.
- CLAUDE.md sections must fit one iPhone screen; if a section grew past that, extract detail to a SKILLS file and leave a one-line pointer.
- Write-up triggers: >30 min non-obvious pattern, new library/service, same problem solved twice, broken production, inefficient pattern with short fix.
- Encoded in CLAUDE.md (both copies) under "Continuous Platform Improvement" and SKILLS/platform-stewardship.md as of 2026-04-14.
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_rca.md

```markdown
---
name: Restore then root-cause — never stop at the patch
description: Patch-to-restore is fine when urgent, but RCA is mandatory after; every incident ends with a LESSONS.md entry
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
**Restore service fast when needed — then always do root-cause analysis.** Patching and RCA are not alternatives. The patch buys time; the RCA prevents recurrence.

**Why:** Patch-and-move-on looks like resolution but is incident debt. User explicitly wants both done: restore first if urgent, RCA always.

**How to apply:**
- Flow: patch with `// HOTFIX <date>: RCA pending` marker → immediately file an RCA follow-up task (TaskCreate or user-action.sh) → do the 5-whys investigation within 24h → ship the permanent fix + LESSONS.md entry in one commit → close the follow-up.
- LESSONS.md entry must include: root cause (1-3 sentences), fix (file:line), preventive rule (test / lint / CLAUDE.md clause / runbook check — or explicitly note "one-off").
- Symptom-suppressors that should trigger alarm bells: `sleep N`, `waitForTimeout`, retry loops without understanding, `try {...} catch {/* ignore */}`, service restarts as resolution, pinned versions you haven't audited.
- Playbook: `/opt/site-deploy/SKILLS/root-cause-analysis.md`.
- Encoded in both CLAUDE.md copies as of 2026-04-14 under "Restore, Then Root-Cause" (commit pending).
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_skills_loop.md

```markdown
---
name: Skills search-use-contribute loop
description: Search SKILLS/ and open-source first; contribute SKILLS/*.md back after non-obvious solves
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
Before writing code, search three sources in order: `SKILLS/*.md`, open-source packages (npm/PyPI/system tools with real maintenance), managed services. Prefer thin wrappers around battle-tested libraries over custom code; custom implementations must justify themselves.

After any non-trivial solve, **write or update `SKILLS/<topic>.md` in the same commit**. Triggers: >30 min on a non-obvious pattern; a solve that will likely recur; first-time integration of an external service or library.

**Why:** User wants compounding knowledge. Every skill written once spares every future agent (including future-you) from relearning the same gotchas. The existing "check SKILLS first" rule was too passive — it didn't mandate contributions back, so the registry was stagnant.

**How to apply:**
- Codified in both /opt/site-deploy/CLAUDE.md and /root/.claude/CLAUDE.md under "Skills Registry — Search, Use, Contribute Back" as of 2026-04-14 (commit 162fd7b).
- Reviewer agents should fail any non-trivial PR that introduces a new pattern without a SKILLS entry.
- When unsure a library is reputable (maintenance, downloads), name it and ask the user rather than guessing.
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/feedback_user_actions_accounts.md

```markdown
---
name: User actions + accounts — verify, don't assume
description: Manual asks go in user-action.sh tracker; accounts go in account.sh registry; never mark done without independent verification
type: feedback
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
Never ask the user for a manual action and then assume it happened. Every such ask must be filed with `/usr/local/bin/user-action.sh add <project> "<title>" "<steps>" "<verify_by>"`. At session start, run `user-action.sh remind` to see open asks; only call `user-action.sh done <id>` after you've programmatically verified completion (curl, env check, API call).

Every third-party account or subscription the platform uses gets registered with `/usr/local/bin/account.sh add <service> <purpose> <url> "<cred-location>" [monthly-cost]` so subscriptions live in one place.

**Why:** The user forgot things buried in past chat context and agents assumed completion, leaving services half-configured. Signups and credentials multiply across projects without a central ledger.

**How to apply:**
- Verify_by must be something *you* can run — not "confirm with me." If you can't verify it, make the step concrete enough that you can.
- Mobile pages: `https://casinv.dev/todo.html` (counter badge on projects.html), `https://casinv.dev/accounts.html`.
- Steps written for non-technical iPhone user: plain text, plain URLs (no markdown wrapping), numbered 1/2/3.
- Playbooks: `/opt/site-deploy/SKILLS/user-action-tracking.md` and `/opt/site-deploy/SKILLS/accounts-registry.md`.
- Encoded in both CLAUDE.md copies as of 2026-04-14 (commit 5f28fb4).
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview/memory/project_state_convention.md

```markdown
---
name: PROJECT_STATE.md convention
description: Per-project session-continuity file convention; rolled out globally 2026-04-13
type: project
originSessionId: 10594318-683e-4f81-9433-313fb0443164
---
Every project owns a `PROJECT_STATE.md` at its root with four sections: Current focus, Last decisions, Open questions, Next step. Read it on entering a project window; update it before ending a turn.

**Why:** User wants to return to a project after a break and have the AI be "right where we left off." Global `TASK_STATE.md` only holds the latest task; `RUNBOOK.md` is static facts; nothing else carries current-session context per project.

**How to apply:**
- When entering any project window, read `PROJECT_STATE.md` first. `claude-project.sh` prompts the AI to do this automatically on spawn. If missing, create from `/opt/site-deploy/deploy/templates/PROJECT_STATE.md.template`.
- Before ending a turn, update if focus/decisions/questions/next-step changed. `end-project.sh` refuses to close a window whose `PROJECT_STATE.md` wasn't touched this session (`--force` override logs staleness).
- Keep it short — four sections, no history. Git covers history.
- Rolled out globally in site-deploy commit `171fd4a` on 2026-04-13; existing projects were backfilled with stub files at the same time.
```


### Timeshare-dashboard chat's memory (/root/.claude/projects/-opt-timeshare-surveillance-preview-dashboard/memory/)

#### /root/.claude/projects/-opt-timeshare-surveillance-preview-dashboard/memory/MEMORY.md

```markdown
- [Cache downloaded SEC filings on disk](feedback_cache_sec_filings.md) — Persist raw EDGAR documents so re-extraction never re-downloads.
```

#### /root/.claude/projects/-opt-timeshare-surveillance-preview-dashboard/memory/feedback_cache_sec_filings.md

```markdown
---
name: Cache downloaded SEC filings on disk
description: For the timeshare-surveillance project, always persist raw SEC EDGAR filings to a local cache on disk so re-extraction does not require re-download.
type: feedback
originSessionId: 1ce939c0-13fa-47b0-bcdb-e294d3111caf
---
When fetching SEC filings (10-K / 10-Q / XBRL / Atom feed hits) for the timeshare-surveillance pipeline, always save the raw downloaded document to a persistent cache on disk (e.g., `data/sec_cache/<TICKER>/<accession>/`) before any parsing or extraction. The extractor should read from cache if present.

**Why:** The user explicitly asked for this on 2026-04-13 when planning the 5-year longitudinal backfill across HGV/VAC/TNL. Re-downloading SEC filings is slow and rate-limited (EDGAR requires throttling to 10 req/s with a User-Agent), and if we later want to pull additional metrics (new segment, new field) we shouldn't have to hit EDGAR again.

**How to apply:** Any new code path that fetches from sec.gov must write raw bytes to the cache directory and prefer cache hits over network calls. Treat re-extraction as an offline operation once the cache is warm. Do not put cached filings in git (large binaries / HTML); keep on droplet disk only.
```


---

_End of bundle. For live state (which moves fast), hit the JSON endpoints listed in ADVISOR_CONTEXT.md section 11._
