"""SEC EDGAR API client with rate limiting and retry logic."""

import time
import logging
import requests
from typing import Optional

from carvana_abs.config import HEADERS, REQUEST_DELAY

logger = logging.getLogger(__name__)

_last_request_time = 0.0


def _rate_limit():
    """Enforce rate limiting between SEC EDGAR requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def fetch_url(url: str, max_retries: int = 4, as_json: bool = False) -> Optional[requests.Response]:
    """Fetch a URL from SEC EDGAR with rate limiting and exponential backoff.

    Args:
        url: The URL to fetch.
        max_retries: Maximum number of retry attempts on failure.
        as_json: If True, return parsed JSON instead of Response object.

    Returns:
        Response object, or parsed JSON if as_json=True, or None on failure.
    """
    for attempt in range(max_retries + 1):
        _rate_limit()
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            if as_json:
                return resp.json()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)  # 2, 4, 8, 16 seconds
                logger.warning(f"Request failed ({e}), retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                logger.error(f"Request failed after {max_retries} retries: {url} - {e}")
                return None


def get_submissions(cik: str) -> Optional[dict]:
    """Fetch the submissions JSON for a given CIK from SEC EDGAR.

    Returns the full submissions data including recent filings and
    references to older filing batches.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    logger.info(f"Fetching submissions for CIK {cik}")
    return fetch_url(url, as_json=True)


def get_filing_index(accession_number: str, cik: str) -> Optional[dict]:
    """Fetch the filing index JSON for a specific filing.

    The index lists all documents/exhibits in the filing.
    """
    # Accession number format: 0001234567-21-012345 -> 0001234567/21/012345
    acc_no_dashes = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dashes}/{accession_number}-index.json"
    logger.info(f"Fetching filing index for {accession_number}")
    return fetch_url(url, as_json=True)


def get_filing_page(accession_number: str, cik: str) -> Optional[str]:
    """Fetch the filing index HTML page to discover exhibit URLs.

    Returns HTML content of the filing index page.
    """
    acc_no_dashes = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dashes}/{accession_number}-index.htm"
    logger.info(f"Fetching filing page for {accession_number}")
    resp = fetch_url(url)
    return resp.text if resp else None


def download_document(url: str) -> Optional[str]:
    """Download a document (HTML, XML, etc.) from SEC EDGAR.

    Returns the text content of the document.
    """
    logger.info(f"Downloading document: {url}")
    resp = fetch_url(url)
    return resp.text if resp else None


def download_document_bytes(url: str) -> Optional[bytes]:
    """Download a document as raw bytes from SEC EDGAR.

    Returns the raw bytes content of the document.
    """
    logger.info(f"Downloading document (bytes): {url}")
    resp = fetch_url(url)
    return resp.content if resp else None
