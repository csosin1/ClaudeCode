#!/usr/bin/env python3
"""Rebuild pre-computed summary tables from existing data.

Run this after schema changes or to refresh summaries without re-downloading.
    python -m carvana_abs.rebuild_summaries
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.db.schema import init_db, get_connection
from carvana_abs.config import DB_PATH, get_active_deals
from carvana_abs.ingestion.ingest import _precompute_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Rebuilding summary tables...")
    init_db(DB_PATH)  # ensures new tables exist

    for deal in get_active_deals():
        # Check if deal has any loan_performance data
        conn = get_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM loan_performance WHERE deal = ?", (deal,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            logger.info(f"[{deal}] Rebuilding summaries ({count:,} performance records)...")
            _precompute_summaries(deal, DB_PATH)
        else:
            logger.info(f"[{deal}] No performance data, skipping.")

    logger.info("Done!")


if __name__ == "__main__":
    main()
