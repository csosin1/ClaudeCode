#!/usr/bin/env python3
"""Entry point for Carvana ABS data ingestion from SEC EDGAR.

Usage:
    # Ingest all active deals:
    python -m carvana_abs.run_ingestion

    # Ingest a specific deal:
    python -m carvana_abs.run_ingestion --deal 2020-P1

    # List available deals:
    python -m carvana_abs.run_ingestion --list

Before running, set your SEC EDGAR User-Agent:
    export SEC_USER_AGENT="YourName your-email@example.com"
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.ingestion.ingest import run_full_ingestion
from carvana_abs.config import USER_AGENT, DEALS, get_active_deals


def main():
    parser = argparse.ArgumentParser(description="Ingest Carvana ABS data from SEC EDGAR")
    parser.add_argument("--deal", type=str, help="Specific deal slug to ingest (e.g., 2020-P1)")
    parser.add_argument("--list", action="store_true", help="List available deals and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    if args.list:
        print("Available deals:")
        for slug, cfg in DEALS.items():
            print(f"  {slug}: {cfg['entity_name']} (CIK {cfg['cik']})")
        sys.exit(0)

    if "your-email@example.com" in USER_AGENT:
        logger.warning(
            "Using default SEC User-Agent. Set SEC_USER_AGENT env var with your "
            "name/email for SEC EDGAR compliance. Example:\n"
            '  export SEC_USER_AGENT="John Doe john@example.com"'
        )

    deals = [args.deal] if args.deal else None
    logger.info(f"Starting ingestion for deals: {deals or get_active_deals()}")
    logger.info(f"User-Agent: {USER_AGENT}")

    summaries = run_full_ingestion(deals=deals)

    total_errors = sum(len(s["errors"]) for s in summaries)
    if total_errors:
        logger.warning(f"Completed with {total_errors} errors across {len(summaries)} deals")
        sys.exit(1)
    else:
        logger.info("Ingestion completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
