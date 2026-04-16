"""Parse 424B prospectus supplements from SEC EDGAR to extract at-issuance deal terms.

Supports both Carvana (CRVNA) and CarMax (CARMX) auto ABS deals.
Uses edgar_client.py for all EDGAR fetches (rate limiting, caching, gzip).
"""

import json
import logging
import os
import re
import sqlite3
import sys
import time
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from carvana_abs.ingestion.edgar_client import fetch_url, download_document

logger = logging.getLogger(__name__)

# Set SEC user agent
os.environ.setdefault(
    "SEC_USER_AGENT",
    "Clifford Sosin clifford.sosin@casinvestmentpartners.com",
)

# ──────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────

DEAL_TERMS_DDL = """
CREATE TABLE IF NOT EXISTS deal_terms (
    deal TEXT PRIMARY KEY,
    filing_url TEXT,
    initial_pool_balance REAL,
    class_a1_pct REAL, class_a1_coupon REAL,
    class_a2_pct REAL, class_a2_coupon REAL,
    class_a3_pct REAL, class_a3_coupon REAL,
    class_a4_pct REAL, class_a4_coupon REAL,
    class_b_pct REAL, class_b_coupon REAL,
    class_c_pct REAL, class_c_coupon REAL,
    class_d_pct REAL, class_d_coupon REAL,
    class_n_pct REAL, class_n_coupon REAL,
    weighted_avg_coupon REAL,
    initial_oc_pct REAL,
    cnl_trigger_schedule TEXT,
    dq_trigger_pct REAL,
    dq_trigger_schedule TEXT,
    initial_reserve_pct REAL,
    reserve_floor_pct REAL,
    oc_target_pct REAL,
    oc_floor_pct REAL,
    servicing_fee_annual_pct REAL,
    cutoff_date TEXT,
    closing_date TEXT,
    terms_extracted INTEGER DEFAULT 1
);
"""


def _ensure_table(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute(DEAL_TERMS_DDL)
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────
# 424B Discovery via EFTS
# ──────────────────────────────────────────────────────────────────────

def _search_efts(query: str, forms: str = "424B2,424B5",
                 start_date: str = None, end_date: str = None) -> list[dict]:
    """Search SEC EDGAR full-text search for 424B filings."""
    import urllib.parse
    params = {
        "q": f'"{query}"',
        "forms": forms,
    }
    if start_date and end_date:
        params["dateRange"] = "custom"
        params["startdt"] = start_date
        params["enddt"] = end_date

    url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)
    data = fetch_url(url, as_json=True)
    if not data:
        return []

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        # Extract document filename from _id: "accession:filename"
        doc_id = hit["_id"]
        parts = doc_id.split(":")
        accession = parts[0] if len(parts) >= 2 else src.get("adsh", "")
        filename = parts[1] if len(parts) >= 2 else ""
        results.append({
            "accession": accession,
            "filename": filename,
            "form": src.get("form", ""),
            "file_date": src.get("file_date", ""),
            "ciks": src.get("ciks", []),
            "display_names": src.get("display_names", []),
        })
    return results


def _build_doc_url(accession: str, filename: str, cik: str) -> str:
    """Build full SEC EDGAR URL from accession + filename."""
    acc_nodashes = accession.replace("-", "")
    cik_clean = cik.lstrip("0")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{acc_nodashes}/{filename}"


def find_424b_url(deal_slug: str, issuer: str, cik: str) -> Optional[str]:
    """Find the 424B filing URL for a deal.

    Strategy:
    1. EFTS full-text search for the deal name
    2. If not found, search the CIK's submission history for 424B forms
    """
    # Build search query using entity name from config for precision
    if issuer == "carvana":
        query = f"Carvana Auto Receivables Trust {deal_slug}"
        entity_prefix = "Carvana"
    else:
        query = f"CarMax Auto Owner Trust {deal_slug}"
        entity_prefix = "CarMax"

    # Derive year for date range
    year = deal_slug[:4]
    start = f"{year}-01-01"
    end = f"{int(year)+1}-06-30"

    results = _search_efts(query, start_date=start, end_date=end)

    # Collect all matching results, pick the latest by file_date
    # Strict matching: the trust's CIK must appear in the filing's CIK list
    candidates = []
    for r in results:
        if cik in r["ciks"]:
            url = _build_doc_url(r["accession"], r["filename"], cik)
            candidates.append((r.get("file_date", ""), url))
        else:
            # Accept display name match only if deal slug is in the name
            for name in r.get("display_names", []):
                if deal_slug in name:
                    use_cik = r["ciks"][0] if r["ciks"] else cik
                    url = _build_doc_url(r["accession"], r["filename"], use_cik)
                    candidates.append((r.get("file_date", ""), url))
                    break

    if candidates:
        # Pick the latest filing date (final prospectus, not preliminary)
        candidates.sort(key=lambda x: x[0], reverse=True)
        url = candidates[0][1]
        logger.info(f"Found 424B for {deal_slug}: {url} (date: {candidates[0][0]})")
        return url

    # Fallback: search CIK's submissions for 424B forms
    logger.info(f"EFTS miss for {deal_slug}, trying submissions API for CIK {cik}")
    url = _find_424b_via_submissions(cik, deal_slug)
    if url and _verify_424b_deal(url, deal_slug):
        return url

    # Try depositor CIK for Carvana (all deals filed under depositor CIK 0001770373)
    if issuer == "carvana":
        depositor_cik = "0001770373"
        url = _find_424b_via_submissions(depositor_cik, deal_slug)
        if url and _verify_424b_deal(url, deal_slug):
            return url

    # Try broader EFTS search without date restriction
    results = _search_efts(query)
    for r in results:
        if cik in r["ciks"]:
            url = _build_doc_url(r["accession"], r["filename"], cik)
            return url
        for name in r.get("display_names", []):
            if deal_slug in name:
                use_cik = r["ciks"][0] if r["ciks"] else cik
                url = _build_doc_url(r["accession"], r["filename"], use_cik)
                return url

    logger.warning(f"Could not find 424B for {deal_slug}")
    return None


def _verify_424b_deal(url: str, deal_slug: str) -> bool:
    """Quick verification that a 424B URL actually belongs to the expected deal.
    Downloads the first ~10K of the document and checks for deal identifiers."""
    html = download_document(url)
    if not html:
        return False
    # Check just the first portion for the deal slug
    header = html[:20000].upper()
    if deal_slug.upper() in header:
        return True
    # Also check for Trust name variant
    if deal_slug.replace("-", " ").upper() in header:
        return True
    logger.warning(f"424B at {url} doesn't mention {deal_slug} in header - rejecting")
    return False


def _find_424b_via_submissions(cik: str, deal_slug: str) -> Optional[str]:
    """Search a CIK's submission history for 424B filings matching a deal.

    Returns the *latest* 424B filing (by filing date) to avoid preliminary
    prospectuses that have blank interest rates.
    """
    from carvana_abs.ingestion.edgar_client import get_submissions

    subs = get_submissions(cik)
    if not subs:
        return None

    candidates = []

    def _collect(forms, accessions, dates, primary_docs):
        for i, form in enumerate(forms):
            if form in ("424B2", "424B5", "424B1"):
                acc = accessions[i]
                doc = primary_docs[i] if i < len(primary_docs) else ""
                date = dates[i] if i < len(dates) else ""
                url = _build_doc_url(acc, doc, cik)
                candidates.append((date, url))

    recent = subs.get("filings", {}).get("recent", {})
    _collect(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
        recent.get("primaryDocument", []),
    )

    # Check older filing batches
    older_files = subs.get("filings", {}).get("files", [])
    for file_info in older_files:
        filename = file_info.get("name", "")
        if filename:
            batch_url = f"https://data.sec.gov/submissions/{filename}"
            batch = fetch_url(batch_url, as_json=True)
            if batch:
                _collect(
                    batch.get("form", []),
                    batch.get("accessionNumber", []),
                    batch.get("filingDate", []),
                    batch.get("primaryDocument", []),
                )

    if not candidates:
        return None

    # Return the latest filing (highest date = final prospectus, not preliminary)
    candidates.sort(key=lambda x: x[0], reverse=True)
    url = candidates[0][1]
    logger.info(f"Found 424B via submissions for CIK {cik}: {url} (date: {candidates[0][0]})")
    return url


# ──────────────────────────────────────────────────────────────────────
# HTML → clean text
# ──────────────────────────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace for text extraction."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    # Decode numeric HTML entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _parse_dollar(s: str) -> Optional[float]:
    """Parse a dollar amount string like '$1,039,515,050.84' → float.

    Also handles SEC EDGAR formatting quirk where the decimal point before
    cents is rendered as a comma: '$400,000,003,21' → 400000003.21.
    """
    s = s.replace('$', '').replace(' ', '').strip()
    # If the last comma-separated group is exactly 2 digits, treat as cents
    # e.g. '400,000,003,21' → '400,000,003.21'
    m = re.match(r'^([\d,]+),(\d{2})$', s)
    if m:
        s = m.group(1) + '.' + m.group(2)
    s = s.replace(',', '')
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_pct(s: str) -> Optional[float]:
    """Parse a percentage string like '2.57%' → 0.0257 (decimal form).
    Returns None if unparseable."""
    s = s.replace('%', '').replace(' ', '').strip()
    try:
        return float(s) / 100.0
    except (ValueError, TypeError):
        return None


def _parse_pct_raw(s: str) -> Optional[float]:
    """Parse percentage string, return raw number (e.g. '2.57%' → 2.57)."""
    s = s.replace('%', '').replace(' ', '').strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────
# Note structure extraction
# ──────────────────────────────────────────────────────────────────────

# Regex for note classes. Handles both formats:
# Carvana: "Class A-1 ... $146,000,000 ... 1.21833%"
# CarMax:  "A-1 $ 291,000,000 1.77613%"
# Also handles sub-classes like A-2a, A-2b
_NOTE_CLASS_MAP = {
    'A-1': 'a1', 'A1': 'a1',
    'A-2': 'a2', 'A2': 'a2', 'A-2a': 'a2', 'A-2A': 'a2', 'A-2b': 'a2', 'A-2B': 'a2',
    'A-3': 'a3', 'A3': 'a3',
    'A-4': 'a4', 'A4': 'a4',
    'A': 'a1',   # N-series deals use single "Class A" (maps to a1 slot)
    'B': 'b',
    'C': 'c',
    'D': 'd',
    'N': 'n',
}


def _extract_notes(text: str) -> dict:
    """Extract note classes, principal amounts, and coupon rates from prospectus text.

    Returns dict like:
        {'a1': {'balance': 146000000, 'coupon': 0.0121833}, ...}
    """
    notes = {}

    # Strategy 1: Cover-page format (Carvana):
    # "$146,000,000 Class A-1 1.21833% Asset Backed Notes"
    # CarMax: "Class A-1 Asset-backed Notes $ 291,000,000 1.77613%"
    cover_pattern = re.compile(
        r'\$\s*([\d,]+(?:\.\d+)?)\s+'
        r'(?:Class\s+)?(A-?[1-4](?:[aAbB])?|[ABCDN])\s+'
        r'([\d]+\.[\d]+)\s*%\s*'
        r'(?:Asset[- ]?[Bb]acked\s+)?[Nn]otes?'
    )
    for m in cover_pattern.finditer(text[:len(text) // 6]):
        balance = _parse_dollar(m.group(1))
        class_raw = m.group(2).strip()
        coupon = float(m.group(3)) / 100.0
        class_key = _NOTE_CLASS_MAP.get(class_raw)
        if class_key and balance:
            _merge_note(notes, class_key, balance, coupon)

    # Also: floating rate on cover: "$249,200,000 Class A-2b SOFR Rate + 0.47%"
    cover_float = re.compile(
        r'\$\s*([\d,]+(?:\.\d+)?)\s+'
        r'(?:Class\s+)?(A-?[1-4](?:[aAbB])?|[ABCDN])\s+'
        r'(?:SOFR|LIBOR|Prime)\s*(?:Rate\s*)?\+\s*([\d]+\.[\d]+)\s*%'
    )
    for m in cover_float.finditer(text[:len(text) // 6]):
        balance = _parse_dollar(m.group(1))
        class_raw = m.group(2).strip()
        spread = float(m.group(3)) / 100.0
        class_key = _NOTE_CLASS_MAP.get(class_raw)
        if class_key and balance:
            _merge_note(notes, class_key, balance, spread)

    # Strategy 1b: CarMax cover format:
    # "Class A-1 Asset-backed Notes $ 291,000,000 1.77613% January 15, 2021"
    # Also handles floating rate: "Class A-2b ... $ 249,200,000 SOFR Rate + 0.47%"
    if len(notes) < 3:
        # Fixed rate notes
        carmax_cover = re.compile(
            r'(?:Class\s+)?(A-?[1-4](?:[aAbB])?|[BCDN])\s+'
            r'(?:Asset[- ]?[Bb]acked\s+)?[Nn]otes?\s+'
            r'\$\s*([\d,]+(?:\.\d+)?)\s+'
            r'([\d]+\.[\d]+)\s*%'
        )
        for m in carmax_cover.finditer(text[:len(text) // 6]):
            class_raw = m.group(1).strip()
            class_key = _NOTE_CLASS_MAP.get(class_raw)
            if not class_key:
                continue
            balance = _parse_dollar(m.group(2))
            coupon = float(m.group(3)) / 100.0
            if balance and coupon < 0.15:  # sanity
                _merge_note(notes, class_key, balance, coupon)

        # Floating rate notes: "Class A-2b ... $ 249,200,000 SOFR Rate + 0.47%"
        float_pattern = re.compile(
            r'(?:Class\s+)?(A-?[1-4](?:[aAbB])?|[BCDN])\s+'
            r'(?:Asset[- ]?[Bb]acked\s+)?[Nn]otes?\s+'
            r'\$\s*([\d,]+(?:\.\d+)?)\s+'
            r'(?:SOFR|LIBOR|Prime)\s*(?:Rate\s*)?\+\s*([\d]+\.[\d]+)\s*%'
        )
        for m in float_pattern.finditer(text[:len(text) // 6]):
            class_raw = m.group(1).strip()
            class_key = _NOTE_CLASS_MAP.get(class_raw)
            if not class_key:
                continue
            balance = _parse_dollar(m.group(2))
            spread = float(m.group(3)) / 100.0
            if balance:
                # Use spread as coupon proxy for floating rate notes
                _merge_note(notes, class_key, balance, spread)

    # Strategy 2: Simple format:
    # "A-1 $ 291,000,000 1.77613%"
    if len(notes) < 3:
        simple_pattern = re.compile(
            r'(A-?[1-4](?:[aAbB])?|[BCDN])\s+'
            r'\$\s*([\d,]+(?:\.\d+)?)\s+'
            r'([\d]+\.[\d]+)\s*%'
        )
        for m in simple_pattern.finditer(text[:len(text) // 6]):
            class_raw = m.group(1).strip()
            class_key = _NOTE_CLASS_MAP.get(class_raw)
            if not class_key:
                continue
            balance = _parse_dollar(m.group(2))
            coupon = float(m.group(3)) / 100.0
            if balance and coupon < 0.15:
                _merge_note(notes, class_key, balance, coupon)

    # Strategy 3: Structured table with "Principal Amount" row + "Interest Rate" row
    if len(notes) < 3:
        _extract_notes_from_table_block(text[:len(text) // 4], notes)

    # Strategy 4: "Class X Asset Backed Notes $ amount" near "Interest Rate ... X%"
    if len(notes) < 3:
        _extract_notes_from_listing(text[:len(text) // 4], notes)

    return notes


def _merge_note(notes: dict, class_key: str, balance: float, coupon: float):
    """Add a note to the dict, merging sub-classes (A-2a + A-2b)."""
    if class_key in notes:
        existing = notes[class_key]
        total_bal = existing['balance'] + balance
        existing['coupon'] = (
            existing['coupon'] * existing['balance'] +
            coupon * balance
        ) / total_bal
        existing['balance'] = total_bal
    else:
        notes[class_key] = {'balance': balance, 'coupon': coupon}


def _fill_balances_from_table(text: str, notes: dict):
    """Fill in missing balances from Principal Amount table for N-series deals.

    These deals have a table like:
        Class A Notes  Class B Notes  Class C Notes  Class D Notes
        Principal Amount  $185,400,000  $53,600,000  $58,200,000  $40,400,000
    """
    # Find "Principal Amount" row and extract dollar amounts
    pa_idx = text.find('Principal Amount')
    if pa_idx < 0:
        return

    # Get the chunk after "Principal Amount" up to next label
    chunk = text[pa_idx:pa_idx + 500]
    amounts = re.findall(r'\$\s*([\d,]+(?:\.\d+)?)', chunk)

    # Map amounts to note classes in order
    class_order = [k for k in ['a1', 'b', 'c', 'd', 'n'] if k in notes]
    for i, cls in enumerate(class_order):
        if i < len(amounts) and notes[cls]['balance'] == 0:
            bal = _parse_dollar(amounts[i])
            if bal:
                notes[cls]['balance'] = bal


def _extract_notes_from_table_block(text: str, notes: dict):
    """Parse note info from the structured table with Principal Amount + Interest Rate rows."""
    pa_idx = text.find('Principal Amount')
    if pa_idx < 0:
        return

    # Get amounts between Principal Amount and Interest Rate
    ir_idx = text.find('Interest Rate', pa_idx)
    if ir_idx < 0:
        return

    # Principal amounts are between the two headers
    amount_chunk = text[pa_idx:ir_idx]
    amounts = re.findall(r'\$\s*([\d,]+(?:\.\d+)?)', amount_chunk)

    # Interest rates follow the Interest Rate header
    ir_chunk = text[ir_idx:ir_idx + 1000]
    rates = re.findall(r'([\d]+\.[\d]+)\s*%', ir_chunk)

    classes = ['a1', 'a2', 'a3', 'a4', 'b', 'c', 'd']
    for i, cls in enumerate(classes):
        if i < len(amounts) and i < len(rates):
            balance = _parse_dollar(amounts[i])
            coupon = float(rates[i]) / 100.0
            if balance and cls not in notes:
                notes[cls] = {'balance': balance, 'coupon': coupon}


def _extract_notes_from_listing(text: str, notes: dict):
    """Parse from listing format: 'Class A-1 Asset Backed Notes $ 146,000,000.00'
    paired with nearby interest rates."""
    listing_pattern = re.compile(
        r'(?:Class\s+)?(A-?[1-4](?:[aAbB])?|[BCDN])\s+'
        r'(?:Asset[- ]?[Bb]acked\s+)?[Nn]otes?\s+'
        r'\$\s*([\d,]+(?:\.\d+)?)'
    )
    classes_found = []
    for m in listing_pattern.finditer(text):
        class_raw = m.group(1).strip()
        class_key = _NOTE_CLASS_MAP.get(class_raw)
        balance = _parse_dollar(m.group(2))
        if class_key and balance:
            classes_found.append((class_key, balance, m.start()))

    # Now find associated coupons - look for the Interest Rate section
    for cls_key, balance, pos in classes_found:
        # Search for rate near this class mention
        chunk = text[pos:pos + 500]
        rate_m = re.search(r'([\d]+\.[\d]+)\s*%', chunk)
        if rate_m:
            coupon = float(rate_m.group(1)) / 100.0
            if coupon < 0.15:  # sanity: coupon should be < 15%
                _merge_note(notes, cls_key, balance, coupon)


# ──────────────────────────────────────────────────────────────────────
# Deal term extraction
# ──────────────────────────────────────────────────────────────────────

def _extract_pool_balance(text: str) -> Optional[float]:
    """Extract initial pool balance."""
    # Carvana: "Initial Pool Balance $ 1,039,515,050.84"
    # Also: "Pool Balance $ 405,000,000.11" (without "Initial" prefix)
    # CarMax: "pool balance of $1,553,875,032.29 as of the cutoff date"
    patterns = [
        r'Initial Pool Balance\s*\$\s*([\d,]+(?:\.\d+)?)',
        r'[Pp]ool [Bb]alance\s+(?:of\s+)?\$\s*([\d,]+(?:\.\d+)?)\s*(?:as of|on)\s*(?:the\s+)?[Cc]utoff',
        r'[Aa]ggregate.*?[Pp]rincipal [Bb]alance.*?\$\s*([\d,]+(?:\.\d+)?)\s*(?:as of|on)\s*(?:the\s+)?[Cc]utoff',
        # "Pool Balance $ 405,000,000.11 Number of Receivables"
        r'Pool Balance\s*\$\s*([\d,]+(?:\.\d+)?)\s*(?:Number|Aggregate)',
    ]
    for pat in patterns:
        m = re.search(pat, text[:200000])
        if m:
            val = _parse_dollar(m.group(1))
            if val and val > 50_000_000:  # sanity: pool > $50M
                return val
    return None


def _extract_servicing_fee(text: str) -> Optional[float]:
    """Extract annual servicing fee as decimal (e.g. 0.0061 for 0.61%)."""
    # Carvana: "Servicing Fee equal to the product of (i) 0.61% times (ii) the Pool Balance"
    # CarMax: "servicing fee ... equal to the product of 1 / 12 of 1.00% and the pool balance"

    # Strategy: find "1/12 of X%" near "servicing" (most reliable)
    m = re.search(
        r'(?:servicing fee|Servicing Fee)[^.]{0,200}?'
        r'(?:product of\s+)?1\s*/\s*12\s+of\s+(\d+\.\d+)\s*%',
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = float(m.group(1))
        if 0.2 <= val <= 2.5:
            return val / 100.0

    # "Servicing Fee equal to ... X% times ... Pool Balance" (within 300 chars)
    m = re.search(
        r'(?:servicing fee|Servicing Fee)[^.]{0,200}?equal to[^.]{0,200}?'
        r'(\d+\.\d+)\s*%\s*(?:times|multiplied)',
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = float(m.group(1))
        if 0.2 <= val <= 2.5:
            return val / 100.0

    # "X% per annum" within same sentence as "servicing"
    m = re.search(
        r'(?:servicing fee|Servicing Fee)[^.]{0,200}?(\d+\.\d+)\s*%\s*per\s+annum',
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = float(m.group(1))
        if 0.2 <= val <= 2.5:
            return val / 100.0

    return None


def _extract_oc_target(text: str) -> Optional[float]:
    """Extract OC target as decimal (e.g. 0.017 for 1.70%)."""
    patterns = [
        r'[Oo]vercollateralization [Tt]arget.*?equal to\s+(\d+\.\d+)\s*%',
        r'[Oo]vercollateralization.*?target.*?(\d+\.\d+)\s*%\s*of\s*(?:the\s+)?[Pp]ool [Bb]alance',
        r'overcollateralization.*?target amount.*?(\d+\.\d+)\s*%',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            # Sanity: OC target should be < 20%
            val = float(m.group(1))
            if val < 20:
                return val / 100.0
    return None


def _extract_oc_floor(text: str) -> Optional[float]:
    """Extract OC floor as decimal."""
    patterns = [
        r'[Oo]vercollateralization [Ff]loor.*?(\d+\.\d+)\s*%',
        r'overcollateral.*?floor.*?equal to\s+(\d+\.\d+)\s*%',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = float(m.group(1))
            if val < 20:
                return val / 100.0
    return None


def _extract_reserve_pct(text: str) -> Optional[float]:
    """Extract initial reserve account as % of initial pool balance."""
    # "approximately 0.60% of the Initial Pool Balance"
    patterns = [
        r'(?:approximately|equals?|equal to)\s+(\d+\.\d+)\s*%\s*of\s*(?:the\s+)?Initial Pool Balance.*?[Rr]eserve',
        r'[Rr]eserve [Aa]ccount.*?(?:approximately|equals?)\s+(\d+\.\d+)\s*%\s*of\s*(?:the\s+)?Initial Pool Balance',
        r'(\d+\.\d+)\s*%\s*of\s*(?:the\s+)?Initial Pool Balance.*?[Rr]eserve',
    ]
    # Also look for reverse pattern: reserve ... X% of IPB
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = float(m.group(1))
            if val < 10:
                return val / 100.0

    # Broader: find "reserve" near "% of the Initial Pool Balance"
    for m in re.finditer(r'(\d+\.\d+)\s*%\s*of\s*(?:the\s+)?Initial Pool Balance', text, re.IGNORECASE):
        # Check if "reserve" appears within 500 chars before
        start = max(0, m.start() - 500)
        context = text[start:m.start()]
        if re.search(r'reserve', context, re.IGNORECASE):
            val = float(m.group(1))
            if val < 10:
                return val / 100.0
    return None


def _extract_reserve_floor(text: str) -> Optional[float]:
    """Extract reserve floor as decimal."""
    patterns = [
        r'[Ss]pecified [Rr]eserve.*?[Aa]mount.*?(\d+\.\d+)\s*%',
        r'[Rr]eserve.*?[Ff]loor.*?(\d+\.\d+)\s*%',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = float(m.group(1))
            if val < 10:
                return val / 100.0
    return None


def _extract_cutoff_date(text: str) -> Optional[str]:
    """Extract cutoff date as ISO string."""
    patterns = [
        r'[Cc]utoff [Dd]ate\s*,?\s*(?:which\s+)?(?:will be|is)\s+(?:the\s+)?(?:end of day on|on)\s+(\w+ \d{1,2},?\s*\d{4})',
        r'[Cc]utoff [Dd]ate.*?(?:will be|is).*?(?:on|end of day on)\s+(\w+ \d{1,2},?\s*\d{4})',
        r'[Cc]utoff [Dd]ate.*?(\w+ \d{1,2},?\s*\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text[:100000])
        if m:
            d = _normalize_date(m.group(1))
            if d and len(d) == 10 and d[0] == '2':
                return d
    return None


def _extract_closing_date(text: str) -> Optional[str]:
    """Extract closing date as ISO string."""
    patterns = [
        r'[Cc]losing [Dd]ate\s+(?:will be|is)\s+(?:on or about|on)\s+(\w+ \d{1,2},?\s*\d{4})',
        r'[Cc]losing [Dd]ate.*?(?:will be|is).*?(?:on or about|on)\s+(\w+ \d{1,2},?\s*\d{4})',
        r'[Cc]losing [Dd]ate.*?(\w+ \d{1,2},?\s*\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text[:100000])
        if m:
            d = _normalize_date(m.group(1))
            if d and len(d) == 10 and d[0] == '2':  # sanity: 20xx-xx-xx
                return d
    return None


def _normalize_date(date_str: str) -> Optional[str]:
    """Convert 'March 30, 2022' or 'March 30 2022' to '2022-03-30'."""
    from datetime import datetime
    date_str = date_str.strip().replace(',', '')
    for fmt in ('%B %d %Y', '%b %d %Y'):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return date_str


def _extract_dq_trigger(text: str) -> tuple[Optional[float], Optional[str]]:
    """Extract delinquency trigger rate(s).

    Returns (single_pct_or_None, schedule_json_or_None).

    Carvana uses a schedule:
        Collection Period  Delinquency Trigger Rates
        1-12               2.00%
        13-24              2.50%
        ...

    CarMax may use a similar schedule or a single threshold.
    """
    # Look for a DQ trigger schedule table
    schedule = []

    # Find the DQ trigger rates table
    m = re.search(
        r'Delinquency Trigger Rates?\s*(?:will be as follows|are as follows|:)',
        text, re.IGNORECASE
    )
    if not m:
        # Alternative: find near 'Collection Period' + 'Delinquency Trigger'
        m = re.search(r'Collection Period\s+Delinquency Trigger Rate', text, re.IGNORECASE)

    if m:
        chunk = text[m.start():m.start() + 1000]
        # Parse rows: "1-12 2.00%" or "1-12 2.00 %" or "49+ 4.50%"
        row_pattern = re.compile(r'(\d+)\s*[-–]\s*(\d+)\s+(\d+\.\d+)\s*%')
        plus_pattern = re.compile(r'(\d+)\s*\+\s+(\d+\.\d+)\s*%')

        for rm in row_pattern.finditer(chunk):
            start_month = int(rm.group(1))
            end_month = int(rm.group(2))
            threshold = float(rm.group(3))
            schedule.append({
                "month_start": start_month,
                "month_end": end_month,
                "threshold_pct": threshold
            })

        for rm in plus_pattern.finditer(chunk):
            start_month = int(rm.group(1))
            threshold = float(rm.group(2))
            schedule.append({
                "month_start": start_month,
                "month_end": 999,
                "threshold_pct": threshold
            })

    # Also look for a single DQ trigger percentage
    single_pct = None
    # "Delinquency Trigger means 6.62%" or "Delinquency Trigger is 6.62%"
    # Keep patterns tight (max 50 chars between "Trigger" and the pct) to avoid
    # matching coupon rates hundreds of characters away.
    dq_patterns = [
        r'[Dd]elinquency [Tt]rigger\s+(?:means|is|equals?)\s+(\d+\.\d+)\s*%',
        r'[Dd]elinquency [Tt]rigger.{0,50}(?:means|is|equals?|set at)\s+(\d+\.\d+)\s*%',
    ]
    for dpat in dq_patterns:
        m = re.search(dpat, text)
        if m:
            val = float(m.group(1))
            if 1.0 < val < 20:  # sanity: DQ trigger between 1% and 20%
                single_pct = val / 100.0
                break

    schedule_json = json.dumps(schedule) if schedule else None
    return single_pct, schedule_json


def _extract_cnl_trigger(text: str) -> Optional[str]:
    """Extract cumulative net loss trigger schedule.

    These appear as structured tables near explicit "Cumulative Net Loss Trigger"
    or "CNL Trigger" section headers. Only extract from clear trigger schedule
    tables, not from static pool data or performance history.

    Returns JSON array: [{"month": 12, "threshold_pct": 1.5}, ...] or
    [{"date": "January 2023", "threshold_pct": 0.65}, ...]
    """
    schedule = []

    # Look for explicit trigger schedule patterns:
    # "Cumulative Net Loss Trigger Rates will be as follows:"
    # "CNL Trigger Rate Schedule"
    # "Cumulative Net Loss Rate ... will be as follows"
    trigger_table_patterns = [
        r'[Cc]umulative [Nn]et [Ll]oss\s+(?:Trigger\s+)?Rate[s]?\s+(?:will be|are)\s+as follows',
        r'CNL\s+[Tt]rigger\s+(?:Rate\s+)?[Ss]chedule',
        r'[Cc]umulative [Nn]et [Ll]oss\s+[Tt]rigger.*?(?:will be|are)\s+as follows',
    ]

    start_pos = None
    for pat in trigger_table_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            start_pos = m.start()
            break

    if start_pos is None:
        # Also check for CarMax-style CNL trigger definition
        # "Cumulative Net Loss Trigger means X%"
        m = re.search(
            r'[Cc]umulative [Nn]et [Ll]oss [Tt]rigger\s+(?:means|is|equals?)\s+(\d+\.\d+)\s*%',
            text
        )
        if m:
            return json.dumps([{"threshold_pct": float(m.group(1))}])

        # CarMax alternative: "cumulative net loss rate ... of X%"
        # e.g. "cumulative net loss rate as a percentage of the Pool Balance as of the Cutoff Date of 1.25%"
        m = re.search(
            r'[Cc]umulative [Nn]et [Ll]oss [Rr]ate.{0,120}?(?:of|equals?|is)\s+(\d+\.\d+)\s*%',
            text
        )
        if m:
            val = float(m.group(1))
            if 0.1 < val < 30:  # sanity
                return json.dumps([{"threshold_pct": val}])

        return None

    # Parse the table (only in a small window after the header)
    chunk = text[start_pos:start_pos + 2000]

    # Pattern 1: Month ranges: "1-12 2.00%"
    month_pct = re.compile(r'(\d{1,3})\s*[-–]\s*(\d{1,3})\s+(\d+\.\d+)\s*%')
    for m in month_pct.finditer(chunk):
        schedule.append({
            "month_start": int(m.group(1)),
            "month_end": int(m.group(2)),
            "threshold_pct": float(m.group(3))
        })

    # Pattern 2: "49+ 4.50%"
    plus_pct = re.compile(r'(\d{1,3})\s*\+\s+(\d+\.\d+)\s*%')
    for m in plus_pct.finditer(chunk):
        schedule.append({
            "month_start": int(m.group(1)),
            "month_end": 999,
            "threshold_pct": float(m.group(2))
        })

    # Pattern 3: Date-based triggers "January 2023 0.65%"
    if not schedule:
        date_pct = re.compile(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+'
            r'(\d{4})\s+(\d+\.\d+)\s*%',
            re.IGNORECASE
        )
        for m in date_pct.finditer(chunk):
            pct = float(m.group(3))
            if 0 < pct < 50:
                schedule.append({
                    "date": f"{m.group(1)} {m.group(2)}",
                    "threshold_pct": pct
                })

    if schedule:
        return json.dumps(schedule)
    return None


# ──────────────────────────────────────────────────────────────────────
# Main parse function
# ──────────────────────────────────────────────────────────────────────

def parse_prospectus(html: str, deal_slug: str, filing_url: str) -> dict:
    """Parse a 424B prospectus HTML and return deal terms dict."""
    text = _clean_html(html)

    result = {
        'deal': deal_slug,
        'filing_url': filing_url,
        'terms_extracted': 1,
    }

    # Pool balance
    result['initial_pool_balance'] = _extract_pool_balance(text)

    # Note structure
    notes = _extract_notes(text)
    ipb = result['initial_pool_balance']

    total_note_balance = 0.0
    weighted_coupon_sum = 0.0

    for cls in ['a1', 'a2', 'a3', 'a4', 'b', 'c', 'd', 'n']:
        if cls in notes:
            note = notes[cls]
            bal = note['balance']
            cpn = note['coupon']
            pct = bal / ipb if ipb else None
            result[f'class_{cls}_pct'] = pct
            result[f'class_{cls}_coupon'] = cpn
            total_note_balance += bal
            weighted_coupon_sum += bal * cpn
        else:
            result[f'class_{cls}_pct'] = None
            result[f'class_{cls}_coupon'] = None

    # Weighted average coupon
    if total_note_balance > 0:
        result['weighted_avg_coupon'] = weighted_coupon_sum / total_note_balance
    else:
        result['weighted_avg_coupon'] = None

    # Initial OC
    if ipb and total_note_balance > 0:
        result['initial_oc_pct'] = (ipb - total_note_balance) / ipb
    else:
        result['initial_oc_pct'] = None

    # OC target and floor
    result['oc_target_pct'] = _extract_oc_target(text)
    result['oc_floor_pct'] = _extract_oc_floor(text)

    # Reserve
    result['initial_reserve_pct'] = _extract_reserve_pct(text)
    result['reserve_floor_pct'] = _extract_reserve_floor(text)

    # Servicing fee
    result['servicing_fee_annual_pct'] = _extract_servicing_fee(text)

    # Triggers
    dq_pct, dq_schedule = _extract_dq_trigger(text)
    result['dq_trigger_pct'] = dq_pct
    result['dq_trigger_schedule'] = dq_schedule

    result['cnl_trigger_schedule'] = _extract_cnl_trigger(text)

    # Dates
    result['cutoff_date'] = _extract_cutoff_date(text)
    result['closing_date'] = _extract_closing_date(text)

    # Validation: if we got fewer than 3 note classes, mark as partial
    if len(notes) < 3:
        logger.warning(f"{deal_slug}: Only found {len(notes)} note classes - marking terms_extracted=0")
        result['terms_extracted'] = 0

    return result


# ──────────────────────────────────────────────────────────────────────
# Database upsert
# ──────────────────────────────────────────────────────────────────────

def _upsert_deal_terms(db_path: str, terms: dict):
    """Insert or replace deal terms into the database."""
    _ensure_table(db_path)
    conn = sqlite3.connect(db_path)

    columns = [
        'deal', 'filing_url', 'initial_pool_balance',
        'class_a1_pct', 'class_a1_coupon',
        'class_a2_pct', 'class_a2_coupon',
        'class_a3_pct', 'class_a3_coupon',
        'class_a4_pct', 'class_a4_coupon',
        'class_b_pct', 'class_b_coupon',
        'class_c_pct', 'class_c_coupon',
        'class_d_pct', 'class_d_coupon',
        'class_n_pct', 'class_n_coupon',
        'weighted_avg_coupon', 'initial_oc_pct',
        'cnl_trigger_schedule', 'dq_trigger_pct', 'dq_trigger_schedule',
        'initial_reserve_pct', 'reserve_floor_pct',
        'oc_target_pct', 'oc_floor_pct',
        'servicing_fee_annual_pct',
        'cutoff_date', 'closing_date',
        'terms_extracted',
    ]

    values = [terms.get(c) for c in columns]
    placeholders = ', '.join(['?'] * len(columns))
    col_names = ', '.join(columns)

    conn.execute(
        f"INSERT OR REPLACE INTO deal_terms ({col_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────
# Main ingestion driver
# ──────────────────────────────────────────────────────────────────────

def ingest_all_deals():
    """Discover and parse 424B for all Carvana and CarMax deals."""
    from carvana_abs.config import DEALS as CARVANA_DEALS
    from carmax_abs.config import DEALS as CARMAX_DEALS

    carvana_db = os.path.join(os.path.dirname(__file__), 'carvana_abs', 'db', 'carvana_abs.db')
    carmax_db = os.path.join(os.path.dirname(__file__), 'carmax_abs', 'db', 'carmax_abs.db')

    _ensure_table(carvana_db)
    _ensure_table(carmax_db)

    results = {'carvana': {'success': 0, 'fail': 0, 'deals': {}},
               'carmax': {'success': 0, 'fail': 0, 'deals': {}}}

    # Process Carvana deals
    for deal_slug, cfg in CARVANA_DEALS.items():
        logger.info(f"Processing Carvana {deal_slug}...")
        try:
            url = find_424b_url(deal_slug, 'carvana', cfg['cik'])
            if not url:
                logger.warning(f"  No 424B found for Carvana {deal_slug}")
                _upsert_deal_terms(carvana_db, {
                    'deal': deal_slug, 'filing_url': None, 'terms_extracted': 0
                })
                results['carvana']['fail'] += 1
                results['carvana']['deals'][deal_slug] = 'no_424b'
                continue

            html = download_document(url)
            if not html:
                logger.warning(f"  Failed to download 424B for Carvana {deal_slug}")
                _upsert_deal_terms(carvana_db, {
                    'deal': deal_slug, 'filing_url': url, 'terms_extracted': 0
                })
                results['carvana']['fail'] += 1
                results['carvana']['deals'][deal_slug] = 'download_failed'
                continue

            terms = parse_prospectus(html, deal_slug, url)
            _upsert_deal_terms(carvana_db, terms)

            if terms['terms_extracted']:
                results['carvana']['success'] += 1
                results['carvana']['deals'][deal_slug] = 'ok'
            else:
                results['carvana']['fail'] += 1
                results['carvana']['deals'][deal_slug] = 'parse_partial'
                logger.warning(f"  Partial parse for Carvana {deal_slug}")

        except Exception as e:
            logger.error(f"  Error processing Carvana {deal_slug}: {e}")
            _upsert_deal_terms(carvana_db, {
                'deal': deal_slug, 'filing_url': None, 'terms_extracted': 0
            })
            results['carvana']['fail'] += 1
            results['carvana']['deals'][deal_slug] = f'error: {e}'

    # Process CarMax deals
    for deal_slug, cfg in CARMAX_DEALS.items():
        logger.info(f"Processing CarMax {deal_slug}...")
        try:
            url = find_424b_url(deal_slug, 'carmax', cfg['cik'])
            if not url:
                logger.warning(f"  No 424B found for CarMax {deal_slug}")
                _upsert_deal_terms(carmax_db, {
                    'deal': deal_slug, 'filing_url': None, 'terms_extracted': 0
                })
                results['carmax']['fail'] += 1
                results['carmax']['deals'][deal_slug] = 'no_424b'
                continue

            html = download_document(url)
            if not html:
                logger.warning(f"  Failed to download 424B for CarMax {deal_slug}")
                _upsert_deal_terms(carmax_db, {
                    'deal': deal_slug, 'filing_url': url, 'terms_extracted': 0
                })
                results['carmax']['fail'] += 1
                results['carmax']['deals'][deal_slug] = 'download_failed'
                continue

            terms = parse_prospectus(html, deal_slug, url)
            _upsert_deal_terms(carmax_db, terms)

            if terms['terms_extracted']:
                results['carmax']['success'] += 1
                results['carmax']['deals'][deal_slug] = 'ok'
            else:
                results['carmax']['fail'] += 1
                results['carmax']['deals'][deal_slug] = 'parse_partial'
                logger.warning(f"  Partial parse for CarMax {deal_slug}")

        except Exception as e:
            logger.error(f"  Error processing CarMax {deal_slug}: {e}")
            _upsert_deal_terms(carmax_db, {
                'deal': deal_slug, 'filing_url': None, 'terms_extracted': 0
            })
            results['carmax']['fail'] += 1
            results['carmax']['deals'][deal_slug] = f'error: {e}'

    return results


def print_report(results: dict):
    """Print summary report."""
    print("\n" + "=" * 70)
    print("PROSPECTUS PARSER RESULTS")
    print("=" * 70)

    for issuer in ['carvana', 'carmax']:
        r = results[issuer]
        total = r['success'] + r['fail']
        print(f"\n{issuer.upper()}: {r['success']}/{total} successful")
        if r['fail'] > 0:
            print(f"  Failed deals:")
            for deal, status in sorted(r['deals'].items()):
                if status != 'ok':
                    print(f"    {deal}: {status}")


def verify_deals():
    """Verify extracted terms for 3 known deals."""
    print("\n" + "=" * 70)
    print("VERIFICATION SPOT-CHECKS")
    print("=" * 70)

    checks = [
        ('carvana_abs/db/carvana_abs.db', '2022-P1', 'Carvana 2022-P1'),
        ('carmax_abs/db/carmax_abs.db', '2020-1', 'CarMax 2020-1'),
        ('carmax_abs/db/carmax_abs.db', '2024-3', 'CarMax 2024-3'),
    ]

    for db_path, deal, label in checks:
        full_path = os.path.join(os.path.dirname(__file__), db_path)
        conn = sqlite3.connect(full_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM deal_terms WHERE deal = ?", (deal,)).fetchone()
        conn.close()

        if not row:
            print(f"\n{label}: NOT FOUND IN DB")
            continue

        print(f"\n{label}:")
        print(f"  Filing URL: {row['filing_url']}")
        print(f"  Initial Pool Balance: ${row['initial_pool_balance']:,.2f}" if row['initial_pool_balance'] else "  Initial Pool Balance: N/A")
        print(f"  terms_extracted: {row['terms_extracted']}")

        # Note structure
        for cls in ['a1', 'a2', 'a3', 'a4', 'b', 'c', 'd', 'n']:
            pct = row[f'class_{cls}_pct']
            cpn = row[f'class_{cls}_coupon']
            if pct is not None:
                print(f"  Class {cls.upper()}: {pct*100:.2f}% of pool, {cpn*100:.4f}% coupon")

        print(f"  Weighted Avg Coupon: {row['weighted_avg_coupon']*100:.4f}%" if row['weighted_avg_coupon'] else "  WAC: N/A")
        print(f"  Initial OC: {row['initial_oc_pct']*100:.2f}%" if row['initial_oc_pct'] else "  OC: N/A")
        print(f"  OC Target: {row['oc_target_pct']*100:.2f}%" if row['oc_target_pct'] else "  OC Target: N/A")
        print(f"  OC Floor: {row['oc_floor_pct']*100:.2f}%" if row['oc_floor_pct'] else "  OC Floor: N/A")
        print(f"  Reserve Initial: {row['initial_reserve_pct']*100:.2f}%" if row['initial_reserve_pct'] else "  Reserve: N/A")
        print(f"  Servicing Fee: {row['servicing_fee_annual_pct']*100:.3f}%" if row['servicing_fee_annual_pct'] else "  Servicing Fee: N/A")
        print(f"  DQ Trigger: {row['dq_trigger_pct']*100:.2f}%" if row['dq_trigger_pct'] else "  DQ Trigger: N/A")
        if row['dq_trigger_schedule']:
            print(f"  DQ Schedule: {row['dq_trigger_schedule'][:200]}")
        if row['cnl_trigger_schedule']:
            print(f"  CNL Schedule: {row['cnl_trigger_schedule'][:200]}")
        print(f"  Cutoff Date: {row['cutoff_date']}")
        print(f"  Closing Date: {row['closing_date']}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    results = ingest_all_deals()
    print_report(results)
    verify_deals()
