#!/usr/bin/env python3
"""Export dashboard-only tables from the full CarMax DB to a small fast one.

Mirrors carvana_abs/export_dashboard_db.py. The main carmax_abs.db contains the
full loan_performance table once loan-level ingestion completes (tens of millions
of rows); the dashboard never reads loan_performance directly — it uses the
pre-aggregated pool_performance / monthly_summary / loan_loss_summary tables.
This script copies just those tables into a lean dashboard.db.

Loans / monthly_summary / loan_loss_summary may be empty on CarMax (loan-level
ingestion is lagging pool-level ingestion). Missing or empty tables are copied
anyway so the dashboard can distinguish "table doesn't exist" from "table exists
but no rows yet."

Usage: python carmax_abs/export_dashboard_db.py
"""
import sqlite3
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carmax_abs.config import DB_PATH

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Same table set as Carvana. model_results may not exist yet on CarMax — that's
# fine, we just skip it.
TABLES_TO_EXPORT = [
    "filings",
    "pool_performance",
    "monthly_summary",
    "loan_loss_summary",
    "loans",
    "notes",
    "model_results",
]


def main():
    if not os.path.exists(DB_PATH):
        logger.error(f"Source database not found: {DB_PATH}")
        return

    logger.info(f"Exporting dashboard tables from {DB_PATH} to {DASHBOARD_DB}")

    if os.path.exists(DASHBOARD_DB):
        os.remove(DASHBOARD_DB)

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(DASHBOARD_DB)

    src.execute("PRAGMA journal_mode=WAL")

    for table in TABLES_TO_EXPORT:
        try:
            schema_row = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not schema_row:
                logger.warning(f"Table {table} not found, skipping")
                continue

            dst.execute(schema_row[0])

            # Chunked cursor iteration — avoids materializing the whole
            # loan_performance/loans table in a Python list.
            cur = src.execute(f"SELECT * FROM {table}")
            first = cur.fetchmany(1)
            if not first:
                logger.info(f"  {table}: 0 rows (empty — table created for forward-compatibility)")
                continue
            placeholders = ",".join(["?"] * len(first[0]))
            insert_sql = f"INSERT INTO {table} VALUES ({placeholders})"
            dst.executemany(insert_sql, first)
            total = 1
            while True:
                chunk = cur.fetchmany(10000)
                if not chunk:
                    break
                dst.executemany(insert_sql, chunk)
                total += len(chunk)
            logger.info(f"  {table}: {total:,} rows")
        except Exception as e:
            logger.error(f"  Error exporting {table}: {e}")

    for row in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        try:
            dst.execute(row[0])
        except Exception:
            pass

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
