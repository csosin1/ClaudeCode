"""Fetch and parse SEC XBRL companyfacts JSON.

Endpoint: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json

The JSON shape is:
    {
      "facts": {
        "us-gaap": {
          "TagName": {
            "units": {
              "USD": [
                {"end": "2025-03-31", "val": 3450000000,
                 "accn": "0001674168-25-000012", "fy": 2025, "fp": "Q1",
                 "form": "10-Q", "filed": "2025-05-02"},
                ...
              ]
            }
          }
        },
        "<company-ext-namespace>": { ... }
      }
    }

We transform that into a period-indexed dict:
    {
      "2025-03-31": {
        "gross_receivables_total_mm": 3450.0,
        "allowance_for_loan_losses_mm": 380.0,
        ...
      },
      "2024-12-31": { ... }
    }

Per-tag scaling comes from settings.XBRL_TAG_MAP. Supports an offline fixture
path so unit tests (and --dry-run) never hit the network.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

log = logging.getLogger("xbrl_fetch")


COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _normalise_cik(cik: str | int) -> str:
    s = str(cik).strip().lstrip("0") or "0"
    return s.zfill(10)


def _load_local(path: Path | str) -> dict:
    with open(path) as f:
        return json.load(f)


def _fetch_network(cik: str) -> dict:
    """HTTP GET the companyfacts endpoint. Rate-limited + simple backoff."""
    import requests  # local import keeps this module importable without deps

    url = COMPANY_FACTS_URL.format(cik=_normalise_cik(cik))
    min_interval = 1.0 / max(1, settings.EDGAR_RATE_LIMIT_PER_SEC)
    backoff = 1.0
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": settings.EDGAR_USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                    "Host": "data.sec.gov",
                },
                timeout=60,
            )
            if resp.status_code in (429, 503):
                log.warning("xbrl %s on %s; backing off %.1fs",
                            resp.status_code, url, backoff)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            resp.raise_for_status()
            # Polite spacing between calls for the next caller.
            time.sleep(min_interval)
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            log.warning("xbrl GET network error on %s: %s", url, e)
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
    raise RuntimeError(f"XBRL companyfacts fetch failed for CIK {cik}: {last_err}")


def load_companyfacts(cik: str | int, fixture_path: Path | str | None = None) -> dict:
    """Load companyfacts JSON from fixture or network (via sec_cache).

    `fixture_path` wins when provided; otherwise we go through sec_cache so
    the JSON is persisted to disk and reused on subsequent runs (TTL-gated).
    """
    if fixture_path:
        log.info("xbrl: loading companyfacts fixture %s", fixture_path)
        return _load_local(fixture_path)
    # Late import keeps sec_cache importable from xbrl_fetch's own callers.
    from pipeline import sec_cache  # noqa: PLC0415

    return sec_cache.get_xbrl_facts(client=None, cik=str(cik), fetcher=_fetch_network)


def _iter_fact_namespaces(cf: dict):
    """Yield (namespace, facts_dict). us-gaap first, then company extensions."""
    facts = cf.get("facts") or {}
    if "us-gaap" in facts:
        yield "us-gaap", facts["us-gaap"]
    for ns, body in facts.items():
        if ns == "us-gaap":
            continue
        yield ns, body


def _best_unit(tag_body: dict, preferred: str) -> tuple[str, list[dict]] | None:
    """Return (unit, rows) picking the preferred unit when present."""
    units = tag_body.get("units") or {}
    if not units:
        return None
    if preferred in units:
        return preferred, units[preferred]
    # Some filers tag USD as "USD/shares" etc; accept first unit as a fallback.
    first_key = next(iter(units))
    return first_key, units[first_key]


def _period_key(row: dict) -> str | None:
    """Use 'end' when present; fall back to 'instant' (point-in-time tags)."""
    return row.get("end") or row.get("instant")


def extract_metrics_by_period(cf: dict) -> dict[str, dict[str, float]]:
    """Build {period_end: {metric_key: scaled_value}} from companyfacts JSON.

    Walks settings.XBRL_TAG_MAP. For each metric we take the first candidate
    tag that has values, and for each disclosed period we keep the most-
    recently-filed (max `filed`) value — this handles amendments cleanly.
    """
    out: dict[str, dict[str, float]] = {}

    # Flatten namespaces -> {tag_name: (unit, rows, namespace)}
    tag_index: dict[str, tuple[str, list[dict], str]] = {}
    for ns, ns_body in _iter_fact_namespaces(cf):
        for tag_name, tag_body in (ns_body or {}).items():
            # If the same local tag appears in multiple namespaces, us-gaap
            # wins because we iterate us-gaap first and skip on re-encounter.
            if tag_name in tag_index:
                continue
            picked = _best_unit(tag_body, "USD")
            if not picked:
                continue
            unit, rows = picked
            tag_index[tag_name] = (unit, rows, ns)

    for metric_key, cfg in settings.XBRL_TAG_MAP.items():
        candidates = cfg.get("tags", [])
        preferred_unit = cfg.get("unit", "USD")
        scale = float(cfg.get("scale", 1.0))
        for tag_name in candidates:
            if tag_name not in tag_index:
                continue
            unit, rows, ns = tag_index[tag_name]
            if unit != preferred_unit:
                log.debug(
                    "xbrl: %s unit mismatch for %s (got %s, want %s); skipping",
                    metric_key, tag_name, unit, preferred_unit,
                )
                continue
            # Pick best row per period: prefer 10-K/10-Q forms, latest `filed`.
            per_period: dict[str, dict] = {}
            for r in rows:
                pk = _period_key(r)
                if not pk:
                    continue
                if "val" not in r:
                    continue
                incumbent = per_period.get(pk)
                if incumbent is None:
                    per_period[pk] = r
                    continue
                # Prefer the row with the later `filed` date; if tied, prefer
                # rows whose form is in settings.FILING_TYPES.
                new_filed = r.get("filed", "")
                old_filed = incumbent.get("filed", "")
                if new_filed > old_filed:
                    per_period[pk] = r
                elif new_filed == old_filed:
                    new_form = r.get("form") in settings.FILING_TYPES
                    old_form = incumbent.get("form") in settings.FILING_TYPES
                    if new_form and not old_form:
                        per_period[pk] = r

            for pk, row in per_period.items():
                try:
                    scaled = float(row["val"]) * scale
                except (TypeError, ValueError):
                    continue
                bucket = out.setdefault(pk, {})
                # First candidate tag to populate the metric for THIS period
                # wins (ordering in XBRL_TAG_MAP["tags"]). We intentionally do
                # NOT break across candidates: a legacy tag may cover only
                # ancient periods while the preferred tag covers current
                # periods (e.g. TNL's "FinancingReceivable" has 2011 data,
                # and "NotesReceivableGross" has 2019-2025). Letting later
                # candidates fill gaps keeps coverage across the full range.
                bucket.setdefault(metric_key, scaled)

    # Derived: allowance_coverage_pct = allowance / gross when both present.
    for pk, bucket in out.items():
        gross = bucket.get("gross_receivables_total_mm")
        allow = bucket.get("allowance_for_loan_losses_mm")
        if gross and allow is not None:
            try:
                bucket["allowance_coverage_pct"] = round(float(allow) / float(gross), 6)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    # Derived: vintage_pools from the FinancingReceivableOriginated* tag family.
    _attach_xbrl_vintage_pools(out, tag_index)

    return out


def _attach_xbrl_vintage_pools(
    out: dict[str, dict],
    tag_index: dict[str, tuple[str, list[dict], str]],
) -> None:
    """Stitch the FinancingReceivableOriginated* tags into vintage_pools.

    Each tag covers a vintage-year offset from the period's fiscal year. We
    produce one vintage_pools entry per (period_end, offset) where a value
    exists. cumulative_default_rate_pct is left None — XBRL doesn't carry it.
    The narrative extractor fills it in when a static-pool table is disclosed.
    """
    from datetime import date

    offsets = getattr(settings, "XBRL_VINTAGE_TAG_OFFSETS", [])
    if not offsets:
        return

    # Collect per-period per-offset the best (latest-filed) row.
    per_period: dict[str, dict[int, dict]] = {}
    for tag_name, offset in offsets:
        if tag_name not in tag_index:
            continue
        unit, rows, _ns = tag_index[tag_name]
        if unit != "USD":
            continue
        period_best: dict[str, dict] = {}
        for r in rows:
            pk = _period_key(r)
            if not pk or "val" not in r:
                continue
            inc = period_best.get(pk)
            if inc is None or r.get("filed", "") > inc.get("filed", ""):
                period_best[pk] = r
        for pk, row in period_best.items():
            per_period.setdefault(pk, {})[offset] = row

    for pk, offset_rows in per_period.items():
        try:
            fy_year = date.fromisoformat(pk).year
        except ValueError:
            continue
        pools: list[dict] = []
        for offset, row in sorted(offset_rows.items()):
            try:
                bal_mm = round(float(row["val"]) * 1e-6, 3)
            except (TypeError, ValueError):
                continue
            pools.append({
                "vintage_year": fy_year - offset,
                "original_balance_mm": bal_mm,
                "cumulative_default_rate_pct": None,
                "as_of_period": pk,
            })
        if pools:
            # Keep most-recent vintages first for display stability.
            pools.sort(key=lambda p: p["vintage_year"], reverse=True)
            out.setdefault(pk, {})["vintage_pools"] = pools


def fetch_metrics(
    cik: str | int,
    fixture_path: Path | str | None = None,
) -> dict[str, dict[str, float]]:
    """Top-level helper: load companyfacts, return period-indexed metrics."""
    cf = load_companyfacts(cik, fixture_path=fixture_path)
    return extract_metrics_by_period(cf)
