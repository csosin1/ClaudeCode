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

    # Add weighted_avg_coupon column if missing (schema migration)
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(monthly_summary)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    if "weighted_avg_coupon" not in existing_cols:
        logger.info("Adding weighted_avg_coupon column to monthly_summary...")
        cursor.execute("ALTER TABLE monthly_summary ADD COLUMN weighted_avg_coupon REAL")
        conn.commit()

    # Ensure notes table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notes'")
    if not cursor.fetchone():
        logger.info("Creating notes table...")
        cursor.execute("""CREATE TABLE IF NOT EXISTS notes (
            deal TEXT NOT NULL, class TEXT NOT NULL,
            original_balance REAL, coupon_rate REAL, rate_type TEXT,
            spread REAL, benchmark TEXT, rating_moodys TEXT,
            rating_sp TEXT, rating_kbra TEXT,
            expected_maturity TEXT, legal_maturity TEXT,
            PRIMARY KEY (deal, class))""")
        conn.commit()
    conn.close()

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
