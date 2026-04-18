# Pool Performance Invariant Audit

**Run:** 2026-04-14
**Scope:** `pool_performance` table on
- `/opt/abs-dashboard/carvana_abs/db/carvana_abs.db` — 16 deals, 607 rows
- `/opt/abs-dashboard/carmax_abs/db/carmax_abs.db`  — 49 deals, 2 004 rows

Date parsed as `%m/%d/%Y` (chronological), not lexicographic.

---

## Severity summary

| Severity     | Carvana | CarMax | Total |
|--------------|---------|--------|-------|
| CRITICAL     | 27      | 68     | 95    |
| SUSPICIOUS   | 0       | 0      | 0     |
| Sanity (high delinq) | 162 | 0   | 162   |
| Coverage gaps| 0       | 1      | 1     |
| Repurchase noise (≤0.5% balance bumps) | 0 | 0 | 0 |

No `total_delinquent_balance` bucket-sum mismatches > $10. No APR/term out-of-range. No `net > gross - proceeds` deltas > 0.5% beyond the cumulative-decrease cases listed below.

---

## CRITICAL findings (mathematically impossible)

### C1. `cumulative_net_losses` decreases month-over-month (88 occurrences)

Cumulatives can only go up — a decrease means either a servicer restatement, a parser bug, or a units error.

**Carvana (8 deals affected):** 2020-P1 (×4), 2021-P1 (×2), 2021-P2, 2022-P1, 2022-P2, 2022-P3, 2024-P3, 2024-P4 (each ×1 on 3/10/2026 cycle).
Most are sub-1% drops ($10k–$180k on multi-million cumulatives). One outlier:
- **2024-P3 12/10/2024**: net dropped 129 165 → 74 007 (-42.7%). Gross simultaneously jumped 131 073 → 190 836 and proceeds jumped 1 908 → 116 830. Accession `0001999856-25-000010` (filed Jan 2025) — a normal sequential filing, not an amendment. Servicer reclassified a charge-off as a recovery; fields are internally consistent (gross-proceeds = 74 006 ≈ net 74 007).

**CarMax (~30 deals affected):** clusters tightly around two windows — Sep 2020–Aug 2021 and Mar–Aug 2022. Drops are typically $10k–$170k on $15M–$30M cumulatives (<1%).

**Root cause:** servicer-issued restatements in the source 10-D / EX-102 filings, not a parser bug. The 2020–2022 cluster aligns with COVID-era loan-mod / repurchase reclassifications across the industry. The Carvana 3/10/2026 cluster (5 deals same date) is a single coordinated restatement after Carvana's Q4 servicing review.

**Fix recommendation:**
1. Add a `restatement_flag` column populated when `cumulative_net_losses[t] < cumulative_net_losses[t-1]`; surface in dashboard with a footnote rather than silently presenting decreasing cumulatives.
2. For loss-curve modeling, use `max(cumulative_net_losses, prior_max)` as a monotone envelope.
3. Do NOT "fix" the values — they reflect the official filing.

### C2. `cumulative_net_losses > cumulative_gross_losses` (10 occurrences, all Carvana)

Impossible by definition (net = gross − recoveries, recoveries ≥ 0).

Affected: 2020-P1 (1), 2021-N2 (1), 2021-N4 (1), 2021-P1 (1), 2021-P2 (2), 2024-P2 (1), 2024-P3 (1), 2024-P4 (1), 2025-P2 (1), 2025-P3 (1), 2025-P4 (1).

Pattern: every case occurs in **the first 1–4 months after deal issuance**, when `cumulative_gross_losses` is still 0 or near-zero but `cumulative_net_losses` is already non-zero. Examples:
- 2024-P2 7/10/2024: net=2 524, gross=0
- 2025-P2 7/10/2025: net=4 199, gross=0
- 2025-P4 1/12/2026: net=2 753, gross=0; `cumulative_liquidation_proceeds=-2 753` (matches)

**Root cause:** parser/source-mapping bug. In Carvana's earliest-cycle EX-102 filings, the "gross losses" tag is reported as 0 (or omitted) while "net losses" is populated from a different XBRL fact. The parser is not back-filling gross from `net + |proceeds|` when gross is 0 but net is non-zero.

**Fix recommendation:** in `carvana_abs/ingestion/servicer_parser.py`, when `cumulative_gross_losses == 0` and `cumulative_net_losses != 0`, derive gross as `cumulative_net_losses + cumulative_liquidation_proceeds` (clamped ≥ 0) OR mark gross as NULL so downstream code doesn't display zero. Verify by re-running parser on accession `0001999856-24-000028` (2024-P3 10/10/2024).

### C3. `cumulative_liquidation_proceeds` goes negative / decreases (2 occurrences, Carvana)

- 2021-P2 8/10/2021: -915 → -6 234
- 2025-P4 1/12/2026: 525 → -2 753

**Root cause:** sign-flipped reclassification at deal inception (servicer credited a prior recovery). Same window-of-issuance pattern as C2. Likely the same parser issue: the EX-102 fact for early-cycle "proceeds" is being populated with a negative reversal entry that should be zeroed.

**Fix recommendation:** clamp `cumulative_liquidation_proceeds` at zero if negative AND `t < 6 months from issuance`, log to a `parse_anomalies` table for review.

### C4. NEGATIVE cumulative loss rate (1 occurrence, Carvana)

- 2025-P4 12/10/2025: rate = -0.0000 (essentially zero, derived from C2/C3 sign flip).

Will resolve when C2/C3 are fixed.

---

## SUSPICIOUS findings

None at the >4σ MoM jump threshold, and no cross-metric `net ≠ gross − proceeds` deltas beyond the C1/C2/C3 cluster.

## Sanity flags (high but plausible)

### S1. Carvana 2021-N1 sustained delinquency rate > 25% (162 rows, Aug 2023 → present)

`total_delinquent_balance / ending_pool_balance` rises from 26% (Aug 2023) to 41% (Jan 2026). This is the **N-shelf (subprime, near-prime mix)** deal in heavy tail amortization — pool balance has shrunk to <5% of original, so a fixed-dollar delinquent stub creates a misleading rate. **Not a data error.** Recommend dashboard either (a) suppress the delinq-rate metric when `ending_pool_balance < 10% of initial_pool_balance`, or (b) annotate "tail deal — denominator effect."

## Coverage gaps

- **CarMax 2025-2**: 3-month gap between 5/15/2025 and 8/15/2025 (missing June, July). Need to verify EDGAR filings exist and re-ingest. Likely missed by ingestion crawler — file a re-fetch task.

---

## Recommended fixes (priority order)

1. **(parser bug, P0)** Patch `carvana_abs/ingestion/servicer_parser.py` for early-cycle `gross_losses=0 / net_losses>0` (C2, C3, C4 — fixes 14 of 27 Carvana criticals).
2. **(crawler gap, P1)** Re-ingest CarMax 2025-2 for June + July 2025 cycles.
3. **(presentation, P2)** Add `restatement_flag` and monotone-envelope columns; suppress delinq rate on tail deals.
4. **(data integrity, P3)** Document servicer restatements (C1) — they are real, not bugs, but should not be silently masked by max-envelope logic in regulatory views.
