#!/usr/bin/env python3
"""Re-ingest all servicer certificates (pool-level data) without re-downloading XMLs.

Use this after fixing the servicer parser to repopulate pool_performance
with the newly-extracted fields (note balances, WAC, etc.).

    python -m carvana_abs.reingest_pool
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.db.schema import get_connection
from carvana_abs.config import DB_PATH, get_active_deals
from carvana_abs.ingestion.edgar_client import download_document
from carvana_abs.ingestion.servicer_parser import store_pool_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()

    for deal in get_active_deals():
        # Reset pool ingestion flags so we re-parse
        cursor.execute("""
            UPDATE filings SET ingested_pool = 0
            WHERE deal = ? AND servicer_cert_url IS NOT NULL
        """, (deal,))

    # Clear existing pool data
    cursor.execute("DELETE FROM pool_performance")
    conn.commit()
    conn.close()

    logger.info("Cleared pool_performance. Re-ingesting servicer certificates...")

    for deal in get_active_deals():
        conn = get_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT accession_number, servicer_cert_url
            FROM filings
            WHERE deal = ? AND servicer_cert_url IS NOT NULL AND ingested_pool = 0
        """, (deal,))
        pending = cursor.fetchall()
        conn.close()

        if not pending:
            logger.info(f"[{deal}] No servicer certs to process")
            continue

        logger.info(f"[{deal}] Re-ingesting {len(pending)} servicer certificates...")
        count = 0
        for filing in pending:
            html = download_document(filing["servicer_cert_url"])
            if html and store_pool_data(html, filing["accession_number"], deal, DB_PATH):
                count += 1
        logger.info(f"[{deal}] Stored {count}/{len(pending)} pool records")

    logger.info("Done! Rebuild summaries if needed: python carvana_abs/rebuild_summaries.py")


if __name__ == "__main__":
    main()
