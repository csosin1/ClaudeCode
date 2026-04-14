# gym-intelligence — Project State

_Last updated: 2026-04-14 end-of-day by gym-intelligence session_

## Current focus
**Queued for tomorrow: build a historical time-series of chain location counts over the last 4 years.** User approved the plan tonight ("Do the last 4 yrs quarterly") but the build did not start — stopped at the end-of-day checkpoint. Scope is locked, files identified, ready to dispatch to Builder(s).

**Shipped earlier today (live as of ~05:00 UTC):**
- Competitors-only toggle on Market tab (default ON) — /api/chains-table?show=all opens the full 31k view.
- Reclassify of 145 unknowns → 99 direct_competitors (was 45), 60 OSM-noise in `not_a_chain`, 23 still unknown.
- Ownership axis (private/public/unknown) added to schema + backfilled on 308 classified ≥4-loc chains → 184 private / 87 public / 37 unknown.
- Public pill + Municipal competitors counter on the Market tab.
- Promoted with rollback tag `rollback-gym-20260414-045932`; previous live DB backed up at `/opt/gym-intelligence/gyms.db.pre-promote-20260414-050012`.

## Last decisions
- **Use Overpass attic queries for history, not a separate data source.** Same free API already in `collect.py`; adds one `[date:"YYYY-MM-DDTHH:MM:SSZ"]` header. No new infra, no API cost. Noise from OSM tagging-lag is acceptable within the 4-year window (~85-95% coverage in our six countries).
- **4 years, quarterly end-dates** — 16 total snapshot_dates. 15 historical to collect (2022-06-30 through 2026-03-31); present-day snapshot from 2026-04-12 already exists in DB.
- **Chain matching uses the current-day `chains` table** — historical gyms of chains we don't know today get dropped. This is intentional: a now-defunct obscure chain adds noise, not signal, to Basic-Fit's competitive view.
- **Altafit flagged as municipal competitor is probably wrong but was shipped as-is.** User said "ship it" knowing this. Flip to private or re-run municipal detection on the competitor set in a follow-up.

## Open questions
- **Wall-clock budget for the 4-year backfill.** Overpass attic queries are ~2-3× slower than present-day; 15 snapshots × 6 countries × 3 tag-types could be 6-12 hours. Some Overpass mirrors refuse attic queries or heavily rate-limit them — will need mirror-failover logic same as the present-day collector. Fine for an overnight background run.
- **Dashboard visualization format.** Could be (a) a trend column on the Market tab per competitor (sparkline + absolute Δ), (b) a dedicated Trends tab, or (c) Δ-YoY badge next to location count. No user preference captured yet; Builder should propose the lightest one and let QA show it.
- **23 chains still `unknown` in classification** — waiting on Anthropic's web_search tool capacity to clear before retrying. Plain-model retry already done; further progress needs live web lookups.

## Next step
Dispatch two Builder subagents in parallel (per the Parallel Builders rule):

1. **Backend builder** touches only: `gym-intelligence/collect.py` (add `--as-of YYYY-MM-DD` flag, inject `[date:"..."]` header into each Overpass query, write rows to `snapshots` with matching date), `gym-intelligence/historical_backfill.py` (new runner that iterates the 15 quarter-end dates and calls the collector), unit tests in `gym-intelligence/test_historical.py`.

2. **Frontend builder** touches only: `gym-intelligence/app.py` (new `/api/chain-history?chain=...&country=...` endpoint that reads from `snapshots`), `gym-intelligence/templates/index.html` (trend sparkline or Δ-YoY column on the Market tab, hooked off the existing chain-table row renderer), Playwright assertions in `tests/gym-intelligence.spec.ts` guarded by `base.label === 'preview'`.

After both return: single Reviewer pass on the combined diff, merge to main, run `historical_backfill.py` in background (foreground Builder keeps only unit tests with Overpass mocked; the real 6-12h collection happens after code ships to preview). Share preview URL when first 2-3 quarters have landed so user has something to look at even before the full run completes.

No code changes uncommitted tonight; main is at commit 10639b9, pushed.
