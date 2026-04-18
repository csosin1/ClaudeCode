#!/usr/bin/env python3
"""Quick-start script to verify SEC EDGAR connectivity and show filing counts.

Run this first to confirm your environment can reach SEC EDGAR:
    export SEC_USER_AGENT="YourName your-email@example.com"
    python -m carvana_abs.verify_access
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.config import DEALS, USER_AGENT, HEADERS
from carvana_abs.ingestion.edgar_client import fetch_url


def main():
    print("=" * 60)
    print("SEC EDGAR Access Verification")
    print("=" * 60)
    print(f"User-Agent: {USER_AGENT}")
    print()

    if "your-email@example.com" in USER_AGENT:
        print("WARNING: Using default User-Agent. Set SEC_USER_AGENT env var!")
        print('  export SEC_USER_AGENT="Your Name your-email@example.com"')
        print()

    for slug, cfg in DEALS.items():
        cik = cfg["cik"]
        print(f"Deal: {slug} ({cfg['entity_name']})")
        print(f"  CIK: {cik}")

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        print(f"  Fetching: {url}")

        data = fetch_url(url, max_retries=2, as_json=True)
        if data is None:
            print("  FAILED - Cannot reach SEC EDGAR.")
            print("  Check your internet connection and User-Agent setting.")
            continue

        # Count filings by type
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        type_counts = {}
        for f in forms:
            type_counts[f] = type_counts.get(f, 0) + 1

        print(f"  Entity: {data.get('name', 'N/A')}")
        print(f"  Recent filings: {len(forms)}")
        for ftype in ["10-D", "10-D/A", "ABS-EE", "ABS-EE/A", "10-K"]:
            if ftype in type_counts:
                print(f"    {ftype}: {type_counts[ftype]}")

        # Check for older filings
        older = data.get("filings", {}).get("files", [])
        if older:
            print(f"  Additional filing batches: {len(older)}")
            for f in older:
                print(f"    {f.get('name')}: {f.get('filingFrom', '?')} to {f.get('filingTo', '?')}")

        print("  ACCESS OK!")
        print()

    print("=" * 60)
    print("If all deals show 'ACCESS OK', run the full ingestion:")
    print("  python -m carvana_abs.run_ingestion")
    print("=" * 60)


if __name__ == "__main__":
    main()
