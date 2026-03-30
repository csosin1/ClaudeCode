"""Discover all 10-D and ABS-EE filings for a Carvana deal from SEC EDGAR."""

import logging
import re
from typing import Optional

from carvana_abs.config import ARCHIVES_BASE, DEALS, DEFAULT_DEAL
from carvana_abs.ingestion.edgar_client import get_submissions, fetch_url
from carvana_abs.db.schema import get_connection

logger = logging.getLogger(__name__)


def _build_doc_url(cik: str, accession_number: str, filename: str) -> str:
    """Build a full SEC EDGAR URL for a document within a filing."""
    acc_no_dashes = accession_number.replace("-", "")
    cik_clean = cik.lstrip("0")
    return f"{ARCHIVES_BASE}/{cik_clean}/{acc_no_dashes}/{filename}"


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


def _discover_exhibit_urls(accession_number: str, cik: str) -> dict:
    """Fetch the filing index and extract exhibit URLs."""
    acc_no_dashes = accession_number.replace("-", "")
    cik_clean = cik.lstrip("0")
    index_url = f"{ARCHIVES_BASE}/{cik_clean}/{acc_no_dashes}/{accession_number}-index.json"

    index_data = fetch_url(index_url, as_json=True)
    if not index_data:
        return _discover_exhibit_urls_html(accession_number, cik)

    result = {"absee_url": None, "servicer_cert_url": None}

    directory = index_data.get("directory", {})
    items = directory.get("item", [])

    for item in items:
        name = item.get("name", "").lower()
        if "ex-102" in name or "ex102" in name or (name.endswith(".xml") and "absee" in name):
            result["absee_url"] = _build_doc_url(cik, accession_number, item["name"])
        elif "ex-99" in name or "ex99" in name:
            result["servicer_cert_url"] = _build_doc_url(cik, accession_number, item["name"])

    return result


def _discover_exhibit_urls_html(accession_number: str, cik: str) -> dict:
    """Fallback: discover exhibit URLs by parsing the filing index HTML page."""
    from carvana_abs.ingestion.edgar_client import get_filing_page

    result = {"absee_url": None, "servicer_cert_url": None}
    html = get_filing_page(accession_number, cik)
    if not html:
        return result

    xml_pattern = re.compile(r'href="([^"]*\.xml)"', re.IGNORECASE)
    for match in xml_pattern.finditer(html):
        url = match.group(1)
        if "absee" in url.lower() or "ex-102" in url.lower() or "ex102" in url.lower():
            if not url.startswith("http"):
                url = f"https://www.sec.gov{url}"
            result["absee_url"] = url
            break

    ex99_pattern = re.compile(r'href="([^"]*(?:ex-?99|servicer)[^"]*\.htm[l]?)"', re.IGNORECASE)
    for match in ex99_pattern.finditer(html):
        url = match.group(1)
        if not url.startswith("http"):
            url = f"https://www.sec.gov{url}"
        result["servicer_cert_url"] = url
        break

    return result


def discover_all_filings(deal: str = DEFAULT_DEAL, db_path: Optional[str] = None) -> int:
    """Discover all 10-D and ABS-EE filings for a deal and store metadata.

    Returns the number of new filings discovered.
    """
    from carvana_abs.config import DB_PATH, get_deal_config

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
        if filing["filing_type"] in ("10-D", "10-D/A"):
            exhibit_urls = _discover_exhibit_urls(acc, cik)

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
    """Link ABS-EE filings to their corresponding 10-D filings."""
    from carvana_abs.config import DB_PATH, get_deal_config

    deal_cfg = get_deal_config(deal)
    cik = deal_cfg["cik"]

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT accession_number, filing_date
        FROM filings WHERE deal = ? AND filing_type IN ('ABS-EE', 'ABS-EE/A')
    """, (deal,))
    absee_filings = cursor.fetchall()

    for absee in absee_filings:
        exhibit_urls = _discover_exhibit_urls(absee["accession_number"], cik)
        xml_url = exhibit_urls.get("absee_url")
        if not xml_url:
            continue

        cursor.execute("""
            SELECT accession_number FROM filings
            WHERE deal = ? AND filing_type IN ('10-D', '10-D/A')
            AND filing_date = ?
            AND absee_url IS NULL
            ORDER BY filing_date
            LIMIT 1
        """, (deal, absee["filing_date"]))
        matching_10d = cursor.fetchone()

        if matching_10d:
            cursor.execute("""
                UPDATE filings SET absee_url = ?
                WHERE accession_number = ?
            """, (xml_url, matching_10d["accession_number"]))
            logger.info(f"Linked ABS-EE XML to 10-D: {matching_10d['accession_number']}")

    conn.commit()
    conn.close()
