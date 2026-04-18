# Dashboard Audit Manifest

Enumeration of every chart/table/KPI on https://casinv.dev/CarvanaLoanDashBoard/.
Renderer: `/opt/abs-dashboard/carvana_abs/generate_dashboard.py`.
Sources: `carvana_abs/db/dashboard.db`, `carmax_abs/db/dashboard.db`.

Tab structure: the dashboard has a top-level selector that chooses between
**one of five comparison/model views** OR **one of 16 Carvana per-deal tabs** OR
**one of 49 CarMax per-deal tabs**. Each per-deal tab then has 4-6 sub-tabs.

Legend for "Kind":
- **D** = direct data (comes straight out of a DB column)
- **A** = aggregated (cumsum / ratio / groupby of direct columns)
- **M** = model-derived (forecast, ML prediction, or external simulation — **out of scope per user**)

Deal universe:
- Carvana: 16 deals ([2020-P1, 2021-N1..N4, 2021-P1..P2, 2022-P1..P3, 2024-P2..P4, 2025-P2..P4]); 12 Prime + 4 Non-Prime
- CarMax: 49 deals (2014-1 through 2026-1, all Prime)
- Tuple totals: `monthly_summary` 606 (Carvana only), `pool_performance` 607 (Carvana) + 2,004 (CarMax)

---

## Top-Level View 1 — Default Model

Function: `generate_model_content()` (lines 2387-2545). Pulls `model_results` JSON from `dashboard.db` + embeds `_loss_forecast_buildup_tables()`.

| # | Section / Chart Title | Metrics | Source | N | Kind |
|---|---|---|---|---|---|
| 1 | Dataset Summary (KPI strip) | total_loans, defaults, default_rate, train_size, test_size | `model_results.default_model.dataset` | 5 scalars | M |
| 2 | Lifetime Loss Forecast Build-Up — Prime (table) | Active Loans, Realized $/%, DQ Pipeline $, Performing Future $, Cohort Cal, Total -1σ/mid/+1σ, Total % | `model_results.conditional_markov.by_deal` | 12 Prime deals | M |
| 3 | Lifetime Loss Forecast Build-Up — Non-Prime (table) | same columns | `model_results.conditional_markov.by_deal` | 4 Non-Prime deals | M |
| 4 | One-month transition probabilities — Prime (top 30 cells) | State, Age, FICO, n obs, P(Default) 1mo, P(Payoff) 1mo | `model_results.conditional_markov.p_default_reference.Prime` | 30 rows | M |
| 5 | One-month transition probabilities — NonPrime (top 30 cells) | same columns | `model_results.conditional_markov.p_default_reference.NonPrime` | 30 rows | M |
| 6 | Model Performance (table) | Accuracy, AUC-ROC, Precision, Recall, F1 | `model_results.default_model.models` | 2 rows (LR, RF) | M |
| 7 | ROC Curve | fpr/tpr + random diagonal | `models[*].roc_curve` | 2 curves | M |
| 8 | Feature Importance (Random Forest) bar | feature → importance | `models.random_forest.feature_importance` | ~10 features | M |
| 9 | Logistic Regression Coefficients bar | feature → coef | `models.logistic_regression.coefficients` | ~10 features | M |
| 10 | Confusion Matrix — Logistic Regression | 2×2 counts | `models.logistic_regression.confusion_matrix` | 1 table | M |
| 11 | Confusion Matrix — Random Forest | 2×2 counts | `models.random_forest.confusion_matrix` | 1 table | M |
| 12 | Default Rate by FICO Score (grouped bar + table) | actual_rate, predicted_rate, loans per FICO bucket | `model_results.default_model.segments.by_fico` | ~8 buckets | M |
| 13 | Default Rate by Origination Year (grouped bar + table) | same | `segments.by_vintage` | ~5 years | M |
| 14 | Default Rate by LTV (grouped bar + table) | same | `segments.by_ltv` | ~6 buckets | M |
| 15 | Default Rate by Interest Rate (grouped bar + table) | same | `segments.by_rate` | ~8 buckets | M |
| 16 | Loss Severity (KPI strip) | total_defaulted, avg_chargeoff, avg_recovery, avg_net_loss, recovery_rate, median_chargeoff | `segments.loss_severity` | 6 scalars | M |

**All Default-Model view items are model-derived (M) — out of scope for data audit.**

---

## Top-Level View 2 — Prime Comparison (Carvana)

Function: `generate_comparison_content(PRIME_DEALS, "Prime Deals")` (lines 1844-2290). 12 Prime deals.

| # | Section / Chart Title | Metrics | Source | N | Kind |
|---|---|---|---|---|---|
| 1 | Prime Deals — Summary (table) | Deal, Avg FICO, Init/Curr Avg Consumer Rate, Init/Curr Avg Trust CoD, Init Balance, Pool Factor, Cum Loss, Equity Dist | `loans` (FICO, rate), `pool_performance.weighted_avg_apr`, `monthly_summary.weighted_avg_coupon`, `notes.coupon_rate/original_balance`, `pool_performance.total_note_interest/aggregate_note_balance/residual_cash/ending_pool_balance`, cert-parsed cum-net-loss | 12 rows × 10 cols | A |
| 2 | Prime Deals — Cumulative Net Loss Rate by Deal Age | cert-parsed cumulative net loss / orig_bal, x = deal age months | `_cum_net_loss_series()` → latest 10-D servicer cert per distribution date | 12 deal curves, ≈385 pts | A |
| 3 | Prime Deals — Pool Factor by Deal Age | total_balance / orig_bal | `monthly_summary.total_balance` | 12 curves, 385 pts | A |
| 4 | Prime Deals — Cumulative Net Loss vs Pool Factor | (x = pool_factor, y = cum_loss_rate) | `pool_performance.ending_pool_balance` + cert cum-net-loss | 12 curves, ≤385 pts | A |
| 5 | Prime Deals — 30+ Day Delinquency Rate by Deal Age | (31-60 + 61-90 + 91-120) / ending_pool_balance, cert-parsed | `_cert_dq_series()` → servicer cert | 12 curves, ≈385 pts | A |
| 6 | Prime Deals — Annualized Net Charge-Off Rate by Deal Age | (period_chargeoffs − period_recoveries) × 12 / prev total_balance | `monthly_summary` | 12 curves, ≈373 pts (skip month 1) | A |
| 7 | Prime Deals — Excess Spread by Deal Age | WAC − CoD on collection-month alignment | `pool_performance.weighted_avg_apr`, `total_note_interest`, `aggregate_note_balance`, `notes` | 12 curves, ≈385 pts | A |

---

## Top-Level View 3 — Non-Prime Comparison (Carvana)

Function: `generate_comparison_content(NONPRIME_DEALS, "Non-Prime Deals")`. 4 Non-Prime deals (2021-N1..N4).

Same 7 items as Prime comparison, restricted to Non-Prime:
1. Non-Prime Deals — Summary table (4 rows)
2. Cumulative Net Loss Rate by Deal Age (4 curves, 221 pts)
3. Pool Factor by Deal Age (4 curves, 221 pts)
4. Cumulative Net Loss vs Pool Factor (4 curves, ≤221 pts)
5. 30+ Day Delinquency Rate by Deal Age (4 curves, 221 pts)
6. Annualized Net Charge-Off Rate by Deal Age (4 curves, ≈217 pts)
7. Excess Spread by Deal Age (4 curves, ≈221 pts)

All Kind=A.

---

## Top-Level View 4 — CarMax Prime Comparison

Function: `generate_carmax_comparison_content(CARMAX_PRIME_DEALS, "CarMax Prime Deals")` (lines 914-997). 49 CarMax deals.

| # | Section / Chart Title | Metrics | Source | N | Kind |
|---|---|---|---|---|---|
| 1 | CarMax Prime Deals — Summary (table) | Deal, Init/Curr Avg Consumer Rate, Init Balance, Pool Factor, Cum Loss | `pool_performance.weighted_avg_apr/ending_pool_balance/cum_net_loss_derived` (CarMax DB) | 49 rows × 6 cols | A |
| 2 | CarMax Prime — Pool Factor by Deal Age | ending_pool_balance / orig_bal | CarMax `pool_performance` | 49 curves, ≈2004 pts | A |
| 3 | CarMax Prime — Cumulative Net Loss Rate by Deal Age | cum_net_loss_derived / orig_bal | CarMax `pool_performance.cum_net_loss_derived` | 49 curves, ≈2004 pts | A |
| 4 | CarMax Prime — Cum Net Loss vs Pool Factor | pair of (pool_factor, cum_loss) | CarMax `pool_performance` | 49 curves, ≤2004 pts | A |
| 5 | CarMax Prime — Total Delinquency Rate by Deal Age | total_delinquent_balance / ending_pool_balance | CarMax `pool_performance` | 49 curves, ≈2004 pts | A |
| 6 | CarMax Prime — Annualized Net Charge-Off Rate by Deal Age | net_charged_off_amount × 12 / beginning_pool_balance | CarMax `pool_performance` | 49 curves | A |
| 7 | CarMax Prime — Excess Spread by Deal Age | weighted_avg_apr − (total_note_interest / aggregate_note_balance × 12) | CarMax `pool_performance` | 49 curves | A |

---

## Top-Level View 5 — Carvana vs CarMax (Prime)

Function: `generate_cross_issuer_comparison()` (lines 1188-1266). Merges Carvana Prime (12) + CarMax (49) onto shared axes.

| # | Chart Title | Metrics | Source | N | Kind |
|---|---|---|---|---|---|
| 1 | Carvana vs CarMax (Prime) — Pool Factor by Deal Age | pool factor | Merged (same as views 2 & 4) | 61 curves | A |
| 2 | Carvana vs CarMax (Prime) — Cumulative Net Loss Rate by Deal Age | cum_loss_rate | Merged | 61 curves | A |
| 3 | Carvana vs CarMax (Prime) — Cum Net Loss vs Pool Factor | (pool_factor, cum_loss) | Merged | 61 curves | A |
| 4 | Carvana vs CarMax (Prime) — Delinquency Rate by Deal Age | DQ/pool (note: Carvana = cert 31-120, CarMax = total 31+) | Merged | 61 curves | A |
| 5 | Carvana vs CarMax (Prime) — Annualized Net Charge-Off Rate by Deal Age | annualized net CO rate | Merged | 61 curves | A |
| 6 | Carvana vs CarMax (Prime) — Excess Spread by Deal Age | WAC − CoD | Merged | 61 curves | A |

No new data — every series is a re-render of data shown in views 2 and 4. Can be sampled via those views.

---

## Carvana Per-Deal Tabs (16 deals × 6 sub-tabs = 96 sub-tab pages)

Function: `generate_deal_content(deal)` (lines 1269-1841). Emits metrics strip + 6 sub-tabs per deal. Counts per deal from `monthly_summary (ms)` and `pool_performance (pp)`:

| Deal | ms rows | pp rows | tier |
|---|---|---|---|
| 2020-P1 | 60 | 60 | Prime |
| 2021-N1 | 59 | 59 | Non-Prime |
| 2021-N2 | 57 | 57 | Non-Prime |
| 2021-N3 | 54 | 54 | Non-Prime |
| 2021-N4 | 51 | 51 | Non-Prime |
| 2021-P1 | 60 | 60 | Prime |
| 2021-P2 | 56 | 57 | Prime |
| 2022-P1 | 48 | 48 | Prime |
| 2022-P2 | 46 | 46 | Prime |
| 2022-P3 | 42 | 42 | Prime |
| 2024-P2 | 21 | 21 | Prime |
| 2024-P3 | 18 | 18 | Prime |
| 2024-P4 | 15 | 15 | Prime |
| 2025-P2 | 9 | 9 | Prime |
| 2025-P3 | 6 | 6 | Prime |
| 2025-P4 | 4 | 4 | Prime |
| **Total** | **606** | **607** | — |

### Metrics strip (each deal, 6 KPIs)
- Original Balance — `_cert_totals.orig_pool_balance` (fallback: SUM of `loans.original_loan_amount`) — **A**
- Current Balance — `_cert_totals.ending_pool_balance` (fallback: latest `monthly_summary.total_balance`) — **D**
- Pool Factor — current / original — **A**
- Active Loans — latest `monthly_summary.active_loans` — **D**
- Cum Loss Rate — cert-parsed cum_net_loss / orig_bal (fallback: monthly cumsum / orig_bal) — **A**
- 30+ DQ Rate — latest `_cert_dq_series` dq/epb (fallback: latest `monthly_summary` dq_rate) — **A**

### Sub-tab A — Pool Summary (every deal)
1. Remaining Pool Balance ($M) line+fill — `monthly_summary.total_balance` — D
2. Active Loan Count — `monthly_summary.active_loans` — D
3. Avg Consumer Rate (WAC) — `pool_performance.weighted_avg_apr` (fallback `monthly_summary.weighted_avg_coupon`; then flat line from `loans.original_interest_rate`) — D/A
4. Avg Trust Cost of Debt — merged Method 1 (`total_note_interest`/`aggregate_note_balance`×12) → Method 2 (weighted `notes.coupon_rate` × per-period note_balance_a1..n) → Method 3 flat from `notes` → Method 4 40% of avg loan rate — **A** (with model-ish fallbacks; methods 3-4 are heuristic fallbacks but not statistical models)

### Sub-tab B — Delinquencies (every deal)
5. Delinquency Rates (% of Pool) stacked area — `monthly_summary.dq_30/60/90/120_plus_balance` / `total_balance` — A
6. 60+ DQ vs Trigger Level — `pool_performance.delinquency_trigger_level` vs `delinquency_trigger_actual` (only where present) — D
7. Latest Period DQ table — latest row counts/balances/%s per bucket — D/A

### Sub-tab C — Losses (every deal)
8. Cumulative Net Loss Rate (filled area) — `(period_chargeoffs − period_recoveries).cumsum() / orig_bal` — A
9. Cumulative Gross Losses vs Recoveries (3 lines) — cumsum of chargeoffs, recoveries, net — A
10. Cumulative Recovery Rate — cum_rec / cum_co — A
11. Monthly Chargeoffs vs Recoveries (bar, grouped) — `period_chargeoffs`, `period_recoveries` — D
12. Losses by Credit Score (table) — groupby FICO bucket of `loans` LEFT JOIN `loan_loss_summary` — A
13. Losses by Interest Rate (table) — groupby rate bucket of same — A

### Sub-tab D — Cash Waterfall (every deal)
14. Monthly Collections & Losses (table, with TOTAL row) — `monthly_summary.interest_collected, principal_collected, period_recoveries, est_servicing_fee, period_chargeoffs, net_loss` — D
15. Cumulative Cash Flows (5 lines) — cumsum of above — A
16. Cash Waterfall (table, from servicer cert, Prime deals with pool_performance) — `pool_performance.total_deposited, available_funds, actual_servicing_fee, total_note_interest, regular_pda, residual_cash` — D
17. Cumulative Cash to Residual (% of Original Balance) — `residual_cash.cumsum() / orig_bal` — A
18. Debt & Equity (table) — `pool_performance.note_balance_a1..n, total_notes, overcollateralization_amount, reserve_account_balance` — D
19. Outstanding Debt Over Time (filled area) — `pool_performance.total_notes` (sum of note_balance_*) — A

### Sub-tab E — Recovery (every deal)
20. Recovery KPI strip (6 KPIs) — counts, recovery rate, median months — A
21. Months to First Recovery histogram — per-loan `first_recovery_period − chargeoff_period` — A
22. Recovery Rate by Credit Score (bar + table) — groupby FICO bucket — A
23. Recovery Rate by Interest Rate (bar + table) — groupby rate bucket — A

### Sub-tab F — Notes & OC (most deals, depends on pp)
24. Note Balances (stacked area by class A1..N) — `pool_performance.note_balance_a1..note_balance_n` — D
25. OC & Reserve Account (2 lines) — `pool_performance.overcollateralization_amount, reserve_account_balance` — D

### Sub-tab G — Documents (every deal)
26. Servicer Certificates (table, links) — `filings.servicer_cert_url` filtered non-null — D
27. Prospectus & Other Filings (table, 4 static EDGAR search links) — `carvana_abs/config.DEALS.cik` — not data

**Per-deal Carvana chart count: ~25 data charts/tables × 16 deals = ~400 chart instances**, but the tuple universe is **606 (ms) + 607 (pp) = 1213 (deal, date) tuples** — most charts reuse the same underlying rows.

---

## CarMax Per-Deal Tabs (49 deals × 4 sub-tabs = 196 sub-tab pages)

Function: `generate_carmax_deal_content(deal)` (lines 489-779). 49 deals totaling **2004 (deal, date) tuples** in `pool_performance`.

### Metrics strip (each deal, 6 KPIs)
- Original Balance — `get_carmax_orig_bal` / `carmax_abs.config` — D
- Current Balance — last non-null `ending_pool_balance` — D
- Pool Factor — A
- Active Loans — last non-null `ending_pool_count` — D
- Cum Loss Rate — last `cum_net_loss_derived` / orig_bal — A
- Total DQ Rate — last `total_delinquent_balance` / last `ending_pool_balance` — A

### Sub-tab A — Pool Summary
1. Remaining Pool Balance ($M) — `pool_performance.ending_pool_balance` — D
2. Active Loan Count — `ending_pool_count` — D
3. Avg Consumer Rate (Weighted APR) — `weighted_avg_apr` — D

### Sub-tab B — Delinquencies
4. Delinquency Rates (% of Pool) stacked area — `delinquent_31_60_balance, _61_90_, _91_120_, _121_plus_balance` / `ending_pool_balance` — A
5. Delinquency Trigger vs Actual (where present) — `delinquency_trigger_level, delinquency_trigger_actual` — D
6. Latest Period DQ table — latest-row buckets — D/A

### Sub-tab C — Losses
7. Cumulative Net Loss Rate (filled area) — `cum_net_loss_derived` / orig_bal — A
8. Cumulative Gross Losses vs Recoveries (lines) — `cumulative_gross_losses, cumulative_liquidation_proceeds, cum_net_loss_derived` (fallback cumsum of `gross_charged_off_amount`, `recoveries`) — D/A
9. Monthly Chargeoffs vs Recoveries (grouped bar) — `gross_charged_off_amount, recoveries` — D
(no loan-level loss tables — CarMax loan tapes not ingested)

### Sub-tab D — Documents
10. Servicer Certificates (table, links) — CarMax `filings.servicer_cert_url` — D
11. Prospectus & Other Filings (static EDGAR links) — `carmax_abs/config.DEALS.cik` — not data

**Per-deal CarMax chart count: ~10 data charts/tables × 49 deals = ~490 chart instances** over **2004 (deal, date) tuples**.

---

## Universe Summary — Tuple Counts by (Issuer, Metric Family)

| Issuer | Source Table | Metric Family | Distinct Columns Touched | Deal-date Tuples | 2% Sample |
|---|---|---|---|---|---|
| Carvana | `monthly_summary` | balance/loan-count/WAC/collections/DQ buckets/charge-offs/recoveries | ~20 numeric cols incl. total_balance, active_loans, weighted_avg_coupon, interest_collected, principal_collected, period_chargeoffs, period_recoveries, est_servicing_fee, dq_30/60/90/120_plus_balance, dq_*_count | **606** | **~12** |
| Carvana | `pool_performance` | note balances/OC/reserve/WAC/CoD components/triggers/waterfall/ending_pool_balance | ~25 cols incl. ending_pool_balance, weighted_avg_apr, note_balance_a1..n, total_notes, overcollateralization_amount, reserve_account_balance, total_note_interest, aggregate_note_balance, total_deposited, available_funds, actual_servicing_fee, regular_pda, residual_cash, delinquency_trigger_level/actual | **607** | **~12** |
| Carvana | `loans` | loan-level FICO / orig balance / rate (for group-by tables and avg-rate fallbacks) | obligor_credit_score, original_loan_amount, original_interest_rate, asset_number | **417,074 loans** (not deal-date; groupby bucket counts ≈ 16 deals × ~8 FICO × ~8 rate = 256 cells) | **~8,340 loans** |
| Carvana | `loan_loss_summary` | chargeoff/recovery per loan (recovery tab + loss groupby) | total_chargeoff, total_recovery, chargeoff_period, first_recovery_period | **41,793 defaulted loans** | **~836 loans** |
| Carvana | `filings` | servicer cert URLs (Documents tab) | filing_date, servicer_cert_url | **~620 rows** (non-null servicer_cert_url) | n/a (links) |
| Carvana | `_cert_dq_series` (derived from 10-D certs) | 30+ DQ balance / ending pool balance | cert parse: 31-60 + 61-90 + 91-120 + EPB | **~607** (one per filing with servicer cert) | **~12** |
| Carvana | `_cum_net_loss_series` (derived from 10-D certs) | cumulative net loss | cert parse: cum_net_loss | **~607** | **~12** |
| CarMax | `pool_performance` | balance/loan-count/WAC/DQ buckets/cum losses/chargeoffs/recoveries/triggers | ~20 cols incl. ending_pool_balance, ending_pool_count, weighted_avg_apr, delinquent_31_60/_61_90/_91_120/_121_plus_balance (+ _count), total_delinquent_balance, cum_net_loss_derived, cumulative_gross_losses, cumulative_liquidation_proceeds, gross_charged_off_amount, net_charged_off_amount, recoveries, beginning_pool_balance, total_note_interest, aggregate_note_balance, delinquency_trigger_level/actual | **2,004** | **~40** |
| CarMax | `filings` | servicer cert URLs (Documents tab) | filing_date, servicer_cert_url | **~1,850** (non-null servicer_cert_url) | n/a (links) |
| CarMax | `loans`, `loan_loss_summary`, `monthly_summary` | — | not ingested, 0 rows | — | — |
| **TOTALS — time-series (deal, date) tuples** | | | | **3,217** (606 + 607 + 2,004) | **~64** |

### Loan-level universe (separate strata, sampled at loan level not deal-date)
| Issuer | Scope | Loans | 2% |
|---|---|---|---|
| Carvana | `loans` (all) | 417,074 | 8,342 |
| Carvana | `loan_loss_summary` (chargeoff>0) | 41,793 | 836 |

### Model-derived items (out of scope per user)
- **Default Model view** (items 1-16 above): all model outputs (LR + RF + confusion matrices + ROC + segment predictions + loss severity)
- **Conditional-Markov Lifetime Loss Forecast Build-Up** (tables 2-3 in model view): per-deal forward simulation; uses loan-level data, empirical paydown curves, and LGD bins
- **One-month transition probabilities reference tables** (items 4-5 in model view)
- **Avg Trust Cost of Debt — Methods 3 & 4 fallbacks**: flat rate from `notes.coupon_rate` mean / rough estimate from avg loan rate × 0.4. Where Method 1 or 2 (actual interest/balance, or weighted coupons × balances) succeeds, the chart point is A not M. Method detection is per-deal, logged at generation time — auditor should check `generate_dashboard.py` log output per deal to know which method a given deal uses.

### Notes on sampling difficulty
- **Documents tab** (both issuers): just link tables, nothing to audit numerically.
- **Cross-issuer view 5**: no new data — every series is a re-plot from views 2 (Carvana Prime) and 4 (CarMax Prime). Sample once at the source.
- **Charts built from multi-column derivations** (Cost of Debt, Excess Spread): audit row = (deal, distribution_date) but verifying requires replaying the merge logic. Flag these explicitly; suggest spot-checking 2-3 deals end-to-end rather than blind 2% row sampling.
- **Loan-level group-by tables** (Losses by Credit Score / Interest Rate; Recovery Rate by FICO / Rate): sample at loan level within-bucket, then reconcile the bucket aggregate.
- **Cert-parsed series** (`_cert_dq_series`, `_cum_net_loss_series`, `_cert_totals`): direct from the latest 10-D servicer cert PDF for each filing_date. Ground truth is the cert itself — a sample here means pulling the cert and re-reading its line items.

### Recommended 2% stratified sampling plan
- Stratum 1: `monthly_summary` rows — 606 tuples → **12 rows**, stratified by (tier × deal).
- Stratum 2: `pool_performance` Carvana — 607 tuples → **12 rows**, stratified by (tier × deal).
- Stratum 3: `pool_performance` CarMax — 2,004 tuples → **40 rows**, stratified by vintage-year.
- Stratum 4: `loans` — 417,074 → **~8,342 loans**, stratified by (deal × FICO bucket × rate bucket) — or skip if the loan-level bucketed tables are considered derived from audited aggregates.
- Stratum 5: `loan_loss_summary` — 41,793 → **~836**, stratified by deal.
- Stratum 6: Cert-derived series (`_cert_dq_series`, `_cum_net_loss_series`) — ≈607 → **~12 filings**, spot-check by opening the 10-D and re-parsing.

Total row-level audit target: **~64 deal-date tuples** + **~9,200 loan-level rows** + **~12 cert re-parses**.
