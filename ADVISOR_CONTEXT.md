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
/root/.ssh/id_ed25519                   infra-agent SSH key (PUBLIC key generated 2026-04-15; as of this writing, NOT YET added to user's DO account — was erroneously described as "added" in an earlier version of this doc; correction 2026-04-17)
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
