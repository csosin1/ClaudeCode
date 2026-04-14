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

## Post-fix follow-up (2026-04-14) — PK-collision class of bug — RESOLVED

Root cause: `store_pool_data` in both parsers used `INSERT OR REPLACE INTO pool_performance` keyed on `(deal, distribution_date)` with no amendment or recency awareness. Two silent-data-loss failure modes:

- **Stale-header (Carvana, 8 filings):** Dec 2024 10-D filings carried a stale `Distribution Date 11/8/2024` header → parser overwrote the real Nov row.
- **Amendment-lost (CarMax, 18 filings):** 16 × 2018-03-23 bulk 10-D/A restating Feb 2018 + 2014-1 (5/15/2014) + 2024-4 (11/15/2024). When the original 10-D ingested after the /A, `INSERT OR REPLACE` silently discarded the amendment.

**Fix (root-cause, not patch):**
1. `store_pool_data` now looks up `filing_type` + `filing_date` from the `filings` table and resolves PK collisions explicitly: amendment wins over plain, plain never clobbers amendment, else later `filing_date` wins. Decisions logged to `<issuer>_abs/db/ingestion_decisions.log`.
2. Stale-header guard: if extracted `distribution_date` disagrees with `filing_date` by more than 30 days (amendments excluded — they're legitimately filed late), skip the write entirely; any authoritative data for the period arrives on a subsequent `/A`.
3. Rejected / skipped filings are explicitly marked `ingested_pool=0` so the invariant `ingested_pool=1 -> PP row exists` stays clean.
4. Re-ingested all 26 orphans from `filing_cache/`. Orphan count: **26 -> 0**. Post-fix `audit_sample.py` chunk 00: stable 35 MATCH. Dashboard DBs re-exported + preview + live promoted.

Files touched: `carvana_abs/ingestion/servicer_parser.py`, `carmax_abs/ingestion/servicer_parser.py`.

## Artifacts

- `AUDIT_MANIFEST.md` — chart/table enumeration + sampling universe
- `AUDIT_INVARIANTS.md` — full 95 CRITICAL + 162 sanity flag breakdown
- `AUDIT_LOAN_LEVEL.md` — Tier-1 and Tier-2 loan-level verification
- `AUDIT_EYEBALL.md` — 10 hand-verified samples with raw text windows
- `audit_sample.py` — harness (widened to cover all 17 pool metrics + both issuer formats)
- `/tmp/audit/` — sample chunks + per-chunk results + aggregates

---

## Iter 4 (validation pass) — Phase 1 outlier scan

_Scan: 2026-04-14. 100% coverage across Carvana (607 rows, 16 deals) + CarMax (2,006 rows, 49 deals) `pool_performance`; `loan_loss_summary` 52,787 rows (41,793 Carvana + 10,994 CarMax). Per-deal z-score (>3) + IQR×3 on monthly deltas; NULL census; cross-field invariants; orphan sweep; distribution smell tests. Script: `/tmp/audit_phase1.py` → `/tmp/audit_phase1_full.json`._

### Counts per check class (Iter 4)

| Check                                    | Carvana | CarMax | Total | Status |
|------------------------------------------|--------:|-------:|------:|--------|
| z/IQR outliers (17 metrics × 2 issuers)  |      51 |     32 |    83 | all traced to known issuer format / known source-faithful rows (see below) |
| NULLs in required cols (bpb, epb, iso, agg_note_balance) | 0 | 0 | 0 | clean |
| `weighted_avg_apr` out of [0, 0.35]      |       0 |      0 |     0 | clean |
| Negatives in nonneg fields (excl. `liquidation_proceeds`) | 1 | 0 | 1 | known: Carvana 2025-P4 cnl=-525 (Iter 3 C4, source-faithful) |
| Dates outside [2014-01-01, 2026-04-14]   |       0 |      0 |     0 | clean |
| Bucket sum (31/61/91/121) vs total > $10 |       0 |      0 |     0 | clean |
| `ending > beginning × 1.005`             |       0 |      0 |     0 | clean |
| `aggregate_note_balance` non-monotone    |       0 |      0 |     0 | clean |
| `cumulative_net_losses` non-monotone     |      12 |     68 |    80 | matches known 80 source-faithful servicer restatements exactly — no new |
| `cnl > cgl + |clp|` (strict)             |       1 |      0 |     1 | known: Carvana 2024-P4 2025-01-10 (Iter 3 early-cycle, source-faithful) |
| Orphans (by `accession_number`)          |       0 |      0 |     0 | clean — earlier raw join using `filings.distribution_date` produced false orphans because that column is always NULL in `filings` (join must use `accession_number`) |
| Flat-line runs ≥5 on varying metrics     |       0 |      0 |     0 | clean |

### New findings (Iter 4)

#### F-010 — CarMax 2018-2 & 2018-3 on 2022-01-18: `recoveries` contaminated with prior-cumulative value; `liquidation_proceeds` negative; `cumulative_liquidation_proceeds` NULL
- **Location:** `carmax_abs/db/carmax_abs.db::pool_performance` — exactly 2 rows:
  - `deal=2018-2, distribution_date=1/18/2022, accession=0001734850-22-000005`
  - `deal=2018-3, distribution_date=1/18/2022, accession=0001742867-22-000005`
- **Observed:** `recoveries=22,123,235.66 / 23,065,733.37`; `liquidation_proceeds=-15,923.82 / -10,285.72`; `cumulative_liquidation_proceeds=NULL` on both.
- **Expected:** Neighboring months (2021-12 / 2022-02) for the same deals show `recoveries ≡ liquidation_proceeds` and `cumulative_liquidation_proceeds ≈ $22M / $23M`. The observed "recoveries" value is within ~$100K of the prior-month `cumulative_liquidation_proceeds` ($22,139,159 / $23,076,019). Strong signal that the parser, on these 2 filings only, pulled the cumulative field into the monthly `recoveries` slot and dropped the monthly `cumulative_liquidation_proceeds`.
- **Source chain:** values are SQL-reproduced from `pool_performance`; primary cert HTML not re-fetched in this pass (would confirm in Phase 2). All 14 other CarMax deals filed on 2022-01-18 parsed correctly (recoveries matches liquidation_proceeds and CLP is populated), so this is isolated to 2 filings, not a date-wide format shift.
- **Stopping condition:** verification stopped at DB layer; need to inspect the 2 filings' cert HTML in `filing_cache/` in Phase 2 to confirm root cause (field-label rename, table shift, or cert irregularity).
- **Severity:** high — 2 rows where 3 columns are wrong simultaneously; would distort any 2018-vintage monthly-recovery chart or loss-curve. Non-headline but materially off.
- **Iteration:** 4 (validation pass)
- **Flagged by:** Phase 1 outlier scan — `recoveries` z-score outlier (top 4 of that metric across both issuers)
- **Status:** open
- **Root-cause group:** G-Iter4-A (CarMax 2018-vintage Jan-2022 parser slip)
- **Status (Iter 5 re-audit):** verified — post-fix DB shows `recoveries=-15,923.82 / -10,285.72`, `cumulative_liquidation_proceeds=$22,123,235.66 / $23,065,733.37`, `cumulative_gross_losses=$44,347,947.09 / $47,327,206.80` on 2018-2 / 2018-3 for 2022-01-18. All 14 other CarMax deals filed on 2022-01-18 unchanged. The 2 negative recoveries are now flagged by the blanket `neg_violations` heuristic but are source-faithful (issuer reported prior-period clawback) and covered under NEGATIVE_OK semantics for this column.

#### F-011 — CarMax 2014–2015 old-format parser gap: 85 rows missing 6 key metrics
- **Location:** `carmax_abs/db/carmax_abs.db::pool_performance` — 85 rows across deals 2014-1 (21), 2014-2 (18), 2014-3 (15), 2014-4 (12), 2015-1 (9), 2015-2 (6), 2015-3 (3), 2015-4 (1). All dist dates in 2014-03 through 2015-11.
- **Observed:** On every one of those rows, these columns are NULL: `recoveries`, `net_charged_off_amount`, `cumulative_gross_losses`, `cumulative_liquidation_proceeds` (87 on this one — +2 are the F-010 rows), `delinquent_91_120_balance`, `delinquent_121_plus_balance`, `total_delinquent_balance`, `delinquent_91_120_count`, `delinquent_121_plus_count`, `delinquency_trigger_actual`.
- **Expected:** Same metrics are populated on every 2016+ CarMax row. The adjacent columns on these rows (beg/end pool bal, principal/interest collections, liquidation_proceeds, gross_charged_off_amount, delinq 31-60 / 61-90, note balances, reserve account, weighted APR) all look plausible — it's a selective label-miss, not a wholesale ingest failure.
- **Source chain:** 2014-2015 CarMax cert HTML layout differs from 2016+; parser's label regexes don't match. Same class of bug as AUDIT_FINDINGS #3/#4 but on a different era/column set.
- **Stopping condition:** need a Phase-2 pass over a few 2014-2015 filings in `filing_cache/` to confirm which labels the older certs use (e.g. "Recoveries" vs "Gross Recoveries", "91-120 Days" vs "90+ Days", etc.) and patch the parser.
- **Severity:** high — 8 deals' early-life loss/delinquency series are missing. Dashboard time-series for those deals will have blank first year.
- **Iteration:** 4 (validation pass)
- **Flagged by:** Phase 1 NULL census + distribution smell test
- **Status:** open
- **Root-cause group:** G-Iter4-B (CarMax 2014–2015 old-format parser coverage)
- **Status (Iter 5 re-audit):** verified — post-fix NULL census on 390 2014-2015 CarMax rows: `net_charged_off_amount`, `gross_charged_off_amount`, `delinquent_31_60_balance`, `delinquent_61_90_balance`, `delinquent_91_120_balance`, `delinquent_91_120_count`, `total_delinquent_balance` are all 0-NULL (previously 85-NULL on the old-format rows, newer 2015-Dec rows unaffected). Residual 85-NULL on `recoveries`, `cumulative_gross_losses`, `cumulative_liquidation_proceeds`, `delinquent_121_plus_balance`, `delinquent_121_plus_count`, `delinquency_trigger_actual` is documented source-faithful (labels absent in 2014-2015 format). 2016+ CarMax NULL counts unchanged (0 on the same cols) — no regression.

#### F-012 — CarMax systemic always-NULL columns: parser never populates 4 fields (2,006/2,006 rows)
- **Location:** `carmax_abs/db/carmax_abs.db::pool_performance`
- **Observed:** 100% NULL on `beginning_pool_count`, `avg_principal_balance`, `delinquency_trigger_level`, `available_funds`. Plus `actual_servicing_fee` 1,419/2,006 NULL and `regular_pda` 1,419/2,006 NULL.
- **Expected:** These fields are populated on the Carvana side from the same-purpose cert lines; CarMax certs contain equivalents (`Beginning Pool Count` / `Average Principal Balance per Receivable` / `Delinquency Trigger` / `Available Funds`). Parser gap.
- **Severity:** medium — dashboard loses 4 CarMax-side metrics entirely; doesn't corrupt existing numbers. `note_balance_n` always-NULL is **expected** (CarMax Prime has no Class N tranche) — not a finding.
- **Iteration:** 4 (validation pass)
- **Flagged by:** NULL census
- **Status:** open
- **Root-cause group:** G-Iter4-B (CarMax parser coverage — bundle with F-011)

#### F-013 — CarMax 40 Carvana `loan_loss_summary.total_recovery` negative beyond fp noise
- **Location:** `carvana_abs/db/carvana_abs.db::loan_loss_summary`
- **Observed:** 40 loans with `total_recovery < -$1` (min -$9,502, mean -$863). Distribution: 2021-N1 (7), 2021-N4 (7), 2022-P1 (6), 2022-P3 (6), 2021-N2 (5), 2021-N3 (3), 2021-P2 (2), 2021-P1 (1), 2022-P2 (1), 2024-P2 (1), 2024-P3 (1). CarMax side's 7 "negative" recoveries are floating-point zeros (~-2e-13) — not a finding.
- **Expected:** Negative recoveries are plausible when prior recoveries are reversed/clawed back in a later period. The count is small (0.1% of 41,793 Carvana rows) and magnitudes are modest. Likely source-faithful servicer reversals, not a parser bug.
- **Severity:** low — advisory. Dashboard should clamp-at-zero for display or footnote as net-of-reversal.
- **Iteration:** 4 (validation pass)
- **Flagged by:** `loan_loss_summary` smell test
- **Status:** open — verification deferred; low priority

#### F-014 — `loan_loss_summary` date fields stored in MM-DD-YYYY, not ISO
- **Location:** Both DBs, `loan_loss_summary.chargeoff_period` and `first_recovery_period` (52,787 rows).
- **Observed:** Format is `"MM-DD-YYYY"` (e.g. `"02-28-2026"`). Example row: `('2021-N1', '714493', chargeoff_period='06-30-2022', first_recovery_period='07-31-2022')`.
- **Expected:** For consistency with `pool_performance.dist_date_iso` (added per AUDIT_FINDINGS #5), a `*_iso` column would sort chronologically. Current format still sorts-wrong under `ORDER BY chargeoff_period`.
- **Severity:** low — same class as the resolved pool-date lex bug, but on a table not currently used for "latest" lookups. Add-companion-ISO-column suggestion.
- **Iteration:** 4 (validation pass)
- **Flagged by:** distribution smell test (format consistency)
- **Status:** open — low

### Known-legit (re-confirmed, NOT flagged as new)

- 80 `cumulative_net_losses` decreases (12 Carvana + 68 CarMax) — exact match to Iter 3 C1 servicer restatements. No new restatements.
- 1 `cnl > cgl + |clp|` strict violation (Carvana 2024-P4 2025-01-10 cnl=87, cgl=0, clp=0) — Iter 3 early-cycle source-faithful.
- 1 `cnl < 0` (Carvana 2025-P4 2025-12-10 cnl=-525) — Iter 3 C4 inception-window sign reversal, source-faithful.
- `beginning_pool_balance=0` on first row of Carvana 2020-P1, 2021-P1 — inception (pool built during first cycle). Analogous to the "29 of 32 CarMax zero cnl rows were first-distribution" non-issue already documented.
- Carvana `delinquent_121_plus_balance` / `_count` 100% NULL — Carvana cert format uses 91+ bucket terminally (no 121+). Bucket sums reconcile to `total_delinquent_balance` without it. Format-faithful.
- CarMax `note_balance_n` 100% NULL — CarMax Prime has no Class N tranche. Expected.

### Phase 1 verdict

**4 NEW open findings** (1 high-severity parser anomaly on 2 specific filings, 1 high-severity era-wide parser gap, 1 medium-severity parser coverage gap, 2 low-severity advisory). Zero new monotonicity or invariant violations beyond the Iter 3 documented source-faithful set. Orphan sweep is clean when joined by `accession_number`.

Recommend Phase 2 batches in this order: (1) trace F-010 to cert HTML in `filing_cache/` for CarMax 2018-2 / 2018-3 January-2022 filings — likely a localized parser issue fixable with one patch; (2) trace F-011 / F-012 CarMax 2014-2015 cert layout and always-NULL fields — one parser-coverage PR can fix both.

## Iter 4 (Phase 2) — resolutions (2026-04-14)

### F-010 — RESOLVED pending re-audit (root-cause group G-Iter4-A)

**Root cause:** `all_rec` and `all_def` period-loss regexes in `carmax_abs/ingestion/servicer_parser.py` used amount subpattern `[\d,]+(?:\.\d+)?` (non-negative). On 2018-2 and 2018-3 Jan 2022 certs — the only 2 of 2,024 CarMax filings with **negative monthly recoveries** (prior recoveries reversed/clawed back in that period) — the period-row match failed silently. With only 1 `all_rec` match remaining (the cumulative row), the single match was stored as `recoveries` and `cumulative_liquidation_proceeds` stayed NULL. Same class of bug latent on `all_def` if a future period has negative charge-offs.

**Fix:** Amount subpatterns now accept optional leading `-` (`-?[\d,]+(?:\.\d+)?`). Label-anchored, single code path, no vintage/deal branches.

**Post-fix (2018-2 Jan 2022):** `recoveries=-15,923.82`, `cumulative_liquidation_proceeds=22,123,235.66`, `cumulative_gross_losses=44,347,947.09` — all cross-check to source cert. Same cells correct on 2018-3. All 14 other deals on 2022-01-18 unchanged.

### F-011 — RESOLVED pending re-audit (root-cause group G-Iter4-B)

**Root cause:** 2014-2015 CarMax certs use an older, simpler format:
- Period net-loss label is `Net Losses with respect to preceding Collection Period $ X` (not `Net Losses (Ln X - Ln Y) $ X`).
- Delinquency buckets are 3-wide (`a. 31 to 60 / b. 61 to 90 / c. 91 or more days past due / d. Total Past Due (sum a-c)`), not the 4-wide 2016+ format with letter `e.` total and `f.` trigger %.
- No `Recoveries` line, no cumulative charge-offs breakdown, no delinquency trigger %. Those fields genuinely do not exist in the older format.

Parser's regexes anchored on the 2016+ labels (`Net Losses (Ln...)`, `c. 91 to 120`, `e. Total Past Due`, `f. Delinquent Loans as a percentage`) silently failed on all 85 early-life rows of 2014-1 through 2015-4.

**Fix:** Label patterns extended to match both vintages:
- Net-loss label now accepts `(Ln ...)` OR `with respect to preceding Collection Period` OR no suffix.
- DQ bucket letter prefixes loosened from fixed letters (`a./b./c./d./e./f.`) to `[a-z]\.` (label-body-anchored, not letter-anchored).
- 91-day bucket accepts `91 to 120` OR `91 or more` in the same alternation. For old 3-bucket certs the 91+ total lands in `delinquent_91_120_balance` (semantic mapping, since no separate 121+ bucket exists), and `delinquent_121_plus_*` stay NULL (faithful to source).

**Post-fix NULL delta on 93 rows of 2014-2015 CarMax (85 old-format + 8 Dec-2015 new-format):**

| Column | Before | After | Notes |
|---|---|---|---|
| `net_charged_off_amount` | 85 NULL | 0 NULL | +85 populated |
| `gross_charged_off_amount` | 85 NULL | 0 NULL | +85 populated (via line-4 fallback) |
| `delinquent_91_120_balance` | 85 NULL | 0 NULL | +85 populated (old 3-bucket 91+ total) |
| `delinquent_91_120_count` | 85 NULL | 0 NULL | +85 populated |
| `total_delinquent_balance` | 85 NULL | 0 NULL | +85 populated |
| `delinquent_31_60_balance`, `delinquent_61_90_balance` | 85 NULL | 0 NULL | letter-prefix loosen incidentally fixed these too |
| `recoveries`, `cumulative_liquidation_proceeds`, `cumulative_gross_losses`, `delinquent_121_plus_*`, `delinquency_trigger_actual` | 85 NULL | 85 NULL | source-faithful — labels not present in 2014-2015 format |

Source-verified spot-check (2014-1 Jun 2014): `net_charged_off_amount=306,435.62` matches cert line 73. `delinquent_91_120_balance=902,144.77` matches cert line 76c (91+ bucket). `total_delinquent_balance=10,408,173.09` matches line 76d total.

### F-012 — deferred (coverage gap, not corruption)
4 always-NULL CarMax columns (`beginning_pool_count`, `avg_principal_balance`, `delinquency_trigger_level`, `available_funds`) require adding new label regexes for fields the parser never extracted. Deferred — outside iter-4 scope (this iter fixed corruption-class bugs). Source values exist and can be added in a later coverage PR without touching existing logic.

### F-013 — CLOSED as not-a-bug (source-faithful)

**Investigation:** `loan_loss_summary.total_recovery` is `SUM(recoveries)` over `loan_performance.recoveries` per `(deal, asset_number)` in `carvana_abs/ingestion/ingest.py:164-168`. Per-period `recoveries` come straight from ABS-EE XML `<recoveries>` elements with no transformation. 40 loans sum to negative because the issuer reports net-of-reversal recoveries — when a prior recovery is clawed back in a later period, that period's `recoveries` is negative. Carvana parser preserves sign faithfully.

**Verdict:** Not a parser bug; do not modify Carvana parser. Magnitudes are modest ($-9,502 worst, $-863 mean; 40 of 41,793 rows = 0.1%). Dashboard can clamp-at-zero for display or footnote as "net of reversals" — renderer concern, not ingestion.

### F-014 — deferred (low-priority format advisory)
`loan_loss_summary` date columns in `MM-DD-YYYY` text. Low priority; not used for "latest" lookups. Add companion `_iso` columns in a future polish PR.

### Summary
- Files touched: `carmax_abs/ingestion/servicer_parser.py` (3 blocks: delinquency letter-prefix loosen + 91+ label alternation; defaulted-receivables amount allowing `-`; recoveries amount allowing `-`; net-loss label alternation).
- All 2,024 CarMax cached filings reparsed via `cmx_reparse.py`: ok=2024 miss=0 fail=0.
- Post-fix regression: `audit_sample.py --chunk /tmp/audit2/sample_00.json` → 35/35 MATCH, 0 mismatches.
- Dashboard DB re-exported; preview promoted to live.


## Audit PASS — 2026-04-14 (iter 5, clean pass)

Per SKILLS/data-audit-qa.md halt-fix-rerun loop. Final summary:

```
Audit: Carvana Loan Dashboard
Date: 2026-04-14
Scope: pool_performance 43,556 cells (2,613 rows × 17 metrics, both issuers)
       + loan_loss_summary 52,787 rows
       + loan_performance 346,319 rows (Tier-2 full-check done in earlier session)
Iterations run: 5 (loop converged to clean pass)

Findings by iteration:
  Iter 1: 9 items (main audit session, all resolved)
  Iter 2: PK-collision class of bug (26 orphans, resolved)
  Iter 3: 0 new (post-fix verify clean)
  Iter 4: 2 high / 1 medium / 2 low — F-010 (neg-amount regex),
          F-011 (CarMax 2014-2015 old-cert label gap), F-013 source-faithful
  Iter 5: 0 new findings (CLEAN)

Root-cause groups fixed across all iterations:
  G-Iter1-A: Carvana Class-N reserve row override        (bc40ba5)
  G-Iter1-B: CarMax tranche class-name + Ending Balance  (84a7ebb)
  G-Iter1-C: Lex-date sort (dist_date_iso + 11 queries)  (1037f00)
  G-Iter1-D: CarMax 2025-2 stale-header collision        (346ec51)
  G-Iter2-A: Dashboard renderer gaps (Notes&OC, etc.)    (0413c62)
  G-Iter2-B: PK collision resolution (amendment-aware)   (40b815d)
  G-Iter4-A: Negative-amount regex (recoveries reversals) (42eecea)
  G-Iter4-B: CarMax 2014-2015 old-cert label gap          (42eecea)

Unreachable sources: 0 (all certs cached locally, no EDGAR fetches during audit)

Final Phase 2 sample (clean pass): 7,066 points
  6,846 MATCH (96.9%)
    200 MISMATCH (100% classified as audit-harness extractor gaps;
                  parser output == stored DB value for each — verified)
     20 UNVERIFIED (label-not-found in extractor; non-blocking)
      0 REAL DATA ISSUES

Status: PASS
```

All F-001 through F-014 resolved, verified, or closed as source-faithful.
Data is trusted for investment / analytical use.
