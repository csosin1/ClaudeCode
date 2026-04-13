# abs-dashboard — Project State

_Last updated: 2026-04-13 by Claude_

## Current focus
Building out the Default Model tab's lifetime-loss-forecast build-up table. A first cut using industry-standard roll-to-loss multipliers (20/50/85% by DQ bucket) shipped as commit e88e06e. User pushed back ("don't use broad estimates — use all available data"). In-flight: replacing the multipliers with an empirical Markov absorption-probability model computed from loan_performance transition history. First attempt produced degenerate results and is NOT shipped; diagnosed two bugs (see Open questions).

## Last decisions
- DQ definition throughout dashboard uses the cert's 31-60 + 61-90 + 91-120 buckets (not ABS-EE's dq_120_plus, which carries pre-charge-off loans). Matches servicer-cert convention. (1cfeb72)
- Cumulative loss values pulled from the cert's "(98) aggregate Net Charged-Off" line, not from summing monthly ABS-EE flow — the latter undercounts for deals with ingestion gaps. (bad0ea5)
- Original pool balance parsed from cert line (14), not MAX(beginning_pool_balance) — fixes 2021-P1 which had been showing $399M vs true $415M. (bad0ea5)
- Servicer-cert parser switched from fixed field numbers (fragile across vintages) to label-based lookup. (1cfeb72)
- ABS-EE ↔ 10-D linker widened from same-day to ±3-day to recover missing months. (1cfeb72)
- Loss forecast uses per-deal severity (1 − cum_liq/cum_gross) rather than a flat industry assumption. (e88e06e)

## Open questions
- Empirical Markov forecast has two unresolved bugs before it can ship:
  1. `ORDER BY reporting_period_end` in loan_performance sorts the "MM-DD-YYYY" string lexicographically, scrambling each loan's chronological trajectory. Need to sort via a date-typed key (e.g., substr reordering to YYYY-MM-DD, or add a sortable column).
  2. Every row where `zero_balance_code='03'` (charge-off) has `current_delinquency_status=NULL`, so the state-at-default is never captured. Need to carry forward the last non-null status per loan and use that as the "from-state" of the terminal transition.
- Whether to compute transition probabilities at the tier level (Prime vs Non-Prime) or per-deal. Tier level gives more data per cell; per-deal respects underwriting drift but is noisy for newer deals.

## Next step
`carvana_abs/default_model.py`: add a `build_transition_matrix(tier_deals)` function that (a) sorts loan_performance chronologically via a year-month-day derived key, (b) carries forward the most recent non-null `current_delinquency_status` per loan so terminal-default transitions attach to the last observed state, (c) computes the fundamental matrix N = (I − Q)⁻¹ and absorption B = NR. Store the per-tier P(default | state) vector alongside the existing `lifetime_forecast_by_deal` segment. Then replace the 20/50/85 heuristic in `generate_dashboard._loss_forecast_buildup_tables` with the learned Markov probabilities.
