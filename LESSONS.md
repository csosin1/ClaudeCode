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
