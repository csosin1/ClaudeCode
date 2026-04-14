# abs-dashboard — Project State

_Last updated: 2026-04-14 (end-of-day checkpoint by Claude)_

## Current focus
Wiring CarMax into the dashboard end-to-end (loan-level data → Bayesian loss forecast → dashboard buildup table) to parity with Carvana. Two long-running background jobs are in flight as of this checkpoint; Wave 2 + 3 (integration + audit) will pick up when both land.

## Last decisions
- **Vintage-blind baseline** in the conditional-Markov transition model. User's framing: "same pool → same expected loss content; vintage differences emerge through loss development, not prior." The vintage covariate is removed from the cell key; vintage effects flow entirely through the per-deal Bayesian calibration overlay.
- **Deal-weighted training** (not loan-weighted). Each pool contributes equal weight to transition cell estimates regardless of loan count, so 2022's big pools don't dominate 2020's smaller ones. Implemented as `weight = 1 / n_loans_in_deal` on every transition observation; raw counts kept separately to gate the `MIN_CELL_OBS=30` sparse-cell fallback.
- **Bayesian log-normal conjugate calibration** replaces the earlier [0.5, 2.0] clamp + 6-month floor. Prior `log(cal) ~ Normal(0, σ_prior² = 0.09)` (σ_prior = 0.30 → 68% prior CI [0.74, 1.35]). Likelihood σ_obs shrinks as realized dollars grow (∝ 1/√N). Posterior gives smooth credibility weighting and a real ±1σ band that flows through to the total-loss interval on the buildup table.
- **CarMax XML filename pattern** discovered: CarMax names the ABS-EE main loan tape `cart<deal>.xml` (e.g. `cart20201.xml`), not Carvana's `ex102-*.xml` convention. Linker in `carmax_abs/ingestion/filing_discovery.py` now handles both.
- **Large XML files excluded from git.** CarMax ABS-EE XMLs average ~100MB each × ~1,400 files = 13GB. Added `carmax_abs/filing_cache/*.xml` to `.gitignore`.

## Open questions
- **2025 Prime forecast magnitude.** Deal-weighted re-training (v7) is running now and expected to lower the 2025 Prime forecasts from ~4.2% toward ~3.0-3.5%. If v7's shift is not enough, the next tool is macro-aware transitions (unemployment + used-car-price index as covariates), which is a multi-day project. **Verdict pending v7 completion + 2025 forecast check.**
- **Dashboard CarMax loan-level sections** currently show placeholders ("loan-level ingestion not complete"). Will light up once the XML ingest job (PID 151524) finishes and Agent B integrates the CarMax forecast.
- **Cross-issuer Bayesian cal** — once CarMax has per-deal cal factors, worth confirming the interpretation is the same across issuers (same Prime tier, same baseline, so cal_factor for CarMax 2020-1 vs Carvana 2020-P1 should be comparable as "vintage effect vs cross-issuer average").

## Next step

### In-flight background jobs (should land 2026-04-14 early-hours UTC)
1. **cmarkov_v7** — PID 157451, log `/tmp/cmarkov_v7.log`. Deal-weighted conditional Markov retrain. Aggregation phase done as of checkpoint; per-loan forecast in progress. Expected complete ~05:30 UTC. When done:
   - Verify 2025 Prime forecasts drop to ~3.0-3.5% range
   - Apply Bayesian cal fixup to saved JSON (same math used in v6 fixup, see recent commits)
   - `carvana_abs/generate_preview.py` → promote
2. **CarMax XML ingestion** — PID 151524, log `/tmp/cmx_absee.log`. Downloading + parsing ~1,400 ABS-EE XMLs into `carmax_abs/db/carmax_abs.db` `loan_performance` + `loans` tables. Average XML ~100MB, per-file parse ~2-3min. Currently mid-2017-2 as of checkpoint. Expected complete ~2-3 hours from 04:00 UTC. When done:
   - Verify `carmax_abs.db` `loan_performance` has multi-million rows and `loans` populated
   - Rebuild CarMax `monthly_summary` + `loan_loss_summary` via `carmax_abs.rebuild_summaries` (may need to be copied from carvana)
   - Re-export CarMax dashboard DB via `carmax_abs/export_dashboard_db.py`

### Wave 2 (once Wave 1 lands) — autonomous via scheduled wakeup at 05:36 UTC
3. Spawn parallel Builder agents:
   - **Agent A — CarMax data auditor**: Compare `carmax_abs` pool-level data to raw cert HTMLs for ~10 deals. Verify cum losses, pool balance, DQ bucket reconciliation, loan count vs expected. Spot-check ≥50 random XML-derived loan records against raw XML. Report any anomalies.
   - **Agent B — CarMax conditional Markov**: Extend `carvana_abs/conditional_markov.py` (or clone to `carmax_abs/`) to treat CarMax as its own tier. Must reuse the same age / FICO / LTV bucketing; deal-weighted training; Bayesian cal overlay. Output saved to `carmax_abs/db/dashboard.db` `model_results` under key `conditional_markov`.
4. Merge both agent outputs. Update `carvana_abs/generate_dashboard.py` (the site-wide renderer) so the Default Model tab's loss-buildup table shows Carvana AND CarMax blocks with matching columns (including Bayesian ±1σ and cohort cal).
5. Add FICO / LTV / avg-rate / avg-term / severity columns to the CarMax summary table once loan tape is ingested.

### Tomorrow morning (user-facing wrap)
6. Regen preview, promote to live, commit + push.
7. Update PROJECT_STATE.md with final status (what shipped, any caveats, known small issues).

### Clean restart path if this session is killed
- Working tree has uncommitted changes in `carvana_abs/conditional_markov.py` (deal-weighted v7 changes) and `carmax_abs/ingestion/filing_discovery.py` (CarMax XML filename pattern). Both will be committed at next checkpoint; see the commit immediately following this doc's publication for the exact shas.
- Current live deploy is commit `8c84143` (Bayesian v6, still correct for Carvana, vintage-blind baseline, NOT yet deal-weighted). If overnight work fails and this is what remains, user has a working dashboard at https://casinv.dev/CarvanaLoanDashBoard/ — just missing the CarMax loan-level integration and the v7 forecast shift.
- If the XML ingestion job dies, re-run with: `SEC_USER_AGENT=... nohup /opt/abs-venv/bin/python -m carmax_abs.run_ingestion > /tmp/cmx_absee.log 2>&1 &`
- If v7 dies mid-way, re-run with: `nohup /opt/abs-venv/bin/python -m carvana_abs.conditional_markov > /tmp/cmarkov_v7.log 2>&1 &`
- Both jobs are idempotent (re-running won't corrupt the DB).

### Key file paths
- Carvana conditional Markov: `carvana_abs/conditional_markov.py` (only one; v7 edits in place)
- Dashboard renderer: `carvana_abs/generate_dashboard.py` (whole site, issuer-aware)
- CarMax ingestion: `carmax_abs/ingestion/{filing_discovery,xml_parser,servicer_parser,ingest}.py`
- CarMax config (49 deals 2014-1 → 2026-1): `carmax_abs/config.py`
- Cloudflare cache-purge script: `deploy/cf_purge.sh` (no-op until `CF_API_TOKEN` + `CF_ZONE_ID` added to `/opt/abs-dashboard/.env`)
- Daily ingest cron: `deploy/cron_ingest.sh` at 14:17 UTC
