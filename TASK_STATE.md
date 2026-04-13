## Current Task
Name:              timeshare-surveillance (XBRL-first refactor)
Status:            building
Spec approved:     yes (user asked for hybrid XBRL + narrative-only LLM, 2026-04-13)
Rollback tag:      n/a (preview-only; not yet promoted)
Branch:            claude/timeshare-surveillance-refactor-to-xbrl-first-extraction-with-s
Resume hint:       Read CLAUDE.md, LESSONS.md, RUNBOOK.md, then this file's Spec section before starting.

## Spec

**Problem with v1:** we send the entire 10-Q / 10-K text to Claude and ask for a full JSON extract. A single HGV 10-K chunk is ~75k input tokens, which busted the account's 30k-TPM Anthropic rate limit. Also wasteful — most of what we extract (total receivables, allowance, provision, originations) is already structured in the SEC's XBRL feed, which is free and instant.

**Refactor:** hybrid extraction.

1. **XBRL first (free, structured, fast).** Hit `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` once per ticker. It returns every US-GAAP-tagged fact the company has ever filed, keyed by tag and period. Map the tags we care about into our METRIC_SCHEMA. This covers the balance-sheet / P&L stuff exactly — no LLM call needed.
2. **Claude on narrow snippets only.** For the remaining fields (delinquency bucket percentages, FICO distribution, vintage loss table, management commentary), download the filing HTML, locate the relevant section via heuristic markers (section headers like "Delinquency", "Past Due", "FICO", "Vintage", plus MD&A / "Critical Accounting Estimates"), and send ONLY those ~2–5k-token excerpts to Claude. No more whole-filing uploads.
3. **SQLite persistence.** Store everything in `data/surveillance.db`. Replaces per-filing JSON blobs in `data/raw/`. `merge.py` becomes "export from DB to combined.json".

### Success criteria

- `python pipeline/fetch_and_parse.py --ticker HGV` (no `--dry-run`) pulls recent 10-Qs and 10-Ks for HGV, populates the DB, and reports: records ingested, XBRL fields populated per filing, narrative-Claude calls made per filing, total input tokens used.
- A typical filing consumes **≤15k total input tokens** to Claude (vs ~225k in v1 for a 3-chunk 10-K). Multiple filings per minute feasible on the 30k-TPM account.
- Dashboard renders unchanged — `combined.json` has the same shape as v1 so the React code doesn't change.
- `--dry-run` still works (fixture XBRL JSON + fixture HTML snippets, no network).
- All 24 Playwright tests still pass on preview.
- Unit tests for xbrl_fetch (parsing SEC companyfacts JSON) and narrative_extract (locating sections in sample HTML) both pass.

### File layout changes

**New files:**
- `timeshare-surveillance/pipeline/xbrl_fetch.py`
- `timeshare-surveillance/pipeline/narrative_extract.py`
- `timeshare-surveillance/pipeline/db.py`
- `timeshare-surveillance/pipeline/schema.sql`
- `timeshare-surveillance/pipeline/fixtures/hgv_companyfacts_sample.json`
- `timeshare-surveillance/pipeline/fixtures/hgv_delinquency_section.html`
- `timeshare-surveillance/tests-unit/test_xbrl_fetch.py`
- `timeshare-surveillance/tests-unit/test_narrative_extract.py`
- `timeshare-surveillance/tests-unit/test_db.py`

**Rewritten files:**
- `timeshare-surveillance/pipeline/fetch_and_parse.py` — orchestrator only. No more monolithic Claude call.
- `timeshare-surveillance/pipeline/merge.py` — `db.export_combined() → combined.json`, plus derived QoQ/YoY.
- `timeshare-surveillance/config/settings.py` — add `XBRL_TAG_MAP`, `NARRATIVE_SECTION_PATTERNS`, `SQLITE_DB_PATH`. Switch `ANTHROPIC_MODEL` to `claude-sonnet-4-6`. Restore `LOOKBACK_FILINGS = 4` and `FILING_TYPES = ["10-K","10-Q"]`.

**Unchanged:**
- `dashboard/index.html` (reads combined.json, shape stays the same)
- `admin/` (Flask app + template, already public per user request)
- `alerts/email_alert.py`
- `pipeline/red_flag_diff.py`
- `deploy/timeshare-surveillance.sh` (sqlite3 is stdlib, no dep changes)
- `watcher/edgar_watcher.py` — internal subprocess call path unchanged; the orchestrator under the hood just does less LLM.

### XBRL_TAG_MAP starter — builder must verify tag names against a live companyfacts JSON before trusting:

| METRIC_SCHEMA key                     | Likely US-GAAP tag(s)                                                                          | Unit | Scale  |
|---------------------------------------|------------------------------------------------------------------------------------------------|------|--------|
| gross_receivables_total_mm            | FinancingReceivableBeforeAllowanceForCreditLoss, company-ext TimeshareFinancingReceivable       | USD  | 1e-6   |
| allowance_for_loan_losses_mm          | FinancingReceivableAllowanceForCreditLoss                                                      | USD  | 1e-6   |
| net_receivables_mm                    | FinancingReceivableAfterAllowanceForCreditLoss                                                 | USD  | 1e-6   |
| provision_for_loan_losses_mm          | ProvisionForLoanAndLeaseLosses / ProvisionForLoanLossesExpensed                                 | USD  | 1e-6   |
| originations_mm                       | company-specific; inspect companyfacts and pick the best fit                                    | USD  | 1e-6   |
| securitized_receivables_mm            | company-ext                                                                                     | USD  | 1e-6   |
| gain_on_sale_mm                       | GainLossOnSalesOfLoansNet / company-ext                                                         | USD  | 1e-6   |

Derived: `allowance_coverage_pct = allowance/gross_receivables`.

Everything else — delinquency bucket %, FICO distribution, vintage table, gain-on-sale margin %, advance rates, rescission, VPG, tour flow, management commentary — via narrow Claude calls on located HTML sections.

### Narrative extraction approach

Function: `narrative_extract.locate_sections(html) → dict[section_name, excerpt_text]`.

Section finders (case-insensitive regex match on nearby headings/text, then pull a bounded window of following text, stripped of HTML tags, capped at ~3k tokens per section):
- `delinquency` — "delinqu", "past due", "aging"
- `fico` — "FICO", "credit score"
- `vintage` — "vintage", "static pool"
- `management_commentary` — "Critical Accounting", "Credit Losses" in MD&A, or "Allowance for" discussion in MD&A

One Claude call per located section, each ~2–4k input tokens, return only the fields relevant to that section. Combine with XBRL metrics into one filing record. Persist.

### Non-goals

- No change to `combined.json` shape.
- No backfill migration of v1 JSON blobs.
- No change to watcher cadence, email alerts, or red-flag thresholds.
- No promote to live — preview only until user accepts.

## Builder Output
(pending)

## Reviewer Verdict
(pending)

## QA Result
(pending)

## Blockers
None at build time. Hard design constraint: ≤15k total Claude input tokens per filing to fit 30k-TPM.
