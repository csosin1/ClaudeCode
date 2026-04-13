"""SEC EDGAR API client with rate limiting and retry logic."""

import os
import time
import logging
import requests
from typing import Optional

from carmax_abs.config import HEADERS, REQUEST_DELAY

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
        except requests.exceptions.HTTPError as e:
            # Don't retry 404s — the URL is wrong, retrying won't help
            if resp.status_code == 404:
                logger.debug(f"404 Not Found: {url}")
                return None
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Request failed ({e}), retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                logger.error(f"Request failed after {max_retries} retries: {url} - {e}")
                return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
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
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dashes}/index.json"
    logger.info(f"Fetching filing index for {accession_number}")
    return fetch_url(url, as_json=True)


def get_filing_page(accession_number: str, cik: str) -> Optional[str]:
    """Fetch the filing index HTML page to discover exhibit URLs.

    Returns HTML content of the filing index page.
    """
    acc_no_dashes = accession_number.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dashes}/index.htm"
    logger.info(f"Fetching filing page for {accession_number}")
    resp = fetch_url(url)
    return resp.text if resp else None


CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "filing_cache")


def _cache_path(url: str) -> str:
    """Get local cache path for a URL."""
    # Use the URL path as the filename, replacing slashes
    from urllib.parse import urlparse
    parsed = urlparse(url)
    safe_name = parsed.path.strip("/").replace("/", "_")
    return os.path.join(CACHE_DIR, safe_name)


def download_document(url: str) -> Optional[str]:
    """Download a document (HTML, XML, etc.) from SEC EDGAR.

    Caches locally so we don't re-download on reingest.
    Returns the text content of the document.
    """
    # Check cache first
    cache = _cache_path(url)
    if os.path.exists(cache):
        logger.debug(f"Cache hit: {cache}")
        with open(cache, "r", errors="replace") as f:
            return f.read()

    logger.info(f"Downloading document: {url}")
    resp = fetch_url(url)
    if resp:
        # Save to cache
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache, "w", errors="replace") as f:
            f.write(resp.text)
        logger.debug(f"Cached: {cache}")
        return resp.text
    return None


def download_document_bytes(url: str) -> Optional[bytes]:
    """Download a document as raw bytes from SEC EDGAR.

    Caches locally so we don't re-download on reingest.
    Returns the raw bytes content of the document.
    """
    cache = _cache_path(url) + ".bin"
    if os.path.exists(cache):
        logger.debug(f"Cache hit: {cache}")
        with open(cache, "rb") as f:
            return f.read()

    logger.info(f"Downloading document (bytes): {url}")
    resp = fetch_url(url)
    if resp:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache, "wb") as f:
            f.write(resp.content)
        return resp.content
    return None
