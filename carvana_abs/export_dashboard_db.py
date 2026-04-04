#!/usr/bin/env python3
"""Export dashboard-only tables to a small, fast database.

The main carvana_abs.db is 1.7GB because of the loan_performance table (20M+ rows).
The dashboard never reads loan_performance directly — it uses pre-computed summary tables.
This script copies just the tables the dashboard needs into a ~50MB file.

Usage: python carvana_abs/export_dashboard_db.py
"""
import sqlite3
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tables the dashboard actually reads (with approximate sizes)
TABLES_TO_EXPORT = [
    "filings",              # ~1249 rows
    "pool_performance",     # ~615 rows
    "monthly_summary",      # ~1000 rows
    "loan_loss_summary",    # ~50K rows
    "loans",                # ~250K rows (for Loan Explorer only)
    "notes",                # ~130 rows (static tranche attributes)
]


def main():
    if not os.path.exists(DB_PATH):
        logger.error(f"Source database not found: {DB_PATH}")
        return

    logger.info(f"Exporting dashboard tables from {DB_PATH} to {DASHBOARD_DB}")

    # Remove old dashboard DB
    if os.path.exists(DASHBOARD_DB):
        os.remove(DASHBOARD_DB)

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(DASHBOARD_DB)

    src.execute("PRAGMA journal_mode=WAL")

    for table in TABLES_TO_EXPORT:
        try:
            # Get table schema
            schema_row = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not schema_row:
                logger.warning(f"Table {table} not found, skipping")
                continue

            # Create table in destination
            dst.execute(schema_row[0])

            # Copy data
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                placeholders = ",".join(["?"] * len(rows[0]))
                dst.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
                logger.info(f"  {table}: {len(rows):,} rows")
            else:
                logger.info(f"  {table}: 0 rows")
        except Exception as e:
            logger.error(f"  Error exporting {table}: {e}")

    # Copy indexes
    for row in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        try:
            dst.execute(row[0])
        except Exception:
            pass  # Index may reference table we didn't copy

    # Optimize the new DB
    dst.commit()
    dst.execute("VACUUM")
    dst.execute("PRAGMA journal_mode=WAL")
    dst.close()
    src.close()

    size_mb = os.path.getsize(DASHBOARD_DB) / (1024 * 1024)
    logger.info(f"Dashboard DB created: {DASHBOARD_DB} ({size_mb:.1f} MB)")
    logger.info("Done!")


if __name__ == "__main__":
    main()
