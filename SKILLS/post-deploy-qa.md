---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Post-deploy QA hook

Runs a project's fast smoke tests against the **live URL** immediately after
`auto_deploy_general.sh` regenerates the project's output. Failure notifies and
(optionally) freezes further auto-deploy for that project until an operator
investigates.

## When to use

Any project whose `auto_deploy.sh` regenerates user-facing output — static
dashboards, scraped-data surfaces, regenerated SQLite DBs consumed by live
endpoints, server-rendered pages that depend on upstream inputs. If a regen
can ship a bug that PR-time QA already passed, this hook is your net.

If the project is purely a static HTML bundle whose only input is source code
(no scraped data, no upstream freshness), PR-time QA already covers it and
the post-deploy hook is redundant.

## The gap it closes

PR-time QA (`qa.yml`) runs Playwright against **preview** when a feature branch
PRs against main. It is comprehensive but it does not run again when the
deployed project is **regenerated from current inputs** on a schedule / on
upstream data change.

**The Hazard-by-LTV incident (2026-04-17).** The abs-dashboard
auto-deploy regenerates the dashboard whenever loan-level inputs change.
A mid-rebuild stale cache regen produced a heatmap that collapsed every LTV
bucket into one cell. PR-time QA had already passed on the (unrelated) code
change that triggered the rebuild. The bug shipped live because nothing ran
tests against the regenerated artefact. Post-deploy hook would have caught it
before users saw it.

**PR-time and post-deploy are both needed, not alternatives.** PR-time checks
that new code is correct. Post-deploy checks that the deployed combination of
code + current inputs is correct. Different failure modes, different gates.

## Adoption for a project

Three steps, in order:

1. **Tag fast smoke tests with `@post-deploy`.** In your spec file
   (`tests/<project>.spec.ts`), add the tag to the title of each test you
   want to run on every regen. Budget: < 30 seconds total for the tagged
   subset. These should be the "is the page loading, do the numbers render,
   did the freshness timestamp advance" checks — not the comprehensive
   happy-path + edge-case coverage.

   ```ts
   test("dashboard renders current-cycle totals @post-deploy", async ({ page }) => {
       await page.goto(LIVE_URL);
       // ... assertions
   });
   ```

2. **Add a row to `/etc/post-deploy-qa.conf`.** TAB-separated:

   ```
   <project>	<cmd_template_with_{LIVE_URL}>	<timeout_sec>	[--freeze-on-fail]
   ```

   The version-controlled mirror is `/opt/site-deploy/helpers/post-deploy-qa.conf`;
   edit there and let auto-deploy sync to `/etc/`. Example:

   ```
   abs-dashboard	cd /opt/abs-dashboard && npx playwright test --grep=@post-deploy	180	--freeze-on-fail
   ```

   The `{LIVE_URL}` placeholder in the template is substituted by the hook
   at runtime; prefer using it so the command never drifts from the URL the
   hook was invoked with.

3. **Decide on `--freeze-on-fail`.** Conservative projects (financial
   dashboards, anything where "show a wrong number" is worse than "show
   nothing") → yes, freeze. More tolerant projects (scraped data where a
   transient upstream failure is expected) → no, notify only.

## The freeze sentinel pattern

When the hook fails with `--freeze-on-fail`, it writes
`/var/run/auto-deploy-frozen-<project>` containing the project name, live URL,
timestamp, failure reason, and the exact `rm` command to clear it.

On the next auto-deploy cycle, `auto_deploy_general.sh` sees the sentinel,
skips the project's deploy script entirely, and fires an urgent ntfy to tell
the operator auto-deploy is blocked. This loops every cycle until the
sentinel is removed — the user cannot miss that something needs attention.

**Clearing:** after investigating, `rm /var/run/auto-deploy-frozen-<project>`.
The next regen cycle will re-run the deploy script and the post-deploy hook.
If the underlying cause is fixed, the hook passes and the project is unfrozen.
If not, the sentinel is re-written and the freeze continues.

**When to use `--freeze-on-fail`:** when silently shipping the wrong output
is worse than a visible outage. When to omit it: when a transient failure is
more likely than a real regression and a notify-only pager is enough.

## Test-tag conventions

- **`@post-deploy`** — fast (< 30s total for the tagged subset) smoke tests.
  Run on every regen. These must be robust to brief upstream hiccups (retry
  transient network failures inside the test) and exercise only the behaviors
  a regen could break: data freshness, core chart render, key-number sanity.
- **`@full-qa`** (optional) — PR-only comprehensive suite. Not run on regen.
- **Untagged** — runs in both. The default; most tests live here.

Projects tag intentionally: `@post-deploy` is a **budget**, not a badge.
Every tagged test is 30+ seconds out of the regen path every cycle.

## Related skills

- `SKILLS/visual-lint.md` — deterministic B-plus assertions are an excellent
  fit for `@post-deploy`-tagged tests: they're fast, robust, and catch the
  class of bug (raw entities, empty charts, scroll traps) that regens
  specifically introduce.
- `SKILLS/data-audit-qa.md` — Phase 5 display-layer sanity ranges can be
  invoked as a `@post-deploy`-tagged Python script rather than a Playwright
  test; the hook's config template accepts any shell command.
- `SKILLS/code-hygiene.md` — the hook itself follows the required bash
  preamble (`set -eE -o pipefail` + ERR trap + recursion guard); projects
  writing adoption glue should do the same.

## Operator runbook (quick reference)

- **Inspect what ran:** `tail -50 /var/log/post-deploy-qa.log`.
- **Check if a project is frozen:** `ls /var/run/auto-deploy-frozen-*`.
- **Unfreeze:** `rm /var/run/auto-deploy-frozen-<project>`.
- **Dry-run the hook manually:**
  `/usr/local/bin/post-deploy-qa-hook.sh <project> <live_url>` — reads the
  same conf, writes to the same log, respects the same lock.
- **Disable a project's hook without removing the conf:** comment out its
  row in `/opt/site-deploy/helpers/post-deploy-qa.conf` and let auto-deploy
  sync. The hook silently skips projects with no matching row.
