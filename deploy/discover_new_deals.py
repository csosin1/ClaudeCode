#!/usr/bin/env python3
"""Discover new Carvana / CarMax securitization entities on SEC EDGAR.

Each ABS deal issues through its own newly-formed trust with its own CIK.
So "new deal discovery" means finding CIKs *not* already present in either
issuer's DEALS config, and whose entity name matches the expected pattern.

Approach: query EDGAR full-text search for recent 424B / 8-K filings naming
the issuer ("Carvana Auto Receivables Trust" / "CarMax Auto Owner Trust"),
dedupe the CIKs returned, drop CIKs already in config, and emit a report.

We DO NOT auto-edit config.py. Malformed entries break the daily cron for
every user. Instead we log the finding and (if notify.sh exists) fire a
notification with the exact edit the user needs to make. A future enhancement
can add opt-in auto-add behind a flag once the detection has proven reliable.

Runs weekly from /etc/cron.d/abs-discover-deals. Install:
    cp deploy/cron.d/abs-discover-deals /etc/cron.d/abs-discover-deals
    chmod 644 /etc/cron.d/abs-discover-deals
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Make the project importable when run as a standalone script.
sys.path.insert(0, "/opt/abs-dashboard")

from carvana_abs.config import DEALS as CARVANA_DEALS  # noqa: E402
from carmax_abs.config import DEALS as CARMAX_DEALS  # noqa: E402

LOG_PATH = "/var/log/abs-dashboard/new_deals_discovered.log"
NOTIFY_BIN = "/usr/local/bin/notify.sh"

# SEC rate limit: 10 req/s. We stay well under by sleeping between requests.
REQUEST_DELAY = 0.2
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "Clifford Sosin clifford.sosin@casinvestmentpartners.com",
)

# Issuer patterns. Each entry:
#   full_name_query -> string to send to EDGAR full-text search
#   slug_regex      -> regex that extracts the canonical deal slug from the
#                      company name returned by EDGAR (e.g. "2026-P1")
#   config_key      -> which DEALS dict to compare CIKs against
#   label           -> human label used in the report
ISSUERS = [
    {
        "label": "Carvana",
        "full_name_query": "Carvana Auto Receivables Trust",
        "name_pattern": re.compile(
            r"Carvana Auto Receivables Trust\s+(20\d{2}-[PN]\d)",
            re.IGNORECASE,
        ),
        "config": CARVANA_DEALS,
        "config_module": "carvana_abs/config.py",
    },
    {
        "label": "CarMax",
        "full_name_query": "CarMax Auto Owner Trust",
        "name_pattern": re.compile(
            r"CarMax Auto Owner Trust\s+(20\d{2}-\d+)",
            re.IGNORECASE,
        ),
        "config": CARMAX_DEALS,
        "config_module": "carmax_abs/config.py",
    },
]


def _setup_logging() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers on repeated imports.
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == LOG_PATH
               for h in root.handlers):
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
        # Always log in UTC.
        logging.Formatter.converter = time.gmtime
        root.addHandler(fh)
    # Also echo to stdout when invoked interactively / from cron (cron appends
    # stdout to the same log via redirection, so we keep StreamHandler off to
    # avoid double-writes).
    return logging.getLogger("discover_new_deals")


log = _setup_logging()


def _http_get_json(url: str, max_retries: int = 3) -> dict | None:
    """GET with retries and SEC-required User-Agent. Returns parsed JSON or None."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    for attempt in range(max_retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
                # urlopen handles gzip only if we declare it; we strip manually.
                enc = resp.headers.get("Content-Encoding", "")
                if "gzip" in enc:
                    import gzip as _gz
                    raw = _gz.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt < max_retries:
                wait = 2 ** attempt
                log.warning("GET %s failed (%s); retry in %ds", url, e, wait)
                time.sleep(wait)
            else:
                log.error("GET %s failed after %d attempts: %s", url, max_retries + 1, e)
                return None
        finally:
            time.sleep(REQUEST_DELAY)
    return None


def _efts_search(query: str, forms: Iterable[str], days_back: int = 60) -> list[dict]:
    """Query EDGAR's full-text search and return hit records.

    EDGAR full-text search API:
      https://efts.sec.gov/LATEST/search-index?q=<query>&forms=<csv>&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD

    Returns the `hits.hits` array (each item has `_source` with cik, forms,
    display_names, file_date, adsh, etc.)
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days_back)
    params = {
        "q": f'"{query}"',
        "forms": ",".join(forms),
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
    }
    url = "https://efts.sec.gov/LATEST/search-index?" + urlencode(params)
    log.info("EDGAR search: %s", url)
    data = _http_get_json(url)
    if not data:
        return []
    return data.get("hits", {}).get("hits", [])


def _normalize_cik(cik_raw) -> str:
    """EDGAR returns CIK as int or int-string; normalize to 10-digit zero-padded."""
    if cik_raw is None:
        return ""
    s = str(cik_raw).strip()
    if not s.isdigit():
        # Sometimes formatted like "CIK0001234567" or "1234567"
        m = re.search(r"(\d+)", s)
        if not m:
            return ""
        s = m.group(1)
    return s.zfill(10)


def _known_ciks(config: dict) -> set[str]:
    return {_normalize_cik(d.get("cik")) for d in config.values()}


def _scan_issuer(issuer: dict) -> list[dict]:
    """Scan EDGAR for candidate new entities for one issuer. Returns list of
    {cik, entity_name, slug, first_seen_form, first_seen_date} dicts for any
    CIK NOT already present in the issuer's DEALS config."""
    known = _known_ciks(issuer["config"])
    # Search across the forms most likely to announce a new trust:
    # 424B* (prospectus supplements) and 8-K (mainly early asset-level reports).
    hits = _efts_search(
        query=issuer["full_name_query"],
        forms=("424B2", "424B3", "424B5", "8-K", "ABS-EE"),
        days_back=60,
    )
    found: dict[str, dict] = {}
    for hit in hits:
        src = hit.get("_source", {}) or {}
        # EDGAR returns parallel arrays for multi-filer filings.
        ciks = src.get("ciks") or []
        names = src.get("display_names") or []
        forms = src.get("forms") or src.get("form") or []
        file_date = src.get("file_date") or src.get("filed") or ""
        form_str = forms[0] if isinstance(forms, list) and forms else str(forms)
        # display_names look like: "Carvana Auto Receivables Trust 2024-P2 (CIK 0001999671)"
        for cik_raw, name in zip(ciks, names):
            cik = _normalize_cik(cik_raw)
            if not cik or cik in known:
                continue
            m = issuer["name_pattern"].search(name or "")
            if not m:
                continue
            slug = m.group(1)
            # Also skip if the slug is already in config (CIK mismatch on a known deal).
            if slug in issuer["config"]:
                log.warning(
                    "%s: slug %s already in config under CIK %s, but EDGAR returned new CIK %s for name %r — NOT treated as new deal",
                    issuer["label"], slug, issuer["config"][slug].get("cik"), cik, name,
                )
                continue
            if cik not in found:
                found[cik] = {
                    "cik": cik,
                    "entity_name": name,
                    "slug": slug,
                    "first_seen_form": form_str,
                    "first_seen_date": file_date,
                    "issuer": issuer["label"],
                    "config_module": issuer["config_module"],
                }
    return list(found.values())


def _emit_notification(new_deals: list[dict]) -> None:
    """Fire notify.sh with a compact summary. Silently no-op if the binary
    isn't installed (not all droplets have it)."""
    if not new_deals:
        return
    if not (os.path.isfile(NOTIFY_BIN) and os.access(NOTIFY_BIN, os.X_OK)):
        log.info("notify.sh not present at %s; skipping notification", NOTIFY_BIN)
        return
    lines = [f"ABS: {len(new_deals)} new deal(s) discovered on EDGAR"]
    for d in new_deals:
        lines.append(
            f"- {d['issuer']} {d['slug']} (CIK {d['cik']}) first seen on {d['first_seen_form']} {d['first_seen_date']}"
        )
    lines.append("To ingest, add the entry to the issuer's DEALS dict in "
                 "carvana_abs/config.py or carmax_abs/config.py.")
    msg = "\n".join(lines)
    try:
        subprocess.run([NOTIFY_BIN, msg], timeout=15, check=False)
    except Exception as e:  # noqa: BLE001
        log.warning("notify.sh invocation failed: %s", e)


def _format_config_snippet(d: dict) -> str:
    """Produce a copy-pasteable DEALS entry for the user."""
    if d["issuer"] == "Carvana":
        return (
            f'    "{d["slug"]}": {{\n'
            f'        "cik": "{d["cik"]}",\n'
            f'        "entity_name": "Carvana Auto Receivables Trust {d["slug"]}",\n'
            f'        "distribution_day": 8,\n'
            f'        "original_pool_balance": None,\n'
            f"    }},"
        )
    else:  # CarMax
        return (
            f'    "{d["slug"]}": {{"cik": "{d["cik"]}", '
            f'"entity_name": "CarMax Auto Owner Trust {d["slug"]}"}},'
        )


def main() -> int:
    log.info("=== discover_new_deals start ===")
    all_new: list[dict] = []
    for issuer in ISSUERS:
        try:
            new = _scan_issuer(issuer)
        except Exception as e:  # noqa: BLE001
            log.exception("scan failed for %s: %s", issuer["label"], e)
            continue
        log.info("%s: %d new deal candidate(s)", issuer["label"], len(new))
        for d in new:
            log.info(
                "  NEW: %s %s (CIK %s) first-seen %s on %s",
                d["issuer"], d["slug"], d["cik"], d["first_seen_date"], d["first_seen_form"],
            )
            log.info("  Add to %s:\n%s", d["config_module"], _format_config_snippet(d))
        all_new.extend(new)
    if all_new:
        _emit_notification(all_new)
    log.info("=== discover_new_deals done; %d total new deal(s) ===", len(all_new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
