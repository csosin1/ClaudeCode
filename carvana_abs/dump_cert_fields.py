#!/usr/bin/env python3
"""Diagnostic: download one servicer cert and dump raw numbered fields.
Runs on the server via auto-deploy. Writes output to deploy/LAST_CERT_FIELDS.txt."""
import sys, os, re, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from ingestion.edgar_client import download_document
from ingestion.servicer_parser import _extract_numbered_fields, _parse_numbered_value
from db.schema import get_connection
from config import DB_PATH

def main():
    # Find a servicer cert URL for 2020-P1 (oldest deal, most data)
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT accession_number, servicer_cert_url
        FROM filings
        WHERE deal = '2020-P1' AND servicer_cert_url IS NOT NULL
        ORDER BY filing_date DESC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if not row:
        print("ERROR: No servicer cert found for 2020-P1")
        return

    acc = row["accession_number"]
    url = row["servicer_cert_url"]
    print(f"Accession: {acc}")
    print(f"URL: {url}")
    print()

    # Download
    html = download_document(url)
    if not html:
        print("ERROR: Failed to download cert")
        return

    print(f"Downloaded: {len(html)} chars")
    print()

    # Extract numbered fields
    fields = _extract_numbered_fields(html)
    if not fields:
        # Try stripping HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        fields = _extract_numbered_fields(text)

    if not fields:
        print("ERROR: No numbered fields extracted")
        print("First 2000 chars of text:")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        print(soup.get_text("\n", strip=True)[:2000])
        return

    print(f"Extracted {len(fields)} numbered fields")
    print()

    # Dump ALL fields related to notes (fields 14-62 cover all note classes)
    print("=" * 80)
    print("NOTE-RELATED FIELDS (14-62)")
    print("=" * 80)

    # Expected layout per class (7 fields each):
    # A1: 14-20, A2: 20-26, A3: 26-32, A4: 32-38, B: 38-44, C: 44-50, D: 50-56, N: 55-61
    class_starts = {
        "A1": 14, "A2": 20, "A3": 26, "A4": 32,
        "B": 38, "C": 44, "D": 50, "N": 55,
    }
    field_labels = ["Rate", "Interest Distributable", "Interest Paid", "Shortfall", "Balance Before", "Principal Paid", "Balance After"]

    for cls, start in class_starts.items():
        print(f"\n--- Class {cls} (fields {start}-{start+6}) ---")
        for offset, label in enumerate(field_labels):
            fnum = start + offset
            if fnum in fields:
                raw = fields[fnum]["raw"][:200]
                parsed = _parse_numbered_value(fields[fnum]["raw"])
                print(f"  Field {fnum:3d} [{label:25s}]: raw='{raw}' -> val={parsed.get('value')}, pct={parsed.get('pct')}")
            else:
                print(f"  Field {fnum:3d} [{label:25s}]: NOT FOUND")

    # Also dump aggregate fields
    print()
    print("=" * 80)
    print("AGGREGATE FIELDS")
    print("=" * 80)
    for fnum in [76, 77, 78, 81]:
        label = {76: "Aggregate Note Balance", 77: "Specified Reserve", 78: "Reserve Balance", 81: "Reserve Balance (alt)"}.get(fnum, "Unknown")
        if fnum in fields:
            raw = fields[fnum]["raw"][:200]
            parsed = _parse_numbered_value(fields[fnum]["raw"])
            print(f"  Field {fnum:3d} [{label:25s}]: raw='{raw}' -> val={parsed.get('value')}")
        else:
            print(f"  Field {fnum:3d} [{label:25s}]: NOT FOUND")

    # Also dump the full parse result
    print()
    print("=" * 80)
    print("FULL PARSER OUTPUT")
    print("=" * 80)
    from ingestion.servicer_parser import parse_servicer_cert
    result = parse_servicer_cert(html)
    for k, v in sorted(result.items()):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
