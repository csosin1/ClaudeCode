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

**New follow-up (non-blocking):** PK-collision sweep found 26 orphan filings (8 Carvana benign — rescue rows already captured via 10-D/A; 18 CarMax = lost amendments, mostly 8-year-old, low magnitude). Fix requires parser collision-resolution rule (prefer /A, else latest filing_date) + batch re-ingest. Queue for next session.

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
