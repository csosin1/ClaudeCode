# Agent Rules

## User Context
The user is non-technical and prompts from an iPhone. Claude owns technical decisions — don't surface jargon or ask the user to pick between implementation options. When a choice has real product trade-offs, explain them in plain terms and recommend one. Never ask the user to run a command, read a log, or paste output.

**URLs in messages must be plain, never wrapped in markdown.** iOS URL detection grabs surrounding characters like `**`, `)`, or backticks and includes them in the tap target, producing 404s. Write URLs on their own line with a space before and after — never `**https://...**` or `[text](https://...)` or \`\`https://...\`\`.

## Setup & host topology
- **Dev droplet** (this box, 159.223.127.125, 4GB/2-core, Ubuntu 22.04): nginx edge + Claude Code chats. Code edits happen here.
- **Prod droplet** (`ssh prod-private` → 10.116.0.3, 8GB/4-core, Ubuntu 24.04, NYC1 VPC): runs all migrated app services. **Heavy compute (Markov training, batch scrape, ML regen, big rsync) MUST run on prod** — `ssh prod-private <cmd>`. Dev is a 4GB box; running compute there starves everyone. Writes to `/opt/<project>/` on dev go to a rollback copy that Phase 5 deletes.
- **Deploy pipeline**: push to main on dev → webhook (2–3s) → `/opt/site-deploy/deploy/auto_deploy_general.sh` on dev → `/etc/deploy-to-prod.conf` rsyncs code to prod. abs-dashboard is the exception: its own auto-deploy.timer on prod tracks `claude/carvana-loan-dashboard-4QMPM`. `*.db`/`*.sqlite`/WAL/journal/shm are rsync-excluded — databases on prod are authoritative.
- Mobile-first output. Every project reachable in one tap from https://casinv.dev/.

## Clarify Before Building
iPhone prompts are short and sometimes autocorrected. If a request is ambiguous, state your interpretation and ask one focused question. A wrong build done confidently is the most expensive outcome. For non-trivial scope, include success criteria and file locations in your interpretation before building — full spec template in `SKILLS/user-info-conventions.md` when you need it. For UI-shipping changes, name which user journey (from project `PROJECT_CONTEXT.md#user-journeys`) this extends, modifies, or introduces.

## Challenge the Approach
Users describe **outcomes**, not methods. Before building what was literally asked, ask: is there a simpler tool, managed service, or pattern that delivers the same outcome with dramatically less complexity, cost, or fragility? If yes, surface it in plain English, recommend one, and ask before spending hours on the harder path. Rough bar: would the alternative save >30% of the time or cost, or eliminate a meaningful failure mode? Frame as "here's the cheaper way, shipping it unless you object" — not a menu of options.

## Every Task Passes The Gates
Nothing defective reaches the user. Each gate uses a fresh subagent.
1. **Build** — Builder writes the feature + Playwright tests in `tests/<project>.spec.ts` that exercise it like a user (click, fill, assert real values — no NaN/blanks).
2. **Review** — Reviewer reads the diff against spec, `LESSONS.md`, security baseline. Must return PASS before deploy.
3. **QA** — push to `main` deploys to preview; `qa.yml` runs Playwright at 390px + 1280px per `SKILLS/perceived-latency.md` + `SKILLS/visual-lint.md`. Regressions fail; fix and redeploy without approval.
4. **Rehearse** — after QA green, `acceptance-rehearsal` walks the declared user journey (per `SKILLS/acceptance-rehearsal.md`) and attaches a narrative to `CHANGES.md`.
5. **Accept** — share the preview URL + narrative. User's "ship it" is the only approval gate. On accept: promote preview → live. The main session orchestrates — it does not write code directly.

## Parallel Execution
**Never do work sequentially that can run in parallel** — tool calls, subagents, builders, research queries. Independent tool calls go in a single assistant message with multiple tool-use blocks. **Plans estimated to take more than 1 minute of wall-clock MUST route through `.claude/agents/speedup-reviewer.md` before dispatch.** The reviewer produces advice, not a gate — dispatcher retains final call — but the review step itself is required, and its findings inform the final plan. See `SKILLS/parallel-execution.md`.

## Non-Blocking Prompt Intake
**The main thread is a coordinator, not an executor.** When a new user prompt arrives while other work is in flight, hand it off to a fresh subagent immediately (if independent) — don't make the user wait for the in-flight stack to drain. Status questions always spawn; corrections interrupt; clarifications refine. See `SKILLS/non-blocking-prompt-intake.md`.

## Project Isolation
Each project owns only: `/opt/<project>/`, `deploy/<project>.sh`, `tests/<project>.spec.ts`, `PROJECT_STATE.md`, its nginx location block, systemd unit, `/var/log/<project>/`, logrotate, uptime cron. Shared paths (`deploy/auto_deploy_general.sh`, `deploy/update_nginx.sh`, `deploy/landing.html`, `.github/workflows/*`, `CLAUDE.md`, `LESSONS.md`, `RUNBOOK.md`, `.claude/agents/*.md`, `SKILLS/*.md`) are modified only via `CHANGES.md` proposals from project chats. Writing outside own paths is a bug.

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
For number-intensive projects, every load-bearing dataset or dashboard passes a skeptical-auditor halt-fix-rerun audit before promote. See `SKILLS/data-audit-qa.md`.

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
