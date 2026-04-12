#!/usr/bin/env python3
"""Fetch SEC EDGAR filings and extract credit metrics via Claude.

Usage:
    python pipeline/fetch_and_parse.py --ticker HGV
    python pipeline/fetch_and_parse.py --all
    python pipeline/fetch_and_parse.py --ticker HGV --dry-run
    python pipeline/fetch_and_parse.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running both as a module and as a script.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

log = logging.getLogger("fetch_and_parse")


# ---------------------------------------------------------------------------
# Metric schema — keep in sync with the user spec. Callers rely on key names.
# ---------------------------------------------------------------------------

METRIC_SCHEMA: dict[str, str] = {
    "gross_receivables_total_mm": "float, millions USD",
    "allowance_for_loan_losses_mm": "float, millions USD",
    "net_receivables_mm": "float, millions USD",
    "allowance_coverage_pct": "float 0-1, allowance as share of gross receivables",
    "provision_for_loan_losses_mm": "float, millions USD (period provision)",
    "delinquent_30_59_days_pct": "float 0-1",
    "delinquent_60_89_days_pct": "float 0-1",
    "delinquent_90_plus_days_pct": "float 0-1",
    "delinquent_total_pct": "float 0-1",
    "default_rate_annualized_pct": "float 0-1, annualized",
    "weighted_avg_fico_origination": "int FICO score, origination-weighted",
    "fico_700_plus_pct": "float 0-1",
    "fico_below_600_pct": "float 0-1",
    "avg_loan_size_dollars": "float, dollars",
    "avg_contract_term_months": "float, months",
    "securitized_receivables_mm": "float, millions USD",
    "retained_interests_mm": "float, millions USD",
    "warehouse_facility_balance_mm": "float, millions USD (outstanding)",
    "new_securitization_volume_mm": "float, millions USD (this period)",
    "new_securitization_advance_rate_pct": "float 0-1",
    "weighted_avg_coupon_new_deals_pct": "float 0-1",
    "overcollateralization_pct": "float 0-1",
    "gain_on_sale_mm": "float, millions USD",
    "gain_on_sale_margin_pct": "float 0-1, gain / originations",
    "originations_mm": "float, millions USD",
    "sales_to_existing_owners_pct": "float 0-1",
    "tour_flow_count": "int, number of tours this period",
    "vpg_dollars": "float, volume per guest (dollars)",
    "contract_rescission_rate_pct": "float 0-1",
    "weighted_avg_ltv_pct": "float 0-1",
    "vintage_pools": (
        "array of {vintage_year:int, original_balance_mm:float, "
        "cumulative_default_rate_pct:float 0-1, as_of_period:str}"
    ),
    "management_flagged_credit_concerns": "bool, true if management notes credit stress",
    "management_credit_commentary": "string, <=2 sentences summarizing management credit commentary",
}


SYSTEM_PROMPT = (
    "You are a senior credit analyst extracting timeshare-receivable credit "
    "metrics from SEC filings. Return ONLY valid JSON matching the schema. "
    "Use null for any field the filing does not explicitly disclose. Never "
    "invent numbers. Express percentages as decimals (12.5% -> 0.125). Express "
    "dollar amounts in millions unless the key name ends with _dollars. "
    "Be strict: if a value is implied but not stated, prefer null."
)


def _build_user_prompt(ticker: str, filing_type: str, period_end: str, html: str) -> str:
    schema_lines = "\n".join(f'  "{k}": {v}' for k, v in METRIC_SCHEMA.items())
    return (
        f"Issuer: {ticker}. Filing type: {filing_type}. Period ended: {period_end}.\n\n"
        f"Extract the following JSON object from the filing text below. Schema:\n"
        f"{{\n{schema_lines}\n}}\n\n"
        f"Rules:\n"
        f"- Return a single JSON object, no markdown fences, no commentary.\n"
        f"- Any field not disclosed: null.\n"
        f"- Percentages as decimals (7.1% -> 0.071).\n"
        f"- Dollar fields ending in _mm are in millions.\n"
        f"- vintage_pools: include every vintage year disclosed in the pool tables.\n\n"
        f"Filing text:\n-----\n{html}\n-----"
    )


# ---------------------------------------------------------------------------
# Rate-limited SEC HTTP client
# ---------------------------------------------------------------------------


class _EdgarClient:
    def __init__(self):
        import requests

        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": settings.EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": None,  # will be set per request
        })
        self._min_interval = 1.0 / max(1, settings.EDGAR_RATE_LIMIT_PER_SEC)
        self._last = 0.0

    def get(self, url: str) -> "requests.Response":
        import requests

        # Per-host header
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        # Rate limit (global, conservative).
        wait = self._min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)

        backoff = 1.0
        for attempt in range(6):
            self._last = time.time()
            headers = dict(self.s.headers)
            headers["Host"] = host
            try:
                r = self.s.get(url, headers=headers, timeout=60)
            except requests.RequestException as e:
                log.warning("edgar GET network error on %s: %s", url, e)
                time.sleep(min(backoff, 30))
                backoff *= 2
                continue
            if r.status_code in (429, 503):
                log.warning("edgar %s on %s, backing off %.1fs", r.status_code, url, backoff)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"EDGAR request failed repeatedly: {url}")


# ---------------------------------------------------------------------------
# HTML chunking
# ---------------------------------------------------------------------------


def _strip_html(html: str) -> str:
    # Light strip: remove scripts/styles, collapse whitespace. Claude can cope
    # with residual tags, but stripping keeps us under the token budget.
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _chunk(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# JSON extraction with retry
# ---------------------------------------------------------------------------


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _call_claude(client, ticker: str, filing_type: str, period_end: str, chunk_text: str) -> dict:
    import anthropic  # noqa: F401  (imported for type context)

    user_msg = _build_user_prompt(ticker, filing_type, period_end, chunk_text)
    resp = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text if resp.content else ""
    cleaned = _strip_json_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Single corrective retry
        log.warning("First JSON parse failed; retrying with corrective prompt")
        retry_resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. Return ONLY "
                        "the JSON object this time, no markdown fences, no prose. "
                        "Repeat the extraction."
                    ),
                },
            ],
        )
        raw2 = retry_resp.content[0].text if retry_resp.content else ""
        cleaned2 = _strip_json_fences(raw2)
        try:
            return json.loads(cleaned2)
        except json.JSONDecodeError:
            log.error("PARSE_ERROR: Claude returned non-JSON twice for %s %s %s",
                      ticker, filing_type, period_end)
            return _null_record(extraction_error=True)


def _null_record(extraction_error: bool = False) -> dict:
    rec = {k: None for k in METRIC_SCHEMA}
    rec["vintage_pools"] = []
    rec["management_flagged_credit_concerns"] = None
    if extraction_error:
        rec["extraction_error"] = True
    return rec


def _merge_chunks(records: list[dict]) -> dict:
    """First non-null per field across chunks."""
    out = _null_record()
    saw_error = False
    for rec in records:
        if rec.get("extraction_error"):
            saw_error = True
        for k in METRIC_SCHEMA:
            if out.get(k) in (None, [], "") and rec.get(k) not in (None, [], ""):
                out[k] = rec[k]
    if saw_error and all(out.get(k) in (None, []) for k in METRIC_SCHEMA):
        out["extraction_error"] = True
    return out


# ---------------------------------------------------------------------------
# EDGAR filing discovery + document fetch
# ---------------------------------------------------------------------------


def _list_filings(client: _EdgarClient, cik: str) -> list[dict]:
    """Return list of (accession, filing_type, period_end, primary_doc, filed_date)."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = client.get(url)
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    rows = []
    n = len(recent.get("accessionNumber", []))
    for i in range(n):
        ftype = recent["form"][i]
        if ftype not in settings.FILING_TYPES:
            continue
        rows.append({
            "accession": recent["accessionNumber"][i],
            "filing_type": ftype,
            "period_end": recent["reportDate"][i],
            "filed_date": recent["filingDate"][i],
            "primary_doc": recent["primaryDocument"][i],
        })
    return rows


def _primary_doc_url(cik: str, accession: str, primary_doc: str) -> str:
    acc_nodash = accession.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for archive URL
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}"


# ---------------------------------------------------------------------------
# Record I/O
# ---------------------------------------------------------------------------


def _raw_path(ticker: str, filing_type: str, period_end: str) -> Path:
    safe = filing_type.replace("/", "-")
    return settings.RAW_DIR / f"{ticker}_{safe}_{period_end}.json"


def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2, default=str)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Dry-run stub data
# ---------------------------------------------------------------------------


_DRY_RUN_STUBS: dict[str, dict] = {
    "HGV": {
        "period_end": "2025-03-31",
        "filing_type": "10-Q",
        "accession": "0001674168-25-000012",
        "metrics": {
            "gross_receivables_total_mm": 3450.0,
            "allowance_for_loan_losses_mm": 380.0,
            "net_receivables_mm": 3070.0,
            "allowance_coverage_pct": 0.110,
            "provision_for_loan_losses_mm": 54.0,
            "delinquent_30_59_days_pct": 0.018,
            "delinquent_60_89_days_pct": 0.011,
            "delinquent_90_plus_days_pct": 0.062,
            "delinquent_total_pct": 0.091,
            "default_rate_annualized_pct": 0.074,
            "weighted_avg_fico_origination": 720,
            "fico_700_plus_pct": 0.62,
            "fico_below_600_pct": 0.04,
            "avg_loan_size_dollars": 28500.0,
            "avg_contract_term_months": 120.0,
            "securitized_receivables_mm": 2120.0,
            "retained_interests_mm": 260.0,
            "warehouse_facility_balance_mm": 310.0,
            "new_securitization_volume_mm": 375.0,
            "new_securitization_advance_rate_pct": 0.92,
            "weighted_avg_coupon_new_deals_pct": 0.0635,
            "overcollateralization_pct": 0.14,
            "gain_on_sale_mm": 42.0,
            "gain_on_sale_margin_pct": 0.112,
            "originations_mm": 375.0,
            "sales_to_existing_owners_pct": 0.54,
            "tour_flow_count": 178000,
            "vpg_dollars": 3980.0,
            "contract_rescission_rate_pct": 0.118,
            "weighted_avg_ltv_pct": 0.87,
            "vintage_pools": [
                {"vintage_year": 2022, "original_balance_mm": 980.0, "cumulative_default_rate_pct": 0.071, "as_of_period": "2025-03-31"},
                {"vintage_year": 2023, "original_balance_mm": 1050.0, "cumulative_default_rate_pct": 0.054, "as_of_period": "2025-03-31"},
                {"vintage_year": 2024, "original_balance_mm": 1120.0, "cumulative_default_rate_pct": 0.023, "as_of_period": "2025-03-31"},
            ],
            "management_flagged_credit_concerns": False,
            "management_credit_commentary": (
                "Management observes an uptick in early-stage delinquency "
                "consistent with broader consumer stress but does not consider "
                "it a material change to credit trajectory."
            ),
        },
    },
    "VAC": {
        "period_end": "2025-03-31",
        "filing_type": "10-Q",
        "accession": "0001524358-25-000009",
        "metrics": {
            "gross_receivables_total_mm": 2280.0,
            "allowance_for_loan_losses_mm": 245.0,
            "net_receivables_mm": 2035.0,
            "allowance_coverage_pct": 0.107,
            "provision_for_loan_losses_mm": 41.0,
            "delinquent_30_59_days_pct": 0.021,
            "delinquent_60_89_days_pct": 0.013,
            "delinquent_90_plus_days_pct": 0.055,
            "delinquent_total_pct": 0.089,
            "default_rate_annualized_pct": 0.069,
            "weighted_avg_fico_origination": 732,
            "fico_700_plus_pct": 0.68,
            "fico_below_600_pct": 0.03,
            "avg_loan_size_dollars": 26100.0,
            "avg_contract_term_months": 120.0,
            "securitized_receivables_mm": 1380.0,
            "retained_interests_mm": 205.0,
            "warehouse_facility_balance_mm": 225.0,
            "new_securitization_volume_mm": 300.0,
            "new_securitization_advance_rate_pct": 0.905,
            "weighted_avg_coupon_new_deals_pct": 0.0612,
            "overcollateralization_pct": 0.135,
            "gain_on_sale_mm": 31.0,
            "gain_on_sale_margin_pct": 0.104,
            "originations_mm": 298.0,
            "sales_to_existing_owners_pct": 0.61,
            "tour_flow_count": 132000,
            "vpg_dollars": 3710.0,
            "contract_rescission_rate_pct": 0.109,
            "weighted_avg_ltv_pct": 0.86,
            "vintage_pools": [
                {"vintage_year": 2022, "original_balance_mm": 720.0, "cumulative_default_rate_pct": 0.062, "as_of_period": "2025-03-31"},
                {"vintage_year": 2023, "original_balance_mm": 810.0, "cumulative_default_rate_pct": 0.047, "as_of_period": "2025-03-31"},
                {"vintage_year": 2024, "original_balance_mm": 860.0, "cumulative_default_rate_pct": 0.019, "as_of_period": "2025-03-31"},
            ],
            "management_flagged_credit_concerns": False,
            "management_credit_commentary": (
                "Portfolio credit performance remains within historical ranges. "
                "Management continues to monitor lower-FICO tranches closely."
            ),
        },
    },
    "TNL": {
        "period_end": "2025-03-31",
        "filing_type": "10-Q",
        "accession": "0000052827-25-000014",
        "metrics": {
            "gross_receivables_total_mm": 3010.0,
            "allowance_for_loan_losses_mm": 295.0,
            "net_receivables_mm": 2715.0,
            "allowance_coverage_pct": 0.098,
            "provision_for_loan_losses_mm": 58.0,
            "delinquent_30_59_days_pct": 0.024,
            "delinquent_60_89_days_pct": 0.015,
            "delinquent_90_plus_days_pct": 0.068,
            "delinquent_total_pct": 0.107,
            "default_rate_annualized_pct": 0.082,
            "weighted_avg_fico_origination": 704,
            "fico_700_plus_pct": 0.57,
            "fico_below_600_pct": 0.068,
            "avg_loan_size_dollars": 22400.0,
            "avg_contract_term_months": 120.0,
            "securitized_receivables_mm": 1910.0,
            "retained_interests_mm": 240.0,
            "warehouse_facility_balance_mm": 365.0,
            "new_securitization_volume_mm": 340.0,
            "new_securitization_advance_rate_pct": 0.885,
            "weighted_avg_coupon_new_deals_pct": 0.0671,
            "overcollateralization_pct": 0.128,
            "gain_on_sale_mm": 28.0,
            "gain_on_sale_margin_pct": 0.084,
            "originations_mm": 333.0,
            "sales_to_existing_owners_pct": 0.49,
            "tour_flow_count": 210000,
            "vpg_dollars": 3420.0,
            "contract_rescission_rate_pct": 0.131,
            "weighted_avg_ltv_pct": 0.89,
            "vintage_pools": [
                {"vintage_year": 2022, "original_balance_mm": 860.0, "cumulative_default_rate_pct": 0.079, "as_of_period": "2025-03-31"},
                {"vintage_year": 2023, "original_balance_mm": 910.0, "cumulative_default_rate_pct": 0.061, "as_of_period": "2025-03-31"},
                {"vintage_year": 2024, "original_balance_mm": 950.0, "cumulative_default_rate_pct": 0.028, "as_of_period": "2025-03-31"},
            ],
            "management_flagged_credit_concerns": True,
            "management_credit_commentary": (
                "Management noted elevated early-stage delinquency in the "
                "lower-FICO cohort and has modestly tightened underwriting."
            ),
        },
    },
}


def _dry_run_write(ticker: str) -> Path:
    stub = _DRY_RUN_STUBS[ticker]
    rec = {
        "ticker": ticker,
        "filing_type": stub["filing_type"],
        "period_end": stub["period_end"],
        "accession": stub["accession"],
        "filed_date": stub["period_end"],
        "source_url": f"fixture://{ticker}_sample.html",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    }
    rec.update(stub["metrics"])
    path = _raw_path(ticker, stub["filing_type"], stub["period_end"])
    _write_record(path, rec)
    log.info("dry-run: wrote stub extract for %s -> %s", ticker, path)
    return path


# ---------------------------------------------------------------------------
# Main processing per ticker
# ---------------------------------------------------------------------------


def _get_target(ticker: str) -> dict:
    for t in settings.TARGETS:
        if t["ticker"].upper() == ticker.upper():
            return t
    raise ValueError(f"Unknown ticker: {ticker}")


def _extract_for_filing(
    anthropic_client,
    ticker: str,
    filing_type: str,
    period_end: str,
    source_url: str,
    text: str,
) -> dict:
    if len(text) > settings.FULL_DOC_CHAR_LIMIT:
        pieces = _chunk(text, settings.CHUNK_CHAR_LIMIT, settings.CHUNK_OVERLAP_CHARS)
    else:
        pieces = [text]

    chunk_records = []
    for idx, piece in enumerate(pieces):
        log.info("claude extract %s %s %s chunk %d/%d", ticker, filing_type,
                 period_end, idx + 1, len(pieces))
        chunk_records.append(
            _call_claude(anthropic_client, ticker, filing_type, period_end, piece)
        )

    merged = _merge_chunks(chunk_records)
    merged.update({
        "ticker": ticker,
        "filing_type": filing_type,
        "period_end": period_end,
        "source_url": source_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    })
    return merged


def process_ticker(ticker: str, dry_run: bool = False) -> list[Path]:
    settings.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return [_dry_run_write(ticker)]

    import anthropic

    api_key = settings.require("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=api_key)
    edgar = _EdgarClient()

    target = _get_target(ticker)
    cik = target["cik"]

    filings = _list_filings(edgar, cik)

    # Keep N most recent per filing type.
    by_type: dict[str, list[dict]] = {}
    for f in filings:
        by_type.setdefault(f["filing_type"], []).append(f)
    for k in by_type:
        by_type[k] = by_type[k][: settings.LOOKBACK_FILINGS]

    written = []
    for ftype, items in by_type.items():
        for f in items:
            out_path = _raw_path(ticker, ftype, f["period_end"])
            if out_path.exists():
                log.info("skip (cached) %s", out_path.name)
                continue
            url = _primary_doc_url(cik, f["accession"], f["primary_doc"])
            try:
                resp = edgar.get(url)
            except Exception as e:
                log.error("fetch failed %s: %s", url, e)
                continue
            text = _strip_html(resp.text)
            rec = _extract_for_filing(
                anthropic_client,
                ticker=ticker,
                filing_type=ftype,
                period_end=f["period_end"],
                source_url=url,
                text=text,
            )
            rec["accession"] = f["accession"]
            rec["filed_date"] = f["filed_date"]
            _write_record(out_path, rec)
            written.append(out_path)
            log.info("wrote %s", out_path)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _setup_logging():
    try:
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers = [
            logging.StreamHandler(),
            logging.FileHandler(settings.LOG_FILE),
        ]
    except PermissionError:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    _setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", choices=[t["ticker"] for t in settings.TARGETS])
    ap.add_argument("--all", action="store_true", help="Process every ticker in TARGETS")
    ap.add_argument("--dry-run", action="store_true",
                    help="Skip network/Anthropic calls; emit synthetic stub data")
    args = ap.parse_args()

    if not args.ticker and not args.all:
        ap.error("Specify --ticker TICK or --all")

    tickers = [t["ticker"] for t in settings.TARGETS] if args.all else [args.ticker]
    any_written = False
    for t in tickers:
        try:
            out = process_ticker(t, dry_run=args.dry_run)
            any_written = any_written or bool(out)
        except Exception as e:
            log.exception("ticker %s failed: %s", t, e)
    return 0 if any_written else 0


if __name__ == "__main__":
    sys.exit(main())
