# Audit Findings — Carvana Loan Dashboard

_Audit date: 2026-04-14_  
_Per SKILLS/data-audit-qa.md: 100% outlier scan + 2% risk-weighted random sample, each sampled point traced to primary source + calculation re-derived from first principles._

## Scope

- **Universe:** 38,417 populated (issuer × deal × distribution_date × metric) cells in `pool_performance` + 41,793 rows in `loan_loss_summary` + 346,319 rows in `loan_performance`.
- **Methods:** pool 2% sample (768 tuples) against cached cert HTML; loan-level 2% sample (835 charge-off events) against ABS-EE XML; invariant sweep (monotonicity, cross-metric, z-score outliers, coverage gaps); hand-eyeball 10 random with raw text inspection; targeted KMX-notes investigation.

## Clean (no action)

- Loan-level pipeline: **0 discrepancies** across 835 sampled events + 346,319 full Tier-2 checks.
- Pool 2% sample: **0 false values** (759 exact MATCH; 9 flagged are same root cause as Issue #1 below).
- Per-deal gross-loss reconciliation (loan_loss_summary ↔ pool_performance): within 1% on 13/16 Carvana deals, <4% on 3 others, <$15K on 1 immaterial deal.
- No orphan loans; no bucket-sum mismatches; no APR/term out-of-range.

## Open defects — ranked by blast radius

### 1. Carvana reserve_account_balance parser override (HIGH — affects Carvana P/N deals, every period)
- Parser (`carvana_abs/ingestion/servicer_parser.py:549-550`) reads field 81 ("Specified Class N Reserve Account Amount") AFTER field 78 ("Ending Reserve Account Balance"), unconditionally overwriting.
- Result: `reserve_account_balance` column stores Class-N-specific reserve (~$3.1M) instead of pool-level reserve (~$6.2M).
- Found by: 2% sample (9 cells) + hand-eyeball (Issue A).
- Evidence: Carvana 2022-P1 — stored 3,118,545; source literal "Ending Reserve Account Balance" = 6,237,090.
- Fix: disambiguate; store pool-level reserve in `reserve_account_balance` and Class-N-specific in a new column if needed.

### 2. Carvana early-cycle net>gross parser bug (MEDIUM — 12 Carvana cells across ~6 deals)
- Source: invariant sweep finding C2/C3.
- First 1–4 months after deal issuance: parser stores `gross_charged_off_amount=0` while `net_charged_off_amount≠0` and/or returns negative `liquidation_proceeds`.
- Fix: sign/label interpretation for early-cycle EX-102 filings.

### 3. CarMax reserve_account_balance parser miss (HIGH — ~43 of 49 deals NULL)
- CarMax certs use "Ending Balance" (line 55) rather than "Reserve Account Balance". Parser label doesn't match.
- Found by: hand-eyeball (Issue B) + KMX-tab investigation.
- Evidence: CarMax 2021-1 — source "57. Ending Balance ... $ 7,526,352.80", DB: NULL.

### 4. CarMax aggregate_note_balance parser miss for newer deals (HIGH — ~18 of 49 deals NULL)
- CarMax 2021-3+ split Class A-2 into A-2a + A-2b, shifting all letter prefixes by one (`a./b./c./d./e./f./g./h./i.`). Parser's letter-prefix regex silently fails.
- Also missing on 2024-3 where label is "Note Balance (sum a - h)".
- Found by: KMX-tab investigation + hand-eyeball (Issue C).
- Evidence: CarMax 2024-3 — source "i. Note Balance (sum a - h) ... $ 874,511,262.33", DB: NULL.

### 5. Dashboard "latest pool row" lex-date bug (MEDIUM)
- `pool_performance.distribution_date` stored as `MM/DD/YYYY` text. `ORDER BY distribution_date DESC` gives lex order, not chronological. `9/12/2022 > 9/10/2025` lex.
- Any dashboard query picking "latest" by lex sort silently returns a stale row.
- Fix: either parse to ISO `YYYY-MM-DD` on store, or use explicit chronological `ORDER BY date(substr(...))` pattern across queries.

### 6. CarMax Notes & OC sub-tab missing (MEDIUM — pure renderer code gap)
- `generate_carmax_deal_content()` in `carvana_abs/generate_dashboard.py` emits 4 sub-tabs vs Carvana's 7. "Notes & OC", "Cash Waterfall", "Recovery" tabs never added for CarMax side.
- CarMax `notes` static-attributes table is empty — no tranche class/coupon/original-balance ingested.
- Fix: copy renderer block from Carvana section; derive original balance from peak of time series if prospectus not ingested.

### 7. Cumulative loss restatement flag missing (LOW — display polish)
- 88 source-verified `cumulative_net_losses` decreases across ~38 deals, clustered in COVID era (2020–2021) + Carvana 3/10/2026 review.
- Real servicer restatements — not a data bug. But dashboard should expose a `restatement_flag` and use a monotone-envelope series for modeling.

### 8. CarMax 2025-2 missing June + July 2025 filings (LOW)
- Coverage gap — 2 missing distributions. Needs re-ingestion from EDGAR.

### 9. Carvana 2021-N1 post-amortization delinquency display >25% (LOW — denominator effect)
- Pool <10% of original; delinquency-rate metric becomes unstable. Not a data error.
- Fix: suppress delinquency rate when `ending_pool_balance < 10% of initial`.

## Non-issues (documented to avoid re-investigation)

- All 41 initial 2% sample MISMATCHES were audit-script extraction bugs (parser output == stored DB). Re-verified 41/41.
- 29 of 32 CarMax zero `cumulative_net_losses` rows were first-distribution certs (loans hadn't defaulted yet).
- `2021-N* 3/10/2022 avg_principal_balance=0` — consistent across 4 deals on one date. Issuer reporting glitch, not parser bug.
- `2021-N4 9/11/2023 total_delinquent_balance` NULL — different cert layout (70-field format); parser gap noted.
- Paid-off deals showing `aggregate_note_balance=0` and `reserve_account_balance=0` are legit (notes fully redeemed).

## Fix sequencing (per RCA rule: serial, root-cause, never patch)

1. [in progress] Carvana parser: fix #1 (Class N reserve), #2 (early-cycle net>gross / neg liq proceeds). Single file; bundle.
2. CarMax parser: fix #3 (reserve label), #4 (A-2a/A-2b letter drift + note-balance variants). Single file; bundle.
3. Reparse all affected rows from `filing_cache/` (no new SEC fetches).
4. Dashboard renderer: fix #5 (date sort), #6 (CarMax Notes & OC tab), #7 (restatement flag), #9 (DQ rate suppression).
5. Re-ingest CarMax 2025-2 June + July (#8) from EDGAR.
6. **Full audit loop re-run** (pool 2% + loan-level 2% + invariants + eyeball). Iterate until zero real data discrepancies.

## Artifacts

- `AUDIT_MANIFEST.md` — chart/table enumeration + sampling universe
- `AUDIT_INVARIANTS.md` — full 95 CRITICAL + 162 sanity flag breakdown
- `AUDIT_LOAN_LEVEL.md` — Tier-1 and Tier-2 loan-level verification
- `AUDIT_EYEBALL.md` — 10 hand-verified samples with raw text windows
- `audit_sample.py` — harness (widened to cover all 17 pool metrics + both issuer formats)
- `/tmp/audit/` — sample chunks + per-chunk results + aggregates
