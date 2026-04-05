#!/usr/bin/env python3
"""Generate PDF documents from cached servicer certificates for the Carvana ABS dashboard.

Reads the filings table to find servicer_cert_url entries, loads cached HTML from
filing_cache/, converts to PDF using weasyprint (if available), and saves to
static_site/docs/{deal}/ and static_site/preview/docs/{deal}/.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB
CACHE_DIR = os.path.join(BASE_DIR, "filing_cache")
STATIC_DIR = os.path.join(BASE_DIR, "static_site")

# Try to import weasyprint for HTML-to-PDF conversion
try:
    from weasyprint import HTML as WeasyprintHTML
    HAS_WEASYPRINT = True
    logger.info("weasyprint available — will generate PDFs")
except ImportError:
    HAS_WEASYPRINT = False
    logger.warning("weasyprint not available — will save as HTML instead of PDF")


def _cache_path(url):
    """Get local cache path for a URL (mirrors edgar_client._cache_path)."""
    parsed = urlparse(url)
    safe_name = parsed.path.strip("/").replace("/", "_")
    return os.path.join(CACHE_DIR, safe_name)


def _format_filing_date(filing_date_str):
    """Convert filing_date (e.g. '2025-12-15') to 'YYYY-MM' for filenames."""
    if not filing_date_str:
        return "unknown"
    try:
        dt = datetime.strptime(str(filing_date_str).strip()[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m")
    except (ValueError, TypeError):
        # Try other formats
        for fmt in ["%m-%d-%Y", "%m/%d/%Y"]:
            try:
                dt = datetime.strptime(str(filing_date_str).strip()[:10], fmt)
                return dt.strftime("%Y-%m")
            except (ValueError, TypeError):
                continue
        return str(filing_date_str).strip()[:7]


def _format_filing_date_display(filing_date_str):
    """Convert filing_date to human-readable display like 'Dec 2025'."""
    if not filing_date_str:
        return "Unknown"
    try:
        dt = datetime.strptime(str(filing_date_str).strip()[:10], "%Y-%m-%d")
        return dt.strftime("%b %Y")
    except (ValueError, TypeError):
        for fmt in ["%m-%d-%Y", "%m/%d/%Y"]:
            try:
                dt = datetime.strptime(str(filing_date_str).strip()[:10], fmt)
                return dt.strftime("%b %Y")
            except (ValueError, TypeError):
                continue
        return str(filing_date_str).strip()[:10]


def _wrap_html_for_pdf(html_content, title="Servicer Certificate"):
    """Wrap raw HTML content in a basic styled page suitable for PDF generation."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
body {{ font-family: Arial, Helvetica, sans-serif; font-size: 10pt; margin: 1cm; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; font-size: 9pt; }}
th {{ background: #f0f0f0; font-weight: bold; }}
h1, h2, h3 {{ color: #333; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""


def generate_pdf(html_content, output_path, title="Servicer Certificate"):
    """Convert HTML content to PDF (or save as HTML if weasyprint unavailable).

    Returns the actual output path (may have .html extension if weasyprint failed).
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wrapped = _wrap_html_for_pdf(html_content, title)

    if HAS_WEASYPRINT:
        try:
            WeasyprintHTML(string=wrapped).write_pdf(output_path)
            logger.info(f"  Generated PDF: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"  weasyprint failed for {output_path}: {e}")
            # Fall through to HTML fallback

    # Fallback: save as HTML
    html_path = output_path.replace(".pdf", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    logger.info(f"  Saved HTML fallback: {html_path}")
    return html_path


def generate_all_pdfs():
    """Generate PDFs for all deals that have servicer certificates."""
    if not os.path.exists(ACTIVE_DB):
        logger.error(f"Database not found: {ACTIVE_DB}")
        return {}

    conn = sqlite3.connect(ACTIVE_DB)
    conn.row_factory = sqlite3.Row

    # Query all filings with servicer cert URLs
    cursor = conn.execute("""
        SELECT deal, filing_date, servicer_cert_url, accession_number, filing_type
        FROM filings
        WHERE servicer_cert_url IS NOT NULL
        ORDER BY deal, filing_date DESC
    """)
    filings = cursor.fetchall()
    conn.close()

    if not filings:
        logger.info("No filings with servicer_cert_url found.")
        return {}

    # Track generated files per deal: {deal: [(filing_date, filename, exists)]}
    generated = {}
    total_generated = 0
    total_skipped = 0

    for row in filings:
        deal = row["deal"]
        filing_date = row["filing_date"]
        cert_url = row["servicer_cert_url"]
        accession = row["accession_number"]

        date_slug = _format_filing_date(filing_date)
        filename_base = f"{deal}_servicer_{date_slug}"

        # Check if cached HTML exists
        cache_file = _cache_path(cert_url)
        if not os.path.exists(cache_file):
            logger.debug(f"  Cache miss for {deal} {date_slug}: {cache_file}")
            # Record as not generated but still list the filing
            if deal not in generated:
                generated[deal] = []
            generated[deal].append({
                "filing_date": filing_date,
                "date_display": _format_filing_date_display(filing_date),
                "filename": None,
                "sec_url": cert_url,
                "accession": accession,
            })
            total_skipped += 1
            continue

        # Read cached content
        with open(cache_file, "r", errors="replace") as f:
            html_content = f.read()

        if not html_content.strip():
            logger.warning(f"  Empty cache file for {deal} {date_slug}")
            total_skipped += 1
            continue

        # Generate PDF to both live and preview docs directories
        title = f"Carvana {deal} — Servicer Certificate ({_format_filing_date_display(filing_date)})"
        pdf_filename = f"{filename_base}.pdf"

        for subdir in ["docs", os.path.join("preview", "docs")]:
            out_dir = os.path.join(STATIC_DIR, subdir, deal)
            out_path = os.path.join(out_dir, pdf_filename)

            # Skip if already generated (avoid re-generating unchanged files)
            if os.path.exists(out_path) and os.path.getmtime(out_path) > os.path.getmtime(cache_file):
                logger.debug(f"  Already up to date: {out_path}")
                continue

            actual_path = generate_pdf(html_content, out_path, title)
            # Update filename if it ended up as HTML
            if actual_path.endswith(".html"):
                pdf_filename = f"{filename_base}.html"

        if deal not in generated:
            generated[deal] = []
        generated[deal].append({
            "filing_date": filing_date,
            "date_display": _format_filing_date_display(filing_date),
            "filename": pdf_filename,
            "sec_url": cert_url,
            "accession": accession,
        })
        total_generated += 1

    logger.info(f"PDF generation complete: {total_generated} generated, {total_skipped} skipped "
                f"(no cache), {len(generated)} deals")
    return generated


def main():
    generated = generate_all_pdfs()
    for deal, docs in generated.items():
        cached = sum(1 for d in docs if d["filename"])
        logger.info(f"  {deal}: {cached} PDFs, {len(docs) - cached} SEC-only links")


if __name__ == "__main__":
    main()
