# Skill: SEC XBRL Extraction (Edge-Case Issuers)

## What This Does

Reliably pulls credit / receivables metrics from SEC EDGAR companyfacts JSON for issuers who report inconsistently in us-gaap — specifically timeshare lenders (HGV, VAC, TNL), but the patterns generalise to any non-bank consumer lender.

## When To Use

Any pipeline pulling `us-gaap` financial concepts from EDGAR for issuers outside the banking sector. Banks tag their loan-loss concepts religiously. Non-bank lenders (timeshare, auto finance, BNPL, specialty finance) often:

- Stop tagging a concept entirely after a few quarters and only disclose it in MD&A text.
- Use only the `…Net` form and never the `…Gross` form.
- Never tag the value at all even when they disclose it in the footnotes.

## Three Hard-Won Rules

### 1. Never use `AllowanceForDoubtfulAccountsReceivable` as an allowance fallback for a non-bank lender.

It's the *non*-product doubtful-accounts balance (B2B receivables, deposits in transit, etc.). For a timeshare lender it's $4–93M. The real timeshare ACL is $500M–$1B. The fallback gives you a value that LOOKS plausible until you sanity-check arithmetic. Ditto `AllowanceForLoanAndLeaseLossesReceivablesNetReportedAmount` for non-loan products.

**Use only:** `FinancingReceivableAllowanceForCreditLosses` (note the plural — `…ForCreditLoss` singular is rare and often a misspelling), `TimeSharingTransactionsAllowanceForUncollectibleAccounts` for timeshare specifically, and the issuer's own extension namespace if present.

### 2. Always cross-check `gross − allowance ≈ net`.

This three-line check catches the entire class of "wrong tag picked" bugs. Any divergence > max($5M, 0.5% × gross) means at least one of the three values is from a different reporting concept than the others.

```python
def _check_receivable_arithmetic(records):
    for r in records:
        g, a, n = r.get("gross_mm"), r.get("allowance_mm"), r.get("net_mm")
        if None in (g, a, n): continue
        tol = max(5.0, 0.005 * abs(g))
        if abs((g - a) - n) > tol:
            log.warning("xbrl cross-check %s %s: gross=%s allow=%s net=%s",
                        r["ticker"], r["period_end"], g, a, n)
```

Wire this into your merge step. Warning-only — don't drop the record, but the warning surfaces the bug in logs immediately rather than weeks later when someone notices the dashboard is wrong.

### 3. XBRL coverage degrades over time. Always have a narrative fallback.

For HGV: `FinancingReceivableAllowanceForCreditLosses` last reported 2021-Q2. `NotesReceivableGross` stopped 2022. After those dates the values are only in the 10-Q/10-K text tables.

The fix: a `balance_sheet` narrative section in your extractor that asks Claude to find these values in MD&A text when XBRL is null. Keyword patterns that work for timeshare:

```python
"balance_sheet": [
    r"Timeshare financing receivables",
    r"vacation ownership notes receivable",
    r"Notes receivable, net",
    r"Allowance for (credit losses|loan losses|financing receivable)",
    r"Financing receivables",
],
```

## Companyfacts JSON Tips

- Path: `https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit-padded>.json`. Cache to disk (10–30 MB per issuer); the SEC has a 10 req/sec limit and you don't want to re-download.
- Required header: `User-Agent: <name> <email>` — anything else gets a 403.
- A single tag's value list contains both 10-K (annual) and 10-Q (quarterly) entries, with overlapping `end` dates. Filter by `(form, fp)` when matching to a specific filing — `fp=Q1/Q2/Q3/FY`.
- For instant tags (allowances, receivables) match on `end` date == filing's `period_end`. For duration tags (provisions, originations) the same `end` works but you must also check `start` to confirm it's a quarterly vs YTD figure.

## Sanity Bounds

After extraction, flag any value outside:
- `*_pct` fields: must be in [0, 1]. Anything outside means the issuer reported in basis points or whole-number percent.
- Allowance coverage `allowance / gross`: < 0.5% or > 50% is suspicious for a consumer lender. Timeshare lenders cluster 8–25%.
- Annual delinquency 90+ DPD: typically 1–10%. > 15% is a fingerprint of pulling a YTD writeoff number instead of a stock balance.

## Minimum Working Example

In `xbrl_fetch.py`:

```python
def fetch_metric(facts, candidate_tags, period_end, scale=1e-6):
    """Walk candidates in order. Return first match for period_end."""
    for ns in ("us-gaap",) + tuple(facts.keys() - {"us-gaap"}):
        for tag in candidate_tags:
            entry = facts.get(ns, {}).get(tag)
            if not entry: continue
            for unit, vals in entry.get("units", {}).items():
                for v in vals:
                    if v.get("end") == period_end and v.get("form") in ("10-K","10-Q"):
                        return v["val"] * scale
    return None
```

Importantly: the `_break_across_tags` failure mode — where a per-tag inner loop breaks out of the outer loop on first miss — has bitten us at least once. Make sure your loop structure tries ALL candidate tags before giving up.

## Files In This Project

- `/opt/site-deploy/timeshare-surveillance/config/settings.py` — `XBRL_TAG_MAP`
- `/opt/site-deploy/timeshare-surveillance/pipeline/xbrl_fetch.py`
- `/opt/site-deploy/timeshare-surveillance/pipeline/sec_cache.py` — disk cache (filings + companyfacts + submissions)
- `/opt/site-deploy/timeshare-surveillance/pipeline/merge.py` — `_check_receivable_arithmetic`

## Required Env

- `EDGAR_USER_AGENT` (any string with name + email; see `settings.py`)
- `ANTHROPIC_API_KEY` (only for the narrative fallback)

## Cost

Free for SEC EDGAR. Caching the companyfacts JSON makes re-extraction zero-network and fully repeatable.
