#!/usr/bin/env python3
"""Hybrid XBRL-first + narrative-Claude filing extractor.

Per ticker:
  1. Pull companyfacts XBRL JSON once; derive period-indexed structured
     metrics (receivables, allowance, provision, originations, ...).
  2. List recent 10-K / 10-Q filings from the submissions API.
  3. For each filing: download the primary doc, locate named sections
     (delinquency / FICO / vintage / MD&A credit commentary), and send only
     those excerpts to Claude — one call per located section.
  4. Merge XBRL + narrative into a single METRIC_SCHEMA record. XBRL wins
     for fields it covers.
  5. Upsert into data/surveillance.db via pipeline.db.

Usage:
    python pipeline/fetch_and_parse.py --ticker HGV
    python pipeline/fetch_and_parse.py --all
    python pipeline/fetch_and_parse.py --ticker HGV --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402
from pipeline import db as pdb  # noqa: E402
from pipeline import narrative_extract as nx  # noqa: E402
from pipeline import sec_cache  # noqa: E402
from pipeline import xbrl_fetch as xf  # noqa: E402
from pipeline.metric_schema import METRIC_SCHEMA, null_record  # noqa: E402

log = logging.getLogger("fetch_and_parse")


# Re-export METRIC_SCHEMA for out-of-tree callers that may have imported it
# from this module in v1.
__all__ = ["METRIC_SCHEMA", "process_ticker", "main"]


# ---------------------------------------------------------------------------
# Rate-limited SEC HTTP client (shared with v1)
# ---------------------------------------------------------------------------


class _EdgarClient:
    def __init__(self):
        import requests

        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": settings.EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._min_interval = 1.0 / max(1, settings.EDGAR_RATE_LIMIT_PER_SEC)
        self._last = 0.0

    def get(self, url: str):
        import requests
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        wait = self._min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)

        backoff = 1.0
        for _ in range(6):
            self._last = time.time()
            headers = dict(self.s.headers)
            headers["Host"] = host
            try:
                r = self.s.get(url, headers=headers, timeout=60)
            except requests.RequestException as e:
                log.warning("edgar GET network error on %s: %s", url, e)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            if r.status_code in (429, 503):
                log.warning("edgar %s on %s; backing off %.1fs", r.status_code, url, backoff)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"EDGAR request failed repeatedly: {url}")


# ---------------------------------------------------------------------------
# EDGAR filing discovery
# ---------------------------------------------------------------------------


def _list_filings(client: _EdgarClient, cik: str) -> list[dict]:
    data = sec_cache.get_submissions(client, cik)
    recent = data.get("filings", {}).get("recent", {})
    rows: list[dict] = []
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
    cik_int = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}"


# ---------------------------------------------------------------------------
# Target lookup
# ---------------------------------------------------------------------------


def _get_target(ticker: str) -> dict:
    for t in settings.TARGETS:
        if t["ticker"].upper() == ticker.upper():
            return t
    raise ValueError(f"Unknown ticker: {ticker}")


# ---------------------------------------------------------------------------
# XBRL period matching
# ---------------------------------------------------------------------------


def _pick_xbrl_slice(
    xbrl_by_period: dict[str, dict],
    period_end: str,
) -> dict:
    """Return the XBRL metrics dict whose period key best matches period_end.

    Exact match preferred; otherwise the nearest earlier period (instant tags
    sometimes settle on the last business day, off by a day or two).
    """
    if not xbrl_by_period:
        return {}
    if period_end in xbrl_by_period:
        return dict(xbrl_by_period[period_end])

    # Fallback: same calendar quarter end within ±5 days, nearest earlier.
    target = period_end
    candidates = [p for p in xbrl_by_period.keys() if p <= target]
    if not candidates:
        return {}
    closest = max(candidates)
    # Only allow ≤ 5-day drift to avoid pulling the wrong quarter.
    try:
        from datetime import date
        d_target = date.fromisoformat(target)
        d_closest = date.fromisoformat(closest)
        if (d_target - d_closest).days > 5:
            return {}
    except ValueError:
        return {}
    log.info("xbrl: period fuzzy-match %s -> %s", target, closest)
    return dict(xbrl_by_period[closest])


# ---------------------------------------------------------------------------
# Dry-run stubs — same numbers as v1 so the dashboard snapshot is stable.
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
            "segments": [
                {"segment_key": "consolidated", "segment_label": "HGV consolidated", "segment_type": "consolidated",
                 "gross_receivables_total_mm": 3450.0, "allowance_for_loan_losses_mm": 380.0, "allowance_coverage_pct": 0.110,
                 "provision_for_loan_losses_mm": 54.0, "delinquent_30_59_days_pct": 0.018, "delinquent_60_89_days_pct": 0.011,
                 "delinquent_90_plus_days_pct": 0.062, "delinquent_total_pct": 0.091, "default_rate_annualized_pct": 0.074,
                 "weighted_avg_fico_origination": 720, "fico_700_plus_pct": 0.62, "fico_below_600_pct": 0.04,
                 "originations_mm": 375.0, "as_of_period": "2025-03-31"},
                {"segment_key": "legacy_hgv", "segment_label": "Legacy-HGV", "segment_type": "brand",
                 "gross_receivables_total_mm": 1520.0, "allowance_for_loan_losses_mm": 140.0, "allowance_coverage_pct": 0.092,
                 "provision_for_loan_losses_mm": 20.0, "delinquent_30_59_days_pct": 0.013, "delinquent_60_89_days_pct": 0.008,
                 "delinquent_90_plus_days_pct": 0.042, "delinquent_total_pct": 0.063, "default_rate_annualized_pct": 0.055,
                 "weighted_avg_fico_origination": 738, "fico_700_plus_pct": 0.71, "fico_below_600_pct": 0.022,
                 "originations_mm": 165.0, "as_of_period": "2025-03-31"},
                {"segment_key": "diamond", "segment_label": "Diamond", "segment_type": "brand",
                 "gross_receivables_total_mm": 1050.0, "allowance_for_loan_losses_mm": 140.0, "allowance_coverage_pct": 0.133,
                 "provision_for_loan_losses_mm": 20.0, "delinquent_30_59_days_pct": 0.023, "delinquent_60_89_days_pct": 0.014,
                 "delinquent_90_plus_days_pct": 0.082, "delinquent_total_pct": 0.119, "default_rate_annualized_pct": 0.094,
                 "weighted_avg_fico_origination": 701, "fico_700_plus_pct": 0.54, "fico_below_600_pct": 0.061,
                 "originations_mm": 118.0, "as_of_period": "2025-03-31"},
                {"segment_key": "bluegreen", "segment_label": "Bluegreen", "segment_type": "brand",
                 "gross_receivables_total_mm": 880.0, "allowance_for_loan_losses_mm": 100.0, "allowance_coverage_pct": 0.114,
                 "provision_for_loan_losses_mm": 14.0, "delinquent_30_59_days_pct": 0.019, "delinquent_60_89_days_pct": 0.012,
                 "delinquent_90_plus_days_pct": 0.068, "delinquent_total_pct": 0.099, "default_rate_annualized_pct": 0.078,
                 "weighted_avg_fico_origination": 712, "fico_700_plus_pct": 0.59, "fico_below_600_pct": 0.046,
                 "originations_mm": 92.0, "as_of_period": "2025-03-31"},
                {"segment_key": "originated", "segment_label": "Originated post-acquisition", "segment_type": "acquisition_cohort",
                 "gross_receivables_total_mm": 2150.0, "allowance_for_loan_losses_mm": 210.0, "allowance_coverage_pct": 0.098,
                 "delinquent_90_plus_days_pct": 0.048, "delinquent_total_pct": 0.072,
                 "weighted_avg_fico_origination": 728, "as_of_period": "2025-03-31"},
                {"segment_key": "acquired_at_fv", "segment_label": "Acquired at fair value", "segment_type": "acquisition_cohort",
                 "gross_receivables_total_mm": 1300.0, "allowance_for_loan_losses_mm": 170.0, "allowance_coverage_pct": 0.131,
                 "delinquent_90_plus_days_pct": 0.085, "delinquent_total_pct": 0.123,
                 "weighted_avg_fico_origination": 704, "as_of_period": "2025-03-31"},
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
            "segments": [
                {"segment_key": "consolidated", "segment_label": "VAC consolidated", "segment_type": "consolidated",
                 "gross_receivables_total_mm": 2280.0, "allowance_for_loan_losses_mm": 245.0, "allowance_coverage_pct": 0.107,
                 "provision_for_loan_losses_mm": 41.0, "delinquent_90_plus_days_pct": 0.055, "delinquent_total_pct": 0.089,
                 "weighted_avg_fico_origination": 732, "fico_below_600_pct": 0.03, "originations_mm": 298.0,
                 "as_of_period": "2025-03-31"},
                {"segment_key": "marriott", "segment_label": "Marriott Vacation Club", "segment_type": "brand",
                 "gross_receivables_total_mm": 1580.0, "allowance_for_loan_losses_mm": 160.0, "allowance_coverage_pct": 0.101,
                 "delinquent_90_plus_days_pct": 0.049, "delinquent_total_pct": 0.081,
                 "weighted_avg_fico_origination": 741, "originations_mm": 210.0, "as_of_period": "2025-03-31"},
                {"segment_key": "vistana", "segment_label": "Vistana", "segment_type": "brand",
                 "gross_receivables_total_mm": 700.0, "allowance_for_loan_losses_mm": 85.0, "allowance_coverage_pct": 0.121,
                 "delinquent_90_plus_days_pct": 0.069, "delinquent_total_pct": 0.105,
                 "weighted_avg_fico_origination": 712, "originations_mm": 88.0, "as_of_period": "2025-03-31"},
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
            "segments": [
                {"segment_key": "consolidated", "segment_label": "TNL consolidated", "segment_type": "consolidated",
                 "gross_receivables_total_mm": 3010.0, "allowance_for_loan_losses_mm": 295.0, "allowance_coverage_pct": 0.098,
                 "provision_for_loan_losses_mm": 58.0, "delinquent_90_plus_days_pct": 0.068, "delinquent_total_pct": 0.107,
                 "weighted_avg_fico_origination": 704, "fico_below_600_pct": 0.068, "originations_mm": 333.0,
                 "as_of_period": "2025-03-31"},
            ],
            "management_flagged_credit_concerns": True,
            "management_credit_commentary": (
                "Management noted elevated early-stage delinquency in the "
                "lower-FICO cohort and has modestly tightened underwriting."
            ),
        },
    },
}


def _dry_run_process(ticker: str) -> int:
    """Write the stub record through db.upsert_filing (no network, no Claude)."""
    stub = _DRY_RUN_STUBS[ticker]
    rec = null_record()
    rec.update(stub["metrics"])
    rec.update({
        "ticker": ticker,
        "filing_type": stub["filing_type"],
        "period_end": stub["period_end"],
        "accession": stub["accession"],
        "filed_date": stub["period_end"],
        "source_url": f"fixture://{ticker}_sample.html",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
    })
    pdb.init_db(settings.SQLITE_DB_PATH)
    pdb.upsert_filing(settings.SQLITE_DB_PATH, rec)
    log.info("dry-run: upserted stub for %s (%s %s)",
             ticker, stub["filing_type"], stub["period_end"])
    return 1


# ---------------------------------------------------------------------------
# Main per-ticker processing
# ---------------------------------------------------------------------------


def _log_xbrl_coverage(ticker: str, xbrl_by_period: dict[str, dict]) -> None:
    """Log a one-line summary of XBRL coverage per key metric across periods.

    Helps diagnose gaps (e.g. allowance=0/36) at a glance in the log without
    needing to re-query the DB after extraction.
    """
    if not xbrl_by_period:
        log.info("xbrl coverage %s: (no periods loaded)", ticker)
        return
    total = len(xbrl_by_period)
    tracked = [
        ("gross", "gross_receivables_total_mm"),
        ("allowance", "allowance_for_loan_losses_mm"),
        ("provision", "provision_for_loan_losses_mm"),
        ("originations", "originations_mm"),
        ("vintages", "vintage_pools"),
    ]
    parts = []
    for label, key in tracked:
        hits = sum(
            1 for b in xbrl_by_period.values()
            if b.get(key) not in (None, [], "")
        )
        parts.append(f"{label}={hits}/{total}")
    log.info("xbrl coverage %s: %s", ticker, " ".join(parts))


def _merge_xbrl_and_narrative(
    xbrl_slice: dict,
    narrative: dict,
) -> dict:
    """XBRL wins for scalar fields it covers; narrative fills the rest.

    `segments` is narrative-only (XBRL doesn't express segment breakdowns
    reliably). `vintage_pools` is narrative-preferred when it includes a
    non-null cumulative_default_rate_pct (the static-pool table is the
    authoritative source for default rates); otherwise fall back to the
    XBRL-derived balances.
    """
    rec = null_record()
    for k, v in narrative.items():
        if v not in (None, [], ""):
            rec[k] = v
    for k, v in xbrl_slice.items():
        if v is None or k in ("segments", "vintage_pools"):
            continue
        rec[k] = v

    # vintage_pools selection — narrative wins if it has default-rate data.
    narr_vp = narrative.get("vintage_pools") or []
    xbrl_vp = xbrl_slice.get("vintage_pools") or []
    narrative_has_defaults = any(
        isinstance(p, dict) and p.get("cumulative_default_rate_pct") is not None
        for p in narr_vp
    )
    if narrative_has_defaults:
        rec["vintage_pools"] = narr_vp
    elif xbrl_vp:
        rec["vintage_pools"] = xbrl_vp
    elif narr_vp:
        rec["vintage_pools"] = narr_vp

    # Narrative wins for the segments array unconditionally.
    if narrative.get("segments"):
        rec["segments"] = narrative["segments"]
    return rec


def process_ticker(ticker: str, dry_run: bool = False) -> int:
    """Process the N most recent 10-K/10-Q filings for `ticker`.

    Returns the number of filings written.
    """
    pdb.init_db(settings.SQLITE_DB_PATH)
    if dry_run:
        return _dry_run_process(ticker)

    import anthropic

    api_key = settings.require("ANTHROPIC_API_KEY")
    anthropic_client = anthropic.Anthropic(api_key=api_key)
    edgar = _EdgarClient()

    target = _get_target(ticker)
    cik = target["cik"]

    # 1. XBRL once per ticker.
    try:
        xbrl_by_period = xf.fetch_metrics(cik)
        log.info("xbrl: %s loaded %d periods", ticker, len(xbrl_by_period))
    except Exception as e:
        log.error("xbrl fetch failed for %s: %s; continuing with narrative-only", ticker, e)
        xbrl_by_period = {}

    _log_xbrl_coverage(ticker, xbrl_by_period)

    # 2. Filing list.
    try:
        filings = _list_filings(edgar, cik)
    except Exception as e:
        log.error("submissions fetch failed for %s: %s", ticker, e)
        return 0

    by_type: dict[str, list[dict]] = {}
    for f in filings:
        by_type.setdefault(f["filing_type"], []).append(f)
    for k in by_type:
        by_type[k] = by_type[k][: settings.LOOKBACK_FILINGS]

    written = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for ftype, items in by_type.items():
        for f in items:
            period_end = f["period_end"]
            accession = f["accession"]
            url = _primary_doc_url(cik, accession, f["primary_doc"])

            # 3. Download filing HTML (cache-first; SEC primary-docs are
            # immutable per accession, so the cache is keep-forever).
            try:
                html = sec_cache.get_filing_html(edgar, ticker, accession, url)
            except Exception as e:
                log.error("fetch failed %s: %s", url, e)
                continue

            # 4. Narrative extraction (one Claude call per located section).
            sections = nx.locate_sections(html)
            if sections:
                narrative, usage = nx.extract_from_sections(
                    anthropic_client, ticker, ftype, period_end, sections,
                )
                total_input_tokens += usage.get("total_input_tokens", 0) or 0
                total_output_tokens += usage.get("total_output_tokens", 0) or 0
                log.info(
                    "narrative %s %s %s: sections=%s input_tokens=%d output_tokens=%d",
                    ticker, ftype, period_end,
                    list(sections.keys()),
                    usage.get("total_input_tokens", 0),
                    usage.get("total_output_tokens", 0),
                )
            else:
                narrative = {}
                log.info("narrative %s %s %s: no sections located; skipping Claude",
                         ticker, ftype, period_end)

            # 5. Merge XBRL + narrative; persist.
            xbrl_slice = _pick_xbrl_slice(xbrl_by_period, period_end)
            rec = _merge_xbrl_and_narrative(xbrl_slice, narrative)
            rec.update({
                "ticker": ticker,
                "filing_type": ftype,
                "period_end": period_end,
                "accession": accession,
                "filed_date": f["filed_date"],
                "source_url": url,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            })

            try:
                pdb.upsert_filing(settings.SQLITE_DB_PATH, rec)
                written += 1
                log.info("db: upserted %s %s %s (accession=%s)",
                         ticker, ftype, period_end, accession)
            except Exception as e:
                log.error("db upsert failed for %s %s: %s", ticker, accession, e)

    log.info(
        "ticker %s complete: filings=%d input_tokens=%d output_tokens=%d",
        ticker, written, total_input_tokens, total_output_tokens,
    )
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
    for t in tickers:
        try:
            process_ticker(t, dry_run=args.dry_run)
        except Exception as e:
            log.exception("ticker %s failed: %s", t, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
