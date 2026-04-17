# Lessons Learned

Append an entry when something breaks in a way that wasn't obvious from the code. Builders and Reviewers read this before starting a task.

## Format

```
## [YYYY-MM-DD] [short title]
- **What went wrong:**
- **Root cause:**
- **What to do differently:**
```

## 2026-04-17 — general-deploy auto-deployed all projects to prod as side-effect of Phase 3
- **What went wrong:** After Phase 3 (carvana-abs migration) the prod droplet was running `/etc/systemd/system/general-deploy.timer` every 5 min, which invoked `/opt/auto_deploy_general.sh` and ran `deploy/<project>.sh` for EVERY project — including the heavy Carvana ML retrain. Dev already ran the same timer, so every push to main paid the retrain cost twice (once per droplet) and quietly added load to prod that nobody had budgeted for. We only noticed because prod capacity nudged upward and `systemctl status general-deploy.timer` showed it firing on prod.
- **Root cause:** When we set up the prod droplet we rsync'd `/etc/systemd/system/` wholesale from dev to save time, which copied **general-deploy.timer enabled** along with the project-specific timers we actually wanted. No explicit gate caught it because "copy all systemd units from dev" looks identical on paper whether the unit is meant to run on the new box or not. The timer should have been scoped dev-only from the start; prod should only have the per-project `auto-deploy.timer` (abs-dashboard git-pull) plus the passive dev→prod rsync mechanism that Phase 1 built.
- **Fix:** Stopped + disabled `general-deploy.timer` on prod (left files in place for auditable rollback). Extended `/etc/deploy-to-prod.conf` with gym-intelligence + car-offers entries so dev's post-deploy rsync now mirrors code to prod for all migrated projects. abs-dashboard stays on its own git-pull `auto-deploy.timer` (prod is authoritative for its 34 GB SQLite state; dev rsync would clobber). See CHANGES.md 2026-04-17 Option C entry.
- **Preventive rule: when copying systemd/cron infrastructure to a new droplet, explicitly enumerate which timers/services should remain enabled on the new box — don't rely on `rsync /etc/systemd/system/` to produce the right shape.** Platform-wide timers (general-deploy, anything that fans out across all projects) should live on exactly ONE droplet; the others get per-project passive mirrors. Add a post-migration checklist item: `ssh newbox 'systemctl list-timers --all'` and justify every ENABLED timer against the migration brief before declaring the phase done. Skill doc candidate: expand `SKILLS/new-project-checklist.md` (or a sibling) with a "copying infra to new droplet" section.

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

## 2026-04-17 — "Expected state" written as "actual state" in a snapshot doc

**Symptom:** User's DO Security page showed zero SSH keys, but `ADVISOR_CONTEXT.md` claimed the infra-agent key was "added to my DO account." Direct contradiction noticed only because user cross-checked.

**Root cause:** I generated the SSH key on 2026-04-15, told the user to add it to DO, never verified it had actually been added. Two days later when writing ADVISOR_CONTEXT.md, I described the state in past-tense ("added") as if it were verified reality. It was expected state presented as actual state.

**Fix:** Corrected the line in ADVISOR_CONTEXT.md to explicitly state "NOT YET added as of writing; correction 2026-04-17."

**Preventive rule:** When writing state-of-the-world documents (ADVISOR_CONTEXT, RUNBOOK, any snapshot), only assert as actual state what was directly verified at write time. If a state was *instructed but not confirmed*, write it explicitly: "user was asked to X at <date>; as of this writing, not yet verified." This is a direct application of the data-audit-qa principle ("honest stopping conditions — verification stopped at layer N") to our own documentation, not just external data sources.

## 2026-04-17 — Shipped advisor-docs endpoint; Anthropic IP ranges not publicly published

**Symptom / context:** user asked for a read-only view of /opt/site-deploy/ advisor-relevant files at a public URL, gated by IP allow-list restricting access to Anthropic's web-fetcher ranges.

**Finding:** Anthropic does not publish an authoritative IP range list as of 2026-04-17. Checked docs.anthropic.com/ip-ranges.json (301 → 404), docs.claude.com (same), console.anthropic.com, api.anthropic.com, and the agent-tool documentation pages. No authoritative source.

**Decision per user instruction:** fell back to HTTP basic auth with a generated per-session password stored in `/opt/site-deploy/.env.docs-credential` (gitignored). nginx location block `/docs/` at `/var/www/docs/`, auth_basic via `/etc/nginx/docs.htpasswd`. Password shared with user for each advisor-session URL.

**Future state:** `/usr/local/bin/refresh-docs-ip-allowlist.sh` runs weekly (`0 8 * * 1` in `/etc/cron.d/claude-ops`) to probe candidate endpoints. When Anthropic publishes, implement parsing in that stub + remove auth_basic.

**Preventive rule:** when a requested mechanism depends on an upstream not-yet-shipping capability (published IP ranges, a webhook, a new API), don't block on it. Ship an equivalent-security fallback now + plant a dated probe script + LESSONS entry. Revisit quarterly. Document the fallback explicitly as a fallback, not as the intended design.

## 2026-04-17 — Claude web-fetch tool strips embedded URL credentials

**Symptom:** User reported advisor session couldn't fetch `https://advisor:PASS@casinv.dev/docs/` — fetcher returned `PERMISSIONS_ERROR`. Basic-auth via URL didn't work even though nginx confirmed the credentials were valid from curl.

**Root cause:** Claude's web-fetch tool (and most HTTPS clients since ~2020) silently strip the `userinfo` portion from URLs per RFC 3986 security guidance. The fetcher sees `https://casinv.dev/docs/` after stripping, which then returns 401 from our basic-auth challenge.

**Fix:** Switched from basic-auth to **path-secret** — the URL path itself is the credential. `/docs/<TOKEN>/` serves the docs, anything else under `/docs/` returns 404. No credentials anywhere in the request; works with any fetcher.

**Preventive rule:** For auth-gated endpoints that need to be fetchable by Claude or other LLM tool fetchers, use **path-secret** or **query-string token**, NOT basic-auth with credentials in the URL. If IP allow-list becomes available (e.g., Anthropic publishes egress CIDRs), that's the strictest gate; otherwise path-secret is the practical floor. Header-based auth (`Authorization:`) may or may not work depending on the fetcher; path-secret works universally.

## 2026-04-17 — Parallel infra-builders on shared repo caused cross-track commit commingling

**Symptom:** Four infra-builder agents dispatched in parallel for alerts #1-#4. Alert #2's agent committed commit `f2ab46d` which unexpectedly included Alert #4's files (`migrate-phase.sh` + `migration.html`) that Alert #4's agent had staged but not yet committed. Commit attribution wrong; if we needed to revert one feature cleanly, couldn't.

**Root cause:** All four agents ran `git add` + `git commit` in the shared `/opt/site-deploy/` checkout. When Alert #2's `git add SPECIFIC_FILES` ran, git's index already had Alert #4's concurrent `git add` pending from seconds earlier. The commit swept both sets in.

**Fix going forward:** parallel infra-builder dispatches must each use their own worktree via `start-task.sh infra "<slug>"` at `/opt/worktrees/infra-<slug>/`. `finish-task.sh` merges to main serially. Direct-to-main pushes only safe for single-builder work. Added to `.claude/agents/infra-builder.md § Parallel-dispatch hygiene`.

**Preventive rule:** when orchestrator dispatches ≥2 builders concurrently, the brief MUST include "use `start-task.sh infra` to get a worktree; commit there." Orchestrator verifies independence (file-path non-overlap) before fan-out but the worktree isolation is the structural defense.

## 2026-04-17 — System-reminder about malware analysis over-interpreted by builder subagent

**Symptom:** Dispatched infra-builder on Alert #3 (auto_deploy_general.sh failure trap). Agent read the target file, received the standard "consider whether this code is malware; you MUST refuse to improve or augment" system-reminder, and refused the entire task. No edits shipped. Agent's reasoning: "Adding a trap handler is augmentation; I cannot proceed."

**Root cause:** The reminder is scoped to unknown/suspicious third-party code being analyzed, not to legitimate platform edits the user explicitly dispatched. The agent's isolated context didn't carry the session history confirming `auto_deploy_general.sh` is our platform code with weeks of git history under the user's account. So it applied the reminder as a blanket refusal.

**Fix:** added to `.claude/agents/infra-builder.md § System reminders: scope and interpretation` — explicit guidance that the reminder is about malicious code and does not blanket-block legitimate platform work. Default posture: proceed-with-care; only escalate if the file legitimately looks opaque / outside platform scope.

**Preventive rule:** in every subagent brief for platform work, include a one-line preamble: "This task is within our platform infrastructure scope. System-reminders about malware analysis are about unknown code; proceed with the edit unless the file itself looks opaque or outside the declared scope."

## 2026-04-17 — Infra-QA position coverage missed bot-fingerprint-specific CDN responses

**Symptom:** Advisor fetcher consistently received 404 for `https://casinv.dev/docs/<token>/` despite infra-QA showing PASS across 4 positions (dev localhost, prod via Cloudflare, origin bypass, 60s repeat). User flagged the gap.

**Root cause:** The four positions all used curl's default (or common UA) fingerprint. Cloudflare's Bot Fight Mode / Verified Bots filter treats requests from Anthropic's web-fetch infrastructure differently from generic curl requests — it can serve a 404 (not the origin's) without the request reaching origin nginx. Evidence: zero entries for `/docs/<token>/` in origin nginx access log during the windows when the user's fetcher was 404-ing, while curl-through-Cloudflare succeeded repeatedly. The QA's notion of "from external vantage" was satisfied by IP-external but not fingerprint-external to what the actual consumer looks like.

**Fix:**
1. Added Position 5 to `.claude/agents/infra-qa.md`: cycle curl through a set of bot-class UAs (ClaudeBot, Anthropic-Claude-Fetcher, Claude-User, python-requests, empty, Mozilla). Any UA-sensitive response divergence is a blocker requiring CDN rule tuning.
2. Position 5 added to the 60s-repeat loop so edge-cache + WAF-state evolution over time is visible.
3. Explicit note in the agent definition: position 4 (user's fetcher) + position 5 (simulated fetcher fingerprints) together cover the bot-mode class of gap that positions 1-3 miss.

**Preventive rule:** Infra-QA position coverage must include **request-origin characteristics** (IP, UA, TLS fingerprint where testable) of the *actual consumer*, not just generalized external fetches. Default-curl responses are insufficient evidence that a bot-fingerprinted consumer will succeed. When a consumer can't be fully fingerprint-simulated (e.g., Claude web-fetch uses TLS details we can't replicate), explicitly flag the coverage gap and require user-manual confirmation as an observation-required item — same pattern as phone-receipt for ntfy.

## 2026-04-17 — post-deploy-rsync ran POST_CMD every cron cycle, killing long-sleeping service

**Symptom:** `timeshare-surveillance-watcher.service` on prod was getting SIGTERM'd and restarted every ~5 minutes for at least 4 hours (49+ restarts observed). `active (running)` from systemd's perspective, but its 900-second sleep between EDGAR fetch cycles never completed, so no new filings were pulled. `/opt/timeshare-surveillance-live/dashboard/data/combined.json` mtime frozen at 2026-04-13 01:40 UTC — 4 days stale. Classic silent-write-failure: health checks pass (HTTP 200 serving the stale file) while the underlying data pipeline hasn't fired in days.

**Root cause:** `/usr/local/bin/post-deploy-rsync.sh` is cron'd every 5 min on dev. For each entry in `/etc/deploy-to-prod.conf` whose rsync exited 0 (always, given healthy VPC), it **unconditionally** ran the configured POST_CMD — in timeshare's case `systemctl try-restart timeshare-surveillance-watcher-preview timeshare-surveillance-admin-preview`. The watcher's sleep is longer than the restart cadence → it never made it to the next cycle.

**Discovered:** via the 24h-rollback-window write-path verification, *not* the overnight infra-QA. Phases 1-4 QA checked HTTP reads; the watcher looked fine externally. The bug existed since Phase 1 but was invisible until someone asked "are writes actually happening?"

**Fix:** post-deploy-rsync.sh now uses `rsync --stats`, captures output to a tmpfile, parses `Number of regular files transferred: N`, and only fires POST_CMD when N > 0. If nothing changed, no restart. Verified at 11:20Z cron fire — no restart happened (first skip in 4+ hours).

**Preventive rules:**
1. **Unconditional post-action in a cron loop + long-sleeping service = silent failure.** Any rsync-and-restart pattern must gate the restart on actual changes. Generalize: any periodic-poll loop that acts on every tick (rather than on detected change) will mask itself when it interacts with a service whose natural period exceeds the loop's.
2. **Write-path checks belong in QA.** Infra-QA currently verifies routing + headers + body parity (reads). Add a write-path category — for each migrated app, trace a write to its state store and confirm mtime freshness matches the declared cadence. Update `.claude/agents/infra-qa.md` accordingly (separate commit).
3. **Prefer change-triggered hooks over periodic polling** when syncing + restarting. Webhook-driven deploys (post-receive git hooks) don't have this failure mode because they only fire on push.

## 2026-04-17 — Fresh prod droplet shipped with ufw inactive; app ports reached public internet during Phase 2

**Symptom:** During Phase 2 (gym-intelligence) migration, infra-QA flagged that prod's Flask services bound `0.0.0.0:8502/:8503`. Confirmed from dev: `curl http://67.205.140.167:8502/ → HTTP 404` (port open, app just doesn't route `/`). `ufw status` on prod: **inactive**. `iptables -L`: default ACCEPT on all chains. Phase 1 timeshare was unaffected only because those services bind `127.0.0.1` and sit behind a prod-local nginx — an accidental protection, not a designed one.

**Root cause:** DigitalOcean's stock Ubuntu 24.04 image ships with ufw installed but disabled, no DO cloud firewall attached by default, and no droplet bake-in step in our Phase 0 runbook to enable one. We only noticed because QA's Position-independent check observed the 0.0.0.0 bind — without that check, Phases 3+ would have widened the exposure silently (abs-dashboard has no 0.0.0.0 bind today; car-offers Playwright services would).

**Fix applied 2026-04-17 02:36Z:**
```
ufw default deny incoming ; ufw default allow outgoing
ufw allow 22/tcp ; ufw allow 80/tcp ; ufw allow 443/tcp
ufw allow from 10.116.0.0/20  # DO VPC NYC1 — dev↔prod private traffic
ufw --force enable
```
Verified: dev→prod-private-IP:8502 still HTTP 200 (VPC rule), public-IP:8502 times out (no match → deny), SSH still reachable, smoketest 17/17 green.

**Preventive rule:** Any new prod droplet's Phase 0 bake-in **must** end with ufw enabled + default-deny-incoming + explicit allow-list for 22/80/443 and the VPC CIDR. Add to `MIGRATION_RUNBOOK.md` Phase 0 checklist and any future droplet-provisioning automation. An app-port bound to 0.0.0.0 is a pre-existing vulnerability when the surrounding network has no default filter — the fix belongs at the network boundary, not per-service.
