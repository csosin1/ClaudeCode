# Gym Intelligence — Project State

_Last updated: 2026-04-15 ~00:00 UTC by Gym Intelligence session (slug: gym-intelligence)_

## Current focus
**Historical backfill approach failed — Overpass attic unusable for our query shape.** Built the 4-year quarterly historical pipeline (commits 50c727f + 2a7e2ad), started the real collection, got 1 quarter in (2022-06-30) that returned only 256 locations across 6 countries vs 41,754 present-day — a ~99% data loss that the trend column on preview exposed immediately. Diagnosed via four direct Overpass tests: the main `overpass-api.de` mirror accepts `[date:"..."]` syntactically (200 OK) but silently returns 0 elements for bbox+tag queries at ANY date, including 2026. A plain (non-attic) query to the same mirror returns the expected thousands. The pipeline itself is correct; the external API doesn't support our query shape. Preview DB cleaned (bad 2022 rows wiped; trend column back to hidden since only 1 snapshot_date remains). Live was never touched. Full post-mortem in `/opt/site-deploy/LESSONS.md` entry 2026-04-14.

**Awaiting user decision on the alternative data source.**

## Last decisions
- **Abandon Overpass attic as the historical data source.** The attic code in `collect.py`/`historical_backfill.py` stays in the repo because the code is correct — the issue is Overpass infrastructure, not our implementation. It won't be invoked again until we have a history-enabled mirror we've validated.
- **Recommended next source: Wayback Machine store-locator scraping.** Archive.org stores Basic-Fit/clever fit/Fitness Park/etc. store-locator pages historically. For our top ~20 chains by location count × 16 quarters = ~1,600 archive fetches, ~1-2 hrs wall-clock, no API cost. Gives authoritative per-chain numbers (better than OSM even where OSM works), limited to chains with machine-readable locators (most big ones do).
- **Competitors-only toggle (default ON), ownership pills, Municipal competitors counter, 99-direct-competitor reclassification — all live as of commit 10639b9 / rollback tag rollback-gym-20260414-045932.** Promote completed at ~05:00 UTC. Live DB is the superset of preview (same data, no ownership regressions).
- **Live venv orphan purge shipped (commit 93cc898).** `/opt/gym-intelligence` went 580MB → 30MB. Deploy script now idempotently purges Streamlit-era packages on every run.
- **Altafit is flagged municipal competitor in live — almost certainly wrong** (it's a private Spanish budget chain). User accepted "ship it" knowing this; pending manual flip or re-run.

## Open questions
- **Which alternative historical source does the user want?** Wayback (my recommendation), planet-file history dump (heavy), or chain financial disclosures (authoritative but spotty coverage). Needs one answer before I dispatch builders.
- **Droplet capacity still warn.** Swap 69.7%, disk 78.5% as of the evening check. The venv purge reclaimed 550MB disk on live but swap usage persists and belongs to a different process (not ours). Separate RCA or a resize is the permanent fix.
- **23 chains still `unknown` classification** — awaiting Anthropic's web_search tool capacity to clear before retrying.

## Next step
**Await user direction on historical-data source.** When they say Wayback: dispatch a single Builder (not parallel — this is sequential Archive.org fetch + parse, single file `gym-intelligence/wayback_scraper.py`), wire results into the same `snapshots` table (schema already supports it), let the existing trend column render them. If user instead says "skip historical, focus elsewhere" — close out the feature, leave the trend column code hidden, update PROJECT_STATE with the close.

No uncommitted code in worktree. Main is at commit 50c727f (backfill build + fix) + the pending LESSONS.md/state-file updates from this session. Pending commit + push will land those.
