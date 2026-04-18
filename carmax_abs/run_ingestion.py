#!/usr/bin/env python3
"""Entry point for CarMax ABS data ingestion from SEC EDGAR.

Mirrors carvana_abs/run_ingestion.py — same flow, different config.

Usage:
    python -m carmax_abs.run_ingestion          # ingest all deals
    python -m carmax_abs.run_ingestion --deal 2020-1
    python -m carmax_abs.run_ingestion --list
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carmax_abs.ingestion.ingest import run_full_ingestion
from carmax_abs.config import USER_AGENT, DEALS, get_active_deals


def main():
    parser = argparse.ArgumentParser(description="Ingest CarMax ABS data from SEC EDGAR")
    parser.add_argument("--deal", help="Specific deal slug (e.g. 2020-1)")
    parser.add_argument("--list", action="store_true", help="List available deals")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.list:
        for k, v in DEALS.items():
            print(f"  {k}  CIK={v['cik']}  {v['entity_name']}")
        return

    if "your-email" in USER_AGENT:
        print("ERROR: set SEC_USER_AGENT env var (e.g. 'YourName your-email@example.com')")
        sys.exit(1)

    deals = [args.deal] if args.deal else get_active_deals()
    summaries = run_full_ingestion(deals=deals)
    print(f"Ingestion completed for {len(summaries)} deals.")


if __name__ == "__main__":
    main()
