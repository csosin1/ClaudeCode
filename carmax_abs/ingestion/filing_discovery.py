"""Discover all 10-D and ABS-EE filings for a Carvana deal from SEC EDGAR."""

import logging
import re
from typing import Optional

from carmax_abs.config import ARCHIVES_BASE, DEALS, DEFAULT_DEAL
from carmax_abs.ingestion.edgar_client import get_submissions, fetch_url
from carmax_abs.db.schema import get_connection

logger = logging.getLogger(__name__)


def _build_doc_url(cik: str, accession_number: str, filename: str) -> str:
    """Build a full SEC EDGAR URL for a document within a filing."""
    acc_no_dashes = accession_number.replace("-", "")
    cik_clean = cik.lstrip("0")
    return f"{ARCHIVES_BASE}/{cik_clean}/{acc_no_dashes}/{filename}"


def _get_index_json(cik: str, accession_number: str) -> Optional[list]:
    """Fetch the filing index.json and return the list of files.

    SEC EDGAR index format: /Archives/edgar/data/{cik}/{acc_nodashes}/index.json
    """
    acc_no_dashes = accession_number.replace("-", "")
    cik_clean = cik.lstrip("0")
    url = f"{ARCHIVES_BASE}/{cik_clean}/{acc_no_dashes}/index.json"
    data = fetch_url(url, max_retries=1, as_json=True)
    if data:
        return data.get("directory", {}).get("item", [])
    return None


def _extract_filings_from_submissions(submissions: dict) -> list[dict]:
    """Extract all 10-D and ABS-EE filings from the submissions JSON."""
    filings = []
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return filings

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    for i in range(len(forms)):
        form_type = forms[i]
        if form_type in ("10-D", "10-D/A", "ABS-EE", "ABS-EE/A"):
            filings.append({
                "accession_number": accessions[i],
                "filing_type": form_type,
                "filing_date": dates[i],
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            })

    # Handle older filings in separate JSON files
    older_files = submissions.get("filings", {}).get("files", [])
    for file_info in older_files:
        filename = file_info.get("name", "")
        if filename:
            url = f"https://data.sec.gov/submissions/{filename}"
            older_data = fetch_url(url, as_json=True)
            if older_data:
                o_forms = older_data.get("form", [])
                o_accessions = older_data.get("accessionNumber", [])
                o_dates = older_data.get("filingDate", [])
                o_primary = older_data.get("primaryDocument", [])
                for i in range(len(o_forms)):
                    if o_forms[i] in ("10-D", "10-D/A", "ABS-EE", "ABS-EE/A"):
                        filings.append({
                            "accession_number": o_accessions[i],
                            "filing_type": o_forms[i],
                            "filing_date": o_dates[i],
                            "primary_document": o_primary[i] if i < len(o_primary) else None,
                        })

    logger.info(f"Found {len(filings)} relevant filings (10-D + ABS-EE)")
    return filings


def _find_exhibits_in_index(items: list, cik: str, accession_number: str) -> dict:
    """Given a list of files from index.json, identify exhibit URLs."""
    result = {"absee_url": None, "servicer_cert_url": None}

    for item in items:
        name = item.get("name", "")
        name_lower = name.lower()

        # XML files are the EX-102 asset data
        if name_lower.endswith(".xml") and ("ex102" in name_lower or "ex-102" in name_lower):
            result["absee_url"] = _build_doc_url(cik, accession_number, name)

        # Servicer report HTM files
        elif "servicer" in name_lower and name_lower.endswith(".htm"):
            result["servicer_cert_url"] = _build_doc_url(cik, accession_number, name)

        # EX-99.1 pattern
        elif ("ex-99" in name_lower or "ex99" in name_lower) and name_lower.endswith(".htm"):
            result["servicer_cert_url"] = _build_doc_url(cik, accession_number, name)

        # Match dXXXXXdex991.htm pattern (Donnelley filings)
        elif name_lower.endswith("ex991.htm") or "dex991" in name_lower:
            result["servicer_cert_url"] = _build_doc_url(cik, accession_number, name)

    return result


def discover_all_filings(deal: str = DEFAULT_DEAL, db_path: Optional[str] = None) -> int:
    """Discover all 10-D and ABS-EE filings for a deal and store metadata."""
    from carmax_abs.config import DB_PATH, get_deal_config

    deal_cfg = get_deal_config(deal)
    cik = deal_cfg["cik"]

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT accession_number FROM filings WHERE deal = ?", (deal,))
    existing = {row["accession_number"] for row in cursor.fetchall()}

    submissions = get_submissions(cik)
    if not submissions:
        logger.error(f"Failed to fetch submissions for {deal} (CIK {cik})")
        return 0

    all_filings = _extract_filings_from_submissions(submissions)

    new_count = 0
    for filing in all_filings:
        acc = filing["accession_number"]
        if acc in existing:
            continue

        exhibit_urls = {"absee_url": None, "servicer_cert_url": None}

        # For 10-D filings, look up the index to find servicer cert
        if filing["filing_type"] in ("10-D", "10-D/A"):
            items = _get_index_json(cik, acc)
            if items:
                exhibit_urls = _find_exhibits_in_index(items, cik, acc)

        filing_url = _build_doc_url(
            cik, acc,
            filing.get("primary_document", f"{acc}.txt")
        )

        cursor.execute("""
            INSERT OR IGNORE INTO filings
            (accession_number, deal, filing_type, filing_date, filing_url,
             absee_url, servicer_cert_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            acc, deal,
            filing["filing_type"],
            filing["filing_date"],
            filing_url,
            exhibit_urls["absee_url"],
            exhibit_urls["servicer_cert_url"],
        ))
        new_count += 1

    conn.commit()
    conn.close()
    logger.info(f"Discovered {new_count} new filings for {deal}")
    return new_count


def link_absee_to_10d(deal: str = DEFAULT_DEAL, db_path: Optional[str] = None) -> None:
    """Link ABS-EE filings (with EX-102 XML) to their corresponding 10-D filings.

    ABS-EE filings contain the XML loan data. They're filed by a different entity
    (filing agent) but correspond to the same reporting period as a 10-D.
    We look up the ABS-EE filing's index.json using the trust's CIK to find the XML.
    """
    from carmax_abs.config import DB_PATH, get_deal_config

    deal_cfg = get_deal_config(deal)
    cik = deal_cfg["cik"]

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    # Find ABS-EE filings that haven't been linked yet
    cursor.execute("""
        SELECT accession_number, filing_date
        FROM filings WHERE deal = ? AND filing_type IN ('ABS-EE', 'ABS-EE/A')
    """, (deal,))
    absee_filings = cursor.fetchall()

    for absee in absee_filings:
        acc = absee["accession_number"]

        # Look up the ABS-EE filing's index to find the XML file
        items = _get_index_json(cik, acc)
        xml_url = None
        if items:
            # Find the main loan-tape XML. Carvana names it with "ex102" /
            # "ex-102"; CarMax names it "cart<deal>.xml" (e.g. cart20201.xml).
            # The loan-tape is always the largest .xml in the ABS-EE filing —
            # other .xmls in the filing are tiny exhibit schedules. Fall back
            # to "pick the biggest .xml that isn't an exhibit-103" if the
            # ex-102 pattern misses.
            best = None; best_size = 0
            for item in items:
                name = item.get("name", "").lower()
                if not name.endswith(".xml"): continue
                if "ex102" in name or "ex-102" in name:
                    xml_url = _build_doc_url(cik, acc, item["name"])
                    break
                if "103" in name or "ex103" in name:
                    continue  # skip small exhibit-103 asset-rep schedules
                try:
                    size = int(item.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                if size > best_size:
                    best_size = size
                    best = item["name"]
            if xml_url is None and best is not None:
                xml_url = _build_doc_url(cik, acc, best)

        if not xml_url:
            logger.debug(f"No XML found in ABS-EE {acc}")
            continue

        # Find matching 10-D by filing date. The ABS-EE and 10-D for a given
        # reporting period are typically filed on the same day, but a ~1-day
        # offset shows up often enough that exact-match drops real pairings.
        # Prefer same-day; fall back to ±3 days; take the closest.
        cursor.execute("""
            SELECT accession_number, filing_date FROM filings
            WHERE deal = ? AND filing_type IN ('10-D', '10-D/A')
            AND (absee_url IS NULL OR absee_url = '')
            AND ABS(julianday(filing_date) - julianday(?)) <= 3
            ORDER BY ABS(julianday(filing_date) - julianday(?))
            LIMIT 1
        """, (deal, absee["filing_date"], absee["filing_date"]))
        matching_10d = cursor.fetchone()

        if matching_10d:
            cursor.execute("""
                UPDATE filings SET absee_url = ?
                WHERE accession_number = ?
            """, (xml_url, matching_10d["accession_number"]))
            logger.info(f"Linked ABS-EE XML to 10-D: {matching_10d['accession_number']}")

    conn.commit()
    conn.close()
