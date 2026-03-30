"""Orchestrate the full data ingestion pipeline for Carvana 2020-P1."""

import logging
from typing import Optional

from carvana_abs.db.schema import init_db, get_connection
from carvana_abs.config import DB_PATH
from carvana_abs.ingestion.filing_discovery import discover_all_filings, link_absee_to_10d
from carvana_abs.ingestion.edgar_client import download_document
from carvana_abs.ingestion.xml_parser import store_loan_data
from carvana_abs.ingestion.servicer_parser import store_pool_data

logger = logging.getLogger(__name__)


def run_full_ingestion(db_path: Optional[str] = None) -> dict:
    """Run the full ingestion pipeline.

    Steps:
        1. Initialize database
        2. Discover all filings from SEC EDGAR
        3. Link ABS-EE filings to 10-D filings
        4. Download and parse servicer certificates (pool-level data)
        5. Download and parse ABS-EE XML files (loan-level data)

    Returns a summary dict with counts.
    """
    db = db_path or DB_PATH
    summary = {
        "filings_discovered": 0,
        "pool_records_ingested": 0,
        "loan_filings_ingested": 0,
        "total_loans": 0,
        "total_performance_records": 0,
        "errors": [],
    }

    # Step 1: Initialize database
    logger.info("Step 1: Initializing database...")
    init_db(db)

    # Step 2: Discover filings
    logger.info("Step 2: Discovering filings from SEC EDGAR...")
    new_filings = discover_all_filings(db)
    summary["filings_discovered"] = new_filings

    # Step 3: Link ABS-EE to 10-D
    logger.info("Step 3: Linking ABS-EE filings to 10-D filings...")
    link_absee_to_10d(db)

    conn = get_connection(db)
    cursor = conn.cursor()

    # Step 4: Ingest servicer certificates (pool-level data)
    logger.info("Step 4: Ingesting servicer certificates (pool-level data)...")
    cursor.execute("""
        SELECT accession_number, servicer_cert_url
        FROM filings
        WHERE filing_type IN ('10-D', '10-D/A')
        AND servicer_cert_url IS NOT NULL
        AND ingested_pool = 0
    """)
    pending_pool = cursor.fetchall()
    logger.info(f"  {len(pending_pool)} servicer certificates to process")

    for filing in pending_pool:
        acc = filing["accession_number"]
        url = filing["servicer_cert_url"]
        try:
            html = download_document(url)
            if html:
                if store_pool_data(html, acc, db):
                    summary["pool_records_ingested"] += 1
                else:
                    summary["errors"].append(f"Failed to parse pool data: {acc}")
            else:
                summary["errors"].append(f"Failed to download servicer cert: {acc}")
        except Exception as e:
            summary["errors"].append(f"Error processing pool data {acc}: {e}")
            logger.error(f"Error processing pool data {acc}: {e}")

    # Step 5: Ingest ABS-EE XML files (loan-level data)
    logger.info("Step 5: Ingesting ABS-EE XML files (loan-level data)...")
    cursor.execute("""
        SELECT accession_number, absee_url
        FROM filings
        WHERE absee_url IS NOT NULL
        AND ingested_loans = 0
    """)
    pending_loans = cursor.fetchall()
    logger.info(f"  {len(pending_loans)} XML files to process")

    for filing in pending_loans:
        acc = filing["accession_number"]
        url = filing["absee_url"]
        try:
            xml = download_document(url)
            if xml:
                loans, perfs = store_loan_data(xml, acc, db)
                summary["total_loans"] += loans
                summary["total_performance_records"] += perfs
                summary["loan_filings_ingested"] += 1
            else:
                summary["errors"].append(f"Failed to download XML: {acc}")
        except Exception as e:
            summary["errors"].append(f"Error processing loan data {acc}: {e}")
            logger.error(f"Error processing loan data {acc}: {e}")

    conn.close()

    # Final summary
    logger.info("=" * 60)
    logger.info("Ingestion Summary:")
    logger.info(f"  Filings discovered: {summary['filings_discovered']}")
    logger.info(f"  Pool records ingested: {summary['pool_records_ingested']}")
    logger.info(f"  Loan filings ingested: {summary['loan_filings_ingested']}")
    logger.info(f"  Total new loan records: {summary['total_loans']}")
    logger.info(f"  Total performance records: {summary['total_performance_records']}")
    if summary["errors"]:
        logger.warning(f"  Errors: {len(summary['errors'])}")
        for err in summary["errors"][:10]:
            logger.warning(f"    - {err}")
    logger.info("=" * 60)

    return summary
