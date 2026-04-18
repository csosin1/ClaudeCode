# Carvana Loan Dashboard — Project State

_Last updated: 2026-04-18 07:10 UTC — overnight 5-deal ingest + retrain complete._

## Overnight 2026-04-18 — 5 missing deals added, full retrain, live site updated

Discovery scanner (`deploy/discover_new_deals.py`) had flagged 5 deals that were never in the DEALS configs: Carvana 2021-P3, 2021-P4, 2025-P1, 2026-P1, and CarMax 2026-2. Overnight session added them to the DEALS registries, ingested all 5, retrained unified Markov on the expanded universe (57 deal_forecasts: 20 Carvana + 37 CarMax, up from 53), regenerated methodology analytics, regenerated + promoted dashboard.

**Commits (this session, in order):**
- `a9816a5` — Phase 1-2: configs + LESSONS entry
- `c3e0080` — audit_new_deals.py
- `72c5610` — audit_new_deals column-name fix
- `653c442` — xml_parser: handle combined FICO/Vantage score format (found during audit; 2026-P1 was 100% NULL FICO until this fix)
- `bcd602f` — deploy/overnight_post_markov.sh pipeline
- `3eeee8e` — audit_final_overnight.py
- (checkpoint commit) — final AUDIT_FINDINGS + PROJECT_STATE

**Live site:** https://casinv.dev/CarvanaLoanDashBoard/ — HTTP 200, last-modified 2026-04-18 07:03 UTC, 5.85 MB. All 4 new Carvana deals visible on the Residual Economics tab. CarMax 2026-2 is registered but dashboard filters render only deals with an initial_pool_balance; 2026-2 will auto-appear on its first 10-D servicer report.

**Final audit (Phase 8, `audit_final_overnight.py`):** 0 HALT, 0 WARN. Clean pass on first iter.

Full narrative in `AUDIT_FINDINGS.md` under "Overnight ingest iter — 2026-04-18".

_Prior state below (pre-2026-04-18 overnight) preserved for reference._

---

## Meta-goal (framing for ALL analysis)

**This dashboard exists to help the user understand Carvana's auto-ABS business insofar as it impacts Carvana (the company).** Carvana is the SUBJECT. CarMax is the BENCHMARK. Analysis, charts, narrative, and callouts should reflect this asymmetry:

- **Recent Trends tab:** lead with Carvana performance (Prime + Non-Prime). CarMax is the comparison peer, not a co-subject.
- **Methodology & Findings tab:** regression comparisons are valid, but findings should be framed as "what this means for Carvana" (e.g. if CarMax outperforms by X bps, that tells us about Carvana's underwriting spread vs. a legacy operator).
- **Residual Economics tab:** keep chronological but emphasize Carvana deals in any narrative summaries/callouts.
- **Deep-dives + spot checks:** prioritize Carvana's most-recent vintages (the deals still building their loss curve) — those are the ones that materially affect Carvana equity.

If an agent produces symmetric Carvana-vs-CarMax framing, that's acceptable but leaves value on the table. A morning framing pass should add Carvana-centric interpretation callouts where the compute already lives.

## Host topology (MUST OBEY)

**abs-dashboard runs on PROD, not dev.** Overnight migration 2026-04-16/17 moved `/opt/abs-dashboard/` to the prod droplet (10.116.0.3, `ssh prod-private`, 8GB RAM, 4 CPUs, 154GB disk). Dev copy at 159.223.127.125 is a rollback snapshot only — any writes to dev paths are discarded within 48hr; dev is memory-constrained (4GB, shared with other projects) and will OOM under real workloads.

**Rule for every compute task:**
- Markov training / forecast runs: `ssh prod-private /opt/abs-venv/bin/python /opt/abs-dashboard/unified_markov.py`
- Methodology analytics (regressions, benchmark fetches, heavy Python): same — `ssh prod-private`
- Dashboard regen + promote: `ssh prod-private` 
- Audits, spot-checks, one-off scripts: run on prod against prod DBs
- Watchers (poll-until-cache-exists): `ssh prod-private 'until [ -f ... ]; do sleep ...; done'` — poll prod, not local
- Dev is ONLY for git commits that must push to origin (prod has no GitHub credentials) and for ssh-outbound to prod

**Incidents log (for context):** 2026-04-17 11:00 UTC Markov launched on dev → OOM → moved to prod. 2026-04-18 02:40 UTC compute_methodology.py launched on dev → swap pressure urgent → moved to prod. Both should have gone to prod from the start. Root cause both times: main session shell is on dev, so `bash` tool runs dev-local unless prefixed with `ssh prod-private`. Fix going forward: **any heavy command must start with `ssh prod-private`**.

## Current focus
**All 9 audit items resolved — data trusted and live.** Full audit per SKILLS/data-audit-qa.md completed 3 iterations to clean-pass. Post-fix audit (1,395-tuple sample + 3-cell spot-check) reconfirmed data trusted after display changes landed. Live dashboard regenerated + promoted with all fixes. Fix commits:
- `bc40ba5` Carvana parser (reserve row + early-cycle)
- `84a7ebb` CarMax parser (tranche class-name + Ending Balance reserve)
- `1037f00` lex-date sort (dist_date_iso column + 11 query rewrites)
- `346ec51` CarMax 2025-2 re-ingest (PK-collision from stale issuer header)
- `0413c62` dashboard renderer (CarMax Notes & OC tab + restatement flag + DQ tail suppression)
- `1a91324` post-fix audit report

**PK-collision follow-up: RESOLVED** (`40b815d`). Both parsers now resolve (deal, distribution_date) PK collisions explicitly: amendments win over plain filings, later filing_date wins ties, and a 30-day stale-header guard skips writes when extracted distribution_date disagrees egregiously with filing_date. All 26 orphan filings re-ingested: **26 → 0**. Collision decisions logged to `<issuer>_abs/db/ingestion_decisions.log` for future audit. No regressions detected.

**All prior data issues closed.** Data trusted, live dashboard updated, 7 commits of fixes in this session.

**🟢 DELIVERY COMPLETE 2026-04-17 23:00 UTC.** Full build pipeline done + final QA PASS. Live at https://casinv.dev/CarvanaLoanDashBoard/
- 53 Markov deal_forecasts (16 Carvana + 37 CarMax)
- Residual Economics landing tab with real at-issuance, projected, realized values + cap structure + Other Terms col
- 1,978-word methodology writeup + state-transition diagram + worked examples
- Final commits: `127a6a4` (rendering 100× bug fix), `600cf79` (numpy vectorization, 14× speedup), `ce22886` (Markov OOM + incremental save), `71b28e2` (chunk=12), `71f18e2` prior audit pass
- Non-blocking follow-on: Trigger Risk column shows "—" (Markov doesn't yet emit OC-breach probability; follow-on task to add to unified_markov.py)
- Fix-forward: vectorized forecast_loan validated to 2e-13 float precision against legacy loop; independent numerical cross-check of the model math

**State snapshot when paused:**
- CarMax loan-level: 37/37 deals, 3.1M loans. Audit clean. F-019 fixed (2019-3 loan_loss_summary recomputed).
- Deal_terms: 65/67 deals extracted. Audit: 4 parser bugs fixed (a175004). 2021-N1 $40B bug corrected, DQ triggers extracted, note structures cleaned.
- Markov: code committed (30e3546), last run OOM'd mid-forecast after 25 of 53 deals. Fix applied: offload all_latest dict to disk (temp SQLite) during forecast phase so RAM stays < 500 MB. **NOT YET VERIFIED E2E** — process killed before completing with the fix.
- Residual-economics tab: LIVE with logistic-regression placeholders (commit 54a3556). Will auto-upgrade to real Markov forecasts when deal_forecasts table is populated on next regen.
- Dashboard DBs and live site reflect everything EXCEPT the Markov forecasts.

**Resume playbook (post-infra):**
1. `cd /opt/abs-dashboard && nohup /opt/abs-venv/bin/python unified_markov.py > /var/log/abs-dashboard/markov_run.log 2>&1 &` — relaunch Markov (idempotent: rebuilds from DB).
2. Wait ~3hr (training ~80min + offload 2min + forecasts ~90min + save 2min).
3. Re-export dashboard DBs: `/opt/abs-venv/bin/python -m carvana_abs.export_dashboard_db && /opt/abs-venv/bin/python -m carmax_abs.export_dashboard_db`
4. Regenerate + promote: `/opt/abs-venv/bin/python carvana_abs/generate_preview.py && /opt/abs-venv/bin/python carvana_abs/generate_preview.py promote`
5. Dispatch final QA audit (MAX_ITER=10).
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
