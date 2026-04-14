# Post-Fix Audit + PK Collision Sweep

2026-04-14 · branch `claude/carvana-loan-dashboard-4QMPM`

## Check 1 — PK Collision Sweep

`INSERT OR REPLACE INTO pool_performance` on `(deal, distribution_date)` silently
overwrites. Orphans = `ingested_pool=1` filings with no PP row keyed by their accession.

| Issuer  | Orphans | Root cause |
|---------|--------:|------------|
| Carvana |       8 | Stale-header bug (same as CarMax 2025-2) |
| CarMax  |      18 | Amendments (10-D/A) lost to original 10-D |
| **Total** | **26** | |

**Carvana (8) — stale-header.** Dec 2024 10-D certs filed 2024-12-13 with stale header
`Distribution Date 11/8/2024`. Parser overwrote Nov. Issuer refiled as **10-D/A on
2025-02-21** with correct dist — rescue rows in DB (data complete), originals discarded.
Deals: 2020-P1, 2021-P1/P2, 2022-P1/P2/P3, 2024-P2/P3.

**CarMax (18) — amendments.** 16 bulk 10-D/A on **2018-03-23** restating Feb 2018
(deals 2014-2…2018-1), plus 2014-1 (2014-05-30) and 2024-4 (2024-12-19). Original 10-D
won every collision; authoritative amendment lost. Example: `CarMax 2017-1 dist=2/15/2018,
winner=..-000008 (10-D), lost=..-000014 (10-D/A)`. Parser doesn't prefer `/A`.

## Check 2 — Post-Fix Audit (seed 2026, 2%=1,395 tuples, 25 chunks)

| Verdict     | Count |
|-------------|------:|
| MATCH       |   827 |
| MISMATCH    |    12 |
| UNVERIFIED  |   556 |

All 12 MISMATCH = **AUDIT-BUG**: CarMax `aggregate_note_balance`; harness grabs one
tranche, but DB aggregate = exact sum of `note_balance_a1..d` (delta=0 for 2024-1,
2024-3, 2025-3). Parser correct. **Zero real issues.**

## Spot-Check

| Cell | Expected | Actual | |
|------|---------:|-------:|:-:|
| Carvana 2022-P1 reserve | 6,237,090 | 6,237,090 | PASS |
| CarMax 2021-1 reserve | 7,526,352.80 | 7,526,352.80 | PASS |
| CarMax 2024-3 agg_note (8/15/25) | 874,511,262.33 | 874,511,262.33 | PASS |

## Confidence

**Data remains trusted.** Parser fixes hold. The 26 orphans are a separate
pre-existing silent data-loss risk, not a regression. Carvana's 8 self-rescued in DB
(no user impact). CarMax's 18 show pre-amendment values instead of amended — user-
visible but low magnitude (mostly 8-year-old Feb 2018 rows).

## Recommendations

1. **Amendment precedence** in parser: on collision prefer filing_type `/A`, else later
   filing_date. Or widen PK to include accession_number + canonical view.
2. **Stale-header guard**: warn if extracted dist disagrees with filing_date ± 30d.
3. **Re-ingest** 18 CarMax amendments + 8 Carvana stale-header originals after (1).
4. **CI invariant**: assert no `ingested_pool=1` filing is an orphan.

Pure audit — no data touched.
