# Eyeball Audit — First-Principles Verification

**Method:** 10 random (issuer, deal, date, metric) tuples (random.seed(7)). For each, manually located the metric in the raw cached servicer-cert HTML (BeautifulSoup text strip — no parser regex), printed a 150-char window, compared to the stored DB value.

## Side-by-side

| # | issuer | deal | date | metric | stored | source-says | window | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | carvana | 2021-P1 | 1/10/2022 | cumulative_net_losses | 988,641.00 | 988,641.28 | "(98) The aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period (98) 988,641" | MATCH |
| 2 | carvana | 2021-N2 | 4/10/2023 | ending_pool_balance | 191,062,332.71 | 191,062,332.71 | "(9) Ending Pool Balance (9) 12,494 191,062,332.71" | MATCH |
| 3 | carvana | 2022-P1 | 9/10/2025 | reserve_account_balance | **3,118,545.00** | **6,237,090.00** | "(80) Ending Reserve Account Balance (80) 6,237,090.00 ... (81) Specified Class N Reserve Account Amount (81) 3,118,545.00" | **MISMATCH** |
| 4 | carvana | 2020-P1 | 11/8/2021 | aggregate_note_balance | 267,057,081.60 | 267,057,081.60 | "(76) Aggregate Note Balance after all distributions {sum of (20,26,32,38,44,50,56)} (76) 267,057,081.60" | MATCH |
| 5 | carvana | 2021-N1 | 1/10/2025 | total_delinquent_balance | 24,564,591.83 | 24,564,591.83 | "(50) Total Delinquencies 2,116 24,564,591.83" | MATCH |
| 6 | carmax | 2018-3 | 10/15/2020 | cumulative_net_losses | 21,251,230.85 | 21,251,230.85 | "82. Cumulative Net Losses (Ln 80 - Ln 81) $ 21,251,230.85" | MATCH |
| 7 | carmax | 2015-2 | 9/15/2017 | ending_pool_balance | 428,340,149.45 | 428,340,149.45 | "5. Pool Balance on the close of the last day of the related Collection Period $ 428,340,149.45 (Ln1 - Ln2 - Ln3 - Ln4)" | MATCH |
| 8 | carmax | 2021-1 | 1/15/2025 | reserve_account_balance | **NULL** | **7,526,352.80** | "57. Ending Balance (Ln53 + Ln54 - Ln55 - Ln56) $ 7,526,352.80" | **MISS — parser failed** |
| 9 | carmax | 2024-3 | 8/15/2025 | aggregate_note_balance | **NULL** | **874,511,262.33** | "i. Note Balance (sum a - h) $ 912,631,129.00 $ 874,511,262.33" | **MISS — parser failed** |
| 10 | carmax | 2015-4 | 3/15/2018 | total_delinquent_balance | 17,963,578.62 | 17,963,578.62 | "e. Total Past Due (sum a - d) 1,330 $ 17,963,578.62" | MATCH |

## Result: 7/10 verified, 3 issues found

### Issue A (semantic / Pick 3) — Carvana 2022-P1 reserve_account_balance is wrong
The DB stores `reserve_account_balance = 3,118,545.00` for every period of Carvana 2022-P1. That figure is line (81) **"Specified Class N Reserve Account Amount"** — not the main reserve. The actual line (80) **"Ending Reserve Account Balance"** is **6,237,090.00**. The parser appears to grab the wrong row when a Class N reserve is also present. This affects all 2022-P1 periods (and likely all Carvana N-deals with a Class N reserve).

### Issue B (parser miss / Pick 8) — CarMax 2021-1 reserve_account_balance NULL
Source clearly says `57. Ending Balance ... $ 7,526,352.80`, but DB stores NULL. CarMax's reserve label is "Ending Balance" (no "Reserve Account" prefix on that exact line) — likely the regex requires "Reserve Account Balance" verbatim and misses the bare "Ending Balance" sub-row.

### Issue C (parser miss / Pick 9) — CarMax 2024-3 aggregate_note_balance NULL
Source: `i. Note Balance (sum a - h) $ 912,631,129.00 $ 874,511,262.33`. The end-of-period aggregate is 874,511,262.33 (not "Aggregate Note Balance" — CarMax labels it just "Note Balance (sum a - h)"). Parser likely anchors on "Aggregate Note Balance" (Carvana phrasing) and misses CarMax's wording.

## Recommendation
- Fix `carvana_abs/ingestion/servicer_parser.py` to anchor the reserve row by line number (80) or require "Ending Reserve Account Balance" (not just "Reserve Account") to avoid grabbing the Class N specified amount.
- Fix `carmax_abs/ingestion/servicer_parser.py` to recognize CarMax's "Ending Balance" (Ln 57) as reserve_account_balance and "Note Balance (sum a - h)" end-of-period column as aggregate_note_balance.
- Re-ingest all Carvana N-deals (Class-N-bearing) and any CarMax filings currently NULL for these fields.
