# Builder CHANGES — longitudinal 5y surveillance + HGV segmentation

## What

1. **Persistent SEC disk cache** — new `pipeline/sec_cache.py` wrapping primary-doc HTML, companyfacts XBRL JSON, and submissions index. Cache root: `data/sec_cache/`. HTML is keep-forever (SEC primary docs are immutable per accession); XBRL + submissions are TTL-gated (`SEC_CACHE_XBRL_TTL_HOURS`, default 168). Atomic writes via tempfile + `os.replace`. Stale-on-network-failure fallback for XBRL/submissions. Non-2xx responses are never persisted.
2. **5-year backfill** — `LOOKBACK_FILINGS` 4 → 25.
3. **Segment-aware schema + extractor** — added `segments` array to `METRIC_SCHEMA`, `schema.sql`, `db.py` (idempotent `ALTER TABLE` so existing DBs upgrade in place). Narrative section `portfolio_segments` with widened window (2k before / 18k after, 2× excerpt cap). Segment-specific Claude prompt that constrains `segment_key` to the canonical per-ticker enum and instructs Claude to return a single `consolidated` entry when no breakout is disclosed. `_merge_xbrl_and_narrative` ensures narrative wins for `segments`. Other sections cannot overwrite `segments` mid-merge.
4. **Dashboard rebuild** — `dashboard/index.html` is now a longitudinal time-series view: 9 small-multiple line charts (90+ DPD, total DPD, allowance coverage, provision $mm, weighted FICO, FICO <600, gain-on-sale margin, ABS advance rate, originations $mm), date-range pills (1y / 3y / 5y / all, default 5y), HGV-breakdown switch with brand vs acquisition-cohort sub-toggle. Latest-snapshot strip retained per ticker with severity colour + management-flagged pill. Empty-state ("pipeline warming up" with spinner) when `combined.json` is `[]`. Mobile-first: 1 col @390, 2 cols @md, 3 cols @lg.
5. **Deploy script** — rsync excludes `data/sec_cache/*` (keeps `.gitkeep`); ensures dir + `.gitkeep` exist for both LIVE/PREVIEW after rsync. Source tree carries `data/sec_cache/.gitkeep` so git tracks the directory.
6. **Tests**
   - `tests-unit/test_sec_cache.py`: filing cache hit/miss, atomic write (no stray `.tmp`), refusal-to-cache non-2xx, XBRL TTL hit + expiry refetch, stale-serve on network failure, submissions cache hit. 7 tests, all green together with the existing 17 — `24 passed`.
   - `tests/timeshare-surveillance.spec.ts` rewritten for the new dashboard: 200 + header + no console errors, snapshot-strip 3-ticker, 9 chart cards, 5y default-active pill, 1y reduces (or holds) x-axis ticks, HGV-breakdown toggle adds ≥2 segment lines. All assertions degrade gracefully to `test.skip` when combined.json is empty.

## Files touched

- `timeshare-surveillance/config/settings.py` — `SEC_CACHE_DIR`, `SEC_CACHE_XBRL_TTL_HOURS`, `LOOKBACK_FILINGS=25`, `portfolio_segments` patterns.
- `timeshare-surveillance/pipeline/sec_cache.py` — new.
- `timeshare-surveillance/pipeline/xbrl_fetch.py` — `load_companyfacts` routed through `sec_cache.get_xbrl_facts`.
- `timeshare-surveillance/pipeline/fetch_and_parse.py` — `_list_filings` via `sec_cache.get_submissions`; primary-doc fetch via `sec_cache.get_filing_html`; `segments` carried through merge; HGV/VAC/TNL dry-run stubs gain canonical-key `segments` lists.
- `timeshare-surveillance/pipeline/metric_schema.py` — `segments` schema entry; `null_record()` defaults to `[]`.
- `timeshare-surveillance/pipeline/schema.sql` — `segments TEXT` column.
- `timeshare-surveillance/pipeline/db.py` — `_JSON_COLS` tuple; idempotent `ALTER TABLE filings ADD COLUMN segments TEXT` in `init_db`; row-to-record deserialises both JSON cols.
- `timeshare-surveillance/pipeline/narrative_extract.py` — `portfolio_segments` SECTION_FIELDS entry, widened window, segment-specific prompt with canonical-key list, parser branch for `segments`, merge-guard so other sections cannot clobber.
- `timeshare-surveillance/dashboard/index.html` — full longitudinal rewrite (single file, no build).
- `timeshare-surveillance/data/sec_cache/.gitkeep` — new.
- `timeshare-surveillance/tests-unit/test_sec_cache.py` — new (7 tests).
- `deploy/timeshare-surveillance.sh` — rsync excludes `data/sec_cache/*`; mkdirs/.gitkeep for live + preview.
- `tests/timeshare-surveillance.spec.ts` — rewritten for new dashboard.

## Risks / caveats for the Reviewer

- **Real-EDGAR segment extraction is unverified.** Dry-run stubs prove the schema + dashboard plumbing end-to-end, but Claude's segment-prompt has not been exercised against a live HGV 10-K yet (per spec, the orchestrator runs the 5-year backfill). If Claude returns `segment_key` values outside the canonical enum, our `_call_claude` parser keeps them — only obvious junk (non-string keys) is dropped. The dashboard tolerates unknown keys by ignoring them when building HGV segment series, but unknown keys still land in the DB unfiltered. We may want stricter post-validation after the first real run.
- **Dashboard segment toggle gracefully degrades** but only for HGV. VAC/TNL segment data is captured in the DB and exposed in `combined.json`, but the dashboard does not currently surface it (per spec — only the HGV breakdown is requested). VAC/TNL lines remain consolidated even when their per-brand segments are present.
- **Cache TTL applies even when the run is `--refresh`**: `refresh=True` is plumbed through `get_xbrl_facts`/`get_submissions`/`get_filing_html` but not yet exposed as a CLI flag. Operator must delete the `data/sec_cache/<...>` files (or pass `refresh=True` programmatically) to force a re-fetch. The spec says "or `refresh=True` kwarg" so the CLI flag is left for a follow-up.
- **`init_db` idempotency:** the `ALTER TABLE` runs every init; SQLite's `PRAGMA table_info` check makes it a no-op after the first run. Cheap.
- **Dashboard removed several panels** (FlagPanel, KPI scorecard, peer table, vintage curves, commentary). Per spec the new structure is snapshot strip + time-series grid only. Threshold/red-flag email logic in `red_flag_diff.py` is untouched and unaffected.
