#!/usr/bin/env python3
"""Entry point for Carvana 2020-P1 ABS data ingestion from SEC EDGAR.

Usage:
    python -m carvana_abs.run_ingestion

Before running, set your SEC EDGAR User-Agent:
    export SEC_USER_AGENT="YourName your-email@example.com"
"""

import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.ingestion.ingest import run_full_ingestion
from carvana_abs.config import USER_AGENT


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    # Warn if using default User-Agent
    if "your-email@example.com" in USER_AGENT:
        logger.warning(
            "Using default SEC User-Agent. Set SEC_USER_AGENT env var with your "
            "name/email for SEC EDGAR compliance. Example:\n"
            '  export SEC_USER_AGENT="John Doe john@example.com"'
        )

    logger.info("Starting Carvana 2020-P1 ABS data ingestion...")
    logger.info(f"User-Agent: {USER_AGENT}")

    summary = run_full_ingestion()

    if summary["errors"]:
        logger.warning(f"Completed with {len(summary['errors'])} errors")
        sys.exit(1)
    else:
        logger.info("Ingestion completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
