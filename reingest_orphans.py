"""Re-ingest the 26 orphan filings identified in AUDIT_POSTFIX.md.

Orphan = filing with ingested_pool=1 but no row in pool_performance keyed by
its accession_number. Caused by the PK-collision bugs (stale-header +
amendment-lost) now fixed in both parsers.

Run: /opt/abs-venv/bin/python /opt/abs-dashboard/reingest_orphans.py
"""
from __future__ import annotations
import os
import sys
import sqlite3
from urllib.parse import urlparse

sys.path.insert(0, "/opt/abs-dashboard")

from carvana_abs.ingestion.servicer_parser import store_pool_data as cv_store
from carmax_abs.ingestion.servicer_parser import store_pool_data as cm_store


ISSUERS = [
    {
        "name": "carvana",
        "db": "/opt/abs-dashboard/carvana_abs/db/carvana_abs.db",
        "cache": "/opt/abs-dashboard/carvana_abs/filing_cache",
        "store": cv_store,
    },
    {
        "name": "carmax",
        "db": "/opt/abs-dashboard/carmax_abs/db/carmax_abs.db",
        "cache": "/opt/abs-dashboard/carmax_abs/filing_cache",
        "store": cm_store,
    },
]


def find_orphans(db_path: str):
    c = sqlite3.connect(db_path)
    try:
        rows = c.execute(
            """
            SELECT f.accession_number, f.deal, f.filing_type, f.filing_date,
                   f.servicer_cert_url
            FROM filings f
            WHERE f.ingested_pool = 1
              AND NOT EXISTS (
                  SELECT 1 FROM pool_performance pp
                  WHERE pp.accession_number = f.accession_number
              )
            ORDER BY f.deal, f.filing_date
            """
        ).fetchall()
    finally:
        c.close()
    return rows


def cache_path(cache_dir: str, url: str) -> str:
    parsed = urlparse(url)
    safe = parsed.path.strip("/").replace("/", "_")
    return os.path.join(cache_dir, safe)


def main():
    overall_before = 0
    overall_after = 0
    for issuer in ISSUERS:
        print(f"\n=== {issuer['name']} ===")
        orphans = find_orphans(issuer["db"])
        print(f"Found {len(orphans)} orphans")
        overall_before += len(orphans)
        ok = miss = fail = 0
        for acc, deal, ftype, fdate, url in orphans:
            path = cache_path(issuer["cache"], url)
            if not os.path.exists(path):
                print(f"  MISS {deal} {acc} type={ftype} fdate={fdate} -> no cached HTML at {path}")
                miss += 1
                continue
            with open(path, errors="replace") as f:
                html = f.read()
            try:
                result = issuer["store"](html, acc, deal, issuer["db"])
                if result:
                    print(f"  OK   {deal} {acc} type={ftype} fdate={fdate}")
                    ok += 1
                else:
                    print(f"  FAIL {deal} {acc} type={ftype} fdate={fdate} -> store returned False")
                    fail += 1
            except Exception as e:
                print(f"  EXC  {deal} {acc} type={ftype} fdate={fdate} -> {e}")
                fail += 1
        remaining = find_orphans(issuer["db"])
        overall_after += len(remaining)
        print(f"  result: ok={ok} miss={miss} fail={fail}; orphans now = {len(remaining)}")
        if remaining:
            for acc, deal, ftype, fdate, _ in remaining:
                print(f"    still-orphan: {deal} {acc} type={ftype} fdate={fdate}")
    print(f"\nTOTAL orphans: {overall_before} -> {overall_after}")


if __name__ == "__main__":
    main()
