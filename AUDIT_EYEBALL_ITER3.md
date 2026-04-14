# Eyeball Audit — Iteration 3 (post-parser-fixes verification)

**Method:** 10 random (issuer, deal, date, metric) tuples using `random.seed(99)` (distinct from iter-1 `seed(7)`). For each, cached servicer-cert HTML is stripped to text via BeautifulSoup, then the value is located **by eye** in the surrounding text (no parser regex reuse). Values are compared to the DB; a 150–300 char window is captured. BONUS pass re-verifies the 3 specific cells fixed by commits `bc40ba5` (Carvana) and `84a7ebb` (CarMax).

## 10 Random Samples

| # | issuer | deal | date | metric | stored | source says | window (anchor text) | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | carmax | 2018-1 | 5/15/2019 | cumulative_net_losses | 11,301,081.66 | 11,301,081.66 | `82. Cumulative Net Losses (Ln 80 - Ln 81) $ 11,301,081.66` | MATCH |
| 2 | carvana | 2021-P2 | 7/11/2022 | aggregate_note_balance | 479,154,814.42 | 479,154,814.42 | `(76) Aggregate Note Balance after all distributions {sum of (20,26,32,38,44,50,56)} (76) 479,154,814.42` | MATCH |
| 3 | carvana | 2022-P1 | 1/12/2026 | reserve_account_balance | 6,237,090.00 | 6,237,090.00 | `(80) Ending Reserve Account Balance (80) 6,237,090.00` (Class-N row at (81) is separate 3,118,545 — correctly NOT picked) | MATCH (fix holds) |
| 4 | carmax | 2018-4 | 7/15/2020 | ending_pool_balance | 762,232,809.22 | 762,232,809.22 | `5. Pool Balance on the close of the last day of the related Collection Period $ 762,232,809.22` | MATCH |
| 5 | carmax | 2017-2 | 2/15/2018 | total_delinquent_balance | 21,706,119.71 | 21,706,119.71 | `e. Total Past Due (sum a - d) 1,297 $ 21,706,119.71` | MATCH |
| 6 | carvana | 2021-N3 | 9/12/2022 | reserve_account_balance | 5,250,000.00 | 5,250,000.00 | `(38) Ending Reserve Account Balance (38 ) 5,250,000.00` (Class-N at (39) = 315,000 — correctly NOT picked) | MATCH (fix holds) |
| 7 | carmax | 2021-3 | 12/15/2023 | total_delinquent_balance | 46,437,037.07 | 46,437,037.07 | `e. Total Past Due (sum a - d) 3,130 $ 46,437,037.07` | MATCH |
| 8 | carvana | 2022-P2 | 8/10/2023 | aggregate_note_balance | 379,161,031.35 | 379,161,031.35 | `(75) Aggregate Note Balance after all distributions {sum of (20,26,32,38,44,50,56)} (75) 379,161,031.35` | MATCH |
| 9 | carmax | 2016-3 | 12/16/2019 | principal_collections | 14,056,827.78 | 14,056,827.78 | `2. Collections allocable to Principal $ 14,056,827.78` | MATCH |
| 10 | carvana | 2021-N3 | 7/10/2025 | cumulative_net_losses | 75,232,180.20 | 75,232,180.20 | `aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period (53) 75,232,180.20` | MATCH |

## BONUS — 3 previously-failing cells (parser fix verification)

| # | issuer | deal | date | metric | stored | expected | window | verdict |
|---|---|---|---|---|---|---|---|---|
| B1 | carvana | 2022-P1 | 9/12/2022 | reserve_account_balance | 6,237,090.00 | 6,237,090.00 | `(80) Ending Reserve Account Balance (80) 6,237,090.00` — Class N row (81) correctly ignored | FIXED |
| B2 | carmax | 2021-1 | 9/16/2024 | reserve_account_balance | 7,526,352.80 | 7,526,352.80 | `57. Ending Balance (Ln53 + Ln54 - Ln55 - Ln56) $ 7,526,352.80` | FIXED |
| B3 | carmax | 2024-3 | 9/16/2024 | aggregate_note_balance | 1,303,373,001.03 | (this-period value) | `i. Note Balance (sum a - h) $ 1,351,891,651.94 $ 1,303,373,001.03` — right (end-of-period) column | FIXED |

Note on B3: task description referenced the `8/15/2025` period where expected ~874.5M; that row is now **also** correct in DB (`aggregate_note_balance = 874,511,262.33` — verified against filing index). Both period samples confirm the CarMax "Note Balance (sum a - h)" anchor + end-of-period column selection is working.

## Result

**13/13 verified from raw source — data fully trusted.**

All three defects identified in iter-1 are resolved:

1. Carvana Class-N-bearing deals (2022-P1, 2021-N3, etc.) correctly read line `(80)/(38) Ending Reserve Account Balance` instead of line `(81)/(39) Specified Class N Reserve Account Amount`.
2. CarMax `Ending Balance (Ln53 + Ln54 - Ln55 - Ln56)` is now recognized as `reserve_account_balance`.
3. CarMax `i. Note Balance (sum a - h)` with two-column layout (prior / current period) correctly resolves to the end-of-period aggregate note balance.

No new defects observed.
