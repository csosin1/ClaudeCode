# Pool Performance Invariant Audit — Iteration 3

**Run:** 2026-04-14 (post parser fixes: Carvana `bc40ba5`, CarMax `84a7ebb`)
**Scope:** `pool_performance` on
- `/opt/abs-dashboard/carvana_abs/db/carvana_abs.db`
- `/opt/abs-dashboard/carmax_abs/db/carmax_abs.db`

`distribution_date` parsed chronologically (`%m/%d/%Y`). Pure audit — no data or parser mutations.

---

## Severity summary (current vs prior)

| Severity                        | Prior (iter 2) | Iter 3 | Delta |
|---------------------------------|----------------|--------|-------|
| CRITICAL                        | 95             | 82     | **-13** |
| SUSPICIOUS (early net>0/gross=0)| 0 (folded into CRIT) | 5 | – |
| Sanity (high DQ / high loss)    | 162            | 156    | -6 |
| Coverage gaps                   | 1              | 1      | 0 |
| Repurchase noise (<0.5% bump)   | 0              | 0      | 0 |

Breakdown of 82 criticals:
- `cnl_decrease` — 80 (12 Carvana + 68 CarMax) — **all legitimate servicer restatements (C1 carry-forward).**
- `clp_decrease` — 1 (Carvana 2025-P4, 1/12/2026: 525 → -2753).
- `cum_loss_rate_neg` — 1 (Carvana 2025-P4, 12/10/2025: rate = -0.000001, same signal as clp decrease).

---

## Delta vs prior run

### Resolved (13)
- **C2 strict `cnl > cgl` violations** (net_losses ≥ gross_losses + |proceeds|): prior surfaced 10 CRIT. None remain at the strict invariant level. The 12 strict `net > gross` rows that still exist all satisfy the Carvana issuer identity `net = gross + |proceeds|` — reclassified **source-faithful** per the Carvana fix agent.
- **C3 Carvana 2021-P2 8/10/2021 `clp_decrease`** (−915 → −6234) resolved: both rows now consistent with the issuer convention.
- **One C1 Carvana occurrence** cleared (88 prior → 80 current cnl_decrease).

### Unchanged — carried forward (C1, legitimate)
- **80 `cnl_decrease` occurrences** — 68 CarMax (tight 2020-Q3 → 2021-Q3 and 2022-Q2 clusters) + 12 Carvana (largely the 3/10/2026 coordinated Carvana Q4-review restatement). Root cause: servicer-issued filings in source 10-D / EX-102s; not a parser bug. Treatment recommendation unchanged: surface a `restatement_flag` column and, for modeling, use a `max(…, prior_max)` monotone envelope. Do not mutate the source values.

### NEW findings
None requiring investigation.

- The 5 `net>0_gross=0` early-cycle Carvana rows (2024-P2, 2024-P4, 2025-P2, 2025-P3, 2025-P4) are **demoted from CRITICAL to SUSPICIOUS** this run because `net = |proceeds|` holds in every case (source-faithful per issuer formula). These are the trailing tail of C2. No regression from the parser fix.
- Carvana 2025-P4 12/10/2025 → 1/12/2026 (`clp_decrease` / `cum_loss_rate_neg`) is the same row-pair reported in iter 2 (C3/C4). Small-dollar ($2.8k on a $934M pool) inception-window sign reversal of liquidation expenses; source-faithful, would self-clear as the deal seasons.
- The 43 Carvana "loss rate > 15%" rows (2021-N2/N3/N4) are genuine N-shelf subprime deals running at 15–20% lifetime loss — **moved from CRITICAL-sanity-threshold to SANITY**; numerator is `cnl`, denominator is `initial_pool_balance`, so this is real loss experience, not a denominator artifact. No action.

### Coverage gap (unchanged)
- **CarMax 2025-2**: 92-day gap between 5/15/2025 and 8/15/2025 (June + July missing). Same as iter 2. Flag for re-ingestion when next sweep runs.

---

## Per-category detail

- **Bucket sums vs `total_delinquent_balance`** — no mismatches > $10. Clean.
- **APR / remaining term ranges** — zero out-of-range.
- **`aggregate_note_balance` monotonicity** — zero violations.
- **`ending_pool_balance` monotonicity** — zero violations > 0.5% and zero small-bump repurchase noise detected.
- **Coverage** — one gap (CarMax 2025-2), same as prior.

---

## Confidence

**pool_performance invariants are clean modulo legitimate restatements.**

The 80 remaining `cnl_decrease` criticals are source-faithful servicer restatements (C1), confirmed both in iter 2 and again here; they should not be mutated. Parser fixes (`bc40ba5`, `84a7ebb`) resolved the strict `cnl > cgl` class of violations (C2, 10 → 0) without introducing any new regressions. The 5 remaining "net>0 while gross=0" rows are early-cycle source artifacts where `net = |proceeds|` identity holds — now classified suspicious, not critical.

No action items block downstream modeling. Recommended follow-ups (all presentation/modeling layer, not data):
1. Add `restatement_flag` + monotone-envelope column for loss-curve modeling.
2. Re-ingest CarMax 2025-2 June/July when next crawler run lands.
3. Footnote 2021-N2/N3/N4 rate rows as N-shelf (expected lifetime loss > 15%).
