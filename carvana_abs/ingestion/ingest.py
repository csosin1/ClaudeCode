"""Orchestrate the full data ingestion pipeline for Carvana ABS deals."""

import logging
from typing import Optional

from carvana_abs.db.schema import init_db, get_connection
from carvana_abs.config import DB_PATH, DEFAULT_DEAL, get_active_deals
from carvana_abs.ingestion.filing_discovery import discover_all_filings, link_absee_to_10d
from carvana_abs.ingestion.edgar_client import download_document
from carvana_abs.ingestion.xml_parser import store_loan_data
from carvana_abs.ingestion.servicer_parser import store_pool_data

logger = logging.getLogger(__name__)


def run_deal_ingestion(deal: str, db_path: Optional[str] = None) -> dict:
    """Run the ingestion pipeline for a single deal.

    Returns a summary dict with counts.
    """
    db = db_path or DB_PATH
    summary = {
        "deal": deal,
        "filings_discovered": 0,
        "pool_records_ingested": 0,
        "loan_filings_ingested": 0,
        "total_loans": 0,
        "total_performance_records": 0,
        "errors": [],
    }

    # Step 1: Discover filings
    logger.info(f"[{deal}] Discovering filings from SEC EDGAR...")
    new_filings = discover_all_filings(deal, db)
    summary["filings_discovered"] = new_filings

    # Step 2: Link ABS-EE to 10-D
    logger.info(f"[{deal}] Linking ABS-EE filings to 10-D filings...")
    link_absee_to_10d(deal, db)

    conn = get_connection(db)
    cursor = conn.cursor()

    # Step 3: Ingest servicer certificates (pool-level data)
    logger.info(f"[{deal}] Ingesting servicer certificates (pool-level data)...")
    cursor.execute("""
        SELECT accession_number, servicer_cert_url
        FROM filings
        WHERE deal = ?
        AND filing_type IN ('10-D', '10-D/A')
        AND servicer_cert_url IS NOT NULL
        AND ingested_pool = 0
    """, (deal,))
    pending_pool = cursor.fetchall()
    logger.info(f"  {len(pending_pool)} servicer certificates to process")

    for filing in pending_pool:
        acc = filing["accession_number"]
        url = filing["servicer_cert_url"]
        try:
            html = download_document(url)
            if html:
                if store_pool_data(html, acc, deal, db):
                    summary["pool_records_ingested"] += 1
                else:
                    summary["errors"].append(f"Failed to parse pool data: {acc}")
            else:
                summary["errors"].append(f"Failed to download servicer cert: {acc}")
        except Exception as e:
            summary["errors"].append(f"Error processing pool data {acc}: {e}")
            logger.error(f"Error processing pool data {acc}: {e}")

    # Step 4: Ingest ABS-EE XML files (loan-level data)
    logger.info(f"[{deal}] Ingesting ABS-EE XML files (loan-level data)...")
    cursor.execute("""
        SELECT accession_number, absee_url
        FROM filings
        WHERE deal = ?
        AND absee_url IS NOT NULL
        AND ingested_loans = 0
    """, (deal,))
    pending_loans = cursor.fetchall()
    logger.info(f"  {len(pending_loans)} XML files to process")

    for filing in pending_loans:
        acc = filing["accession_number"]
        url = filing["absee_url"]
        try:
            xml = download_document(url)
            if xml:
                loans, perfs = store_loan_data(xml, acc, deal, db)
                summary["total_loans"] += loans
                summary["total_performance_records"] += perfs
                summary["loan_filings_ingested"] += 1
            else:
                summary["errors"].append(f"Failed to download XML: {acc}")
        except Exception as e:
            summary["errors"].append(f"Error processing loan data {acc}: {e}")
            logger.error(f"Error processing loan data {acc}: {e}")

    conn.close()
    return summary


def run_full_ingestion(deals: Optional[list[str]] = None,
                       db_path: Optional[str] = None) -> list[dict]:
    """Run the full ingestion pipeline for one or more deals.

    Args:
        deals: List of deal slugs to ingest. Defaults to all active deals.
        db_path: Optional override for database path.

    Returns a list of summary dicts (one per deal).
    """
    db = db_path or DB_PATH

    # Initialize database
    logger.info("Initializing database...")
    init_db(db)

    deal_list = deals or get_active_deals()
    summaries = []

    for deal in deal_list:
        logger.info(f"{'=' * 60}")
        logger.info(f"Processing deal: {deal}")
        logger.info(f"{'=' * 60}")
        summary = run_deal_ingestion(deal, db)
        summaries.append(summary)

        # Log per-deal summary
        logger.info(f"[{deal}] Summary:")
        logger.info(f"  Filings discovered: {summary['filings_discovered']}")
        logger.info(f"  Pool records ingested: {summary['pool_records_ingested']}")
        logger.info(f"  Loan filings ingested: {summary['loan_filings_ingested']}")
        logger.info(f"  Total new loan records: {summary['total_loans']}")
        logger.info(f"  Total performance records: {summary['total_performance_records']}")
        if summary["errors"]:
            logger.warning(f"  Errors: {len(summary['errors'])}")
            for err in summary["errors"][:5]:
                logger.warning(f"    - {err}")

    # Grand total
    logger.info(f"\n{'=' * 60}")
    logger.info("Grand Total Across All Deals:")
    logger.info(f"  Deals processed: {len(summaries)}")
    logger.info(f"  Total filings discovered: {sum(s['filings_discovered'] for s in summaries)}")
    logger.info(f"  Total pool records: {sum(s['pool_records_ingested'] for s in summaries)}")
    logger.info(f"  Total loan filings: {sum(s['loan_filings_ingested'] for s in summaries)}")
    total_errors = sum(len(s['errors']) for s in summaries)
    if total_errors:
        logger.warning(f"  Total errors: {total_errors}")
    logger.info(f"{'=' * 60}")

    return summaries
