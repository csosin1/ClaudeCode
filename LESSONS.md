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
