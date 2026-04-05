#!/usr/bin/env python3
"""Download one servicer cert and dump field mapping. Output to stdout."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingestion.edgar_client import download_document
from ingestion.servicer_parser import _extract_numbered_fields, _parse_numbered_value, parse_servicer_cert
from db.schema import get_connection
from config import DB_PATH

conn = get_connection(DB_PATH)
c = conn.cursor()
c.execute("""SELECT servicer_cert_url FROM filings
    WHERE deal='2020-P1' AND servicer_cert_url IS NOT NULL
    ORDER BY filing_date DESC LIMIT 1""")
row = c.fetchone()
conn.close()
if not row:
    print("NO CERT FOUND")
    sys.exit(1)

url = row["servicer_cert_url"]
print(f"URL: {url}")
html = download_document(url)
if not html:
    print("DOWNLOAD FAILED")
    sys.exit(1)

# Try numbered fields
from bs4 import BeautifulSoup
text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
fields = _extract_numbered_fields(text)
if not fields:
    fields = _extract_numbered_fields(html)

if fields:
    print(f"\nExtracted {len(fields)} fields\n")
    # Dump fields 14-62 (note classes area)
    for fnum in range(14, 63):
        if fnum in fields:
            raw = fields[fnum]["raw"][:150].replace("\n", " ")
            pv = _parse_numbered_value(fields[fnum]["raw"])
            print(f"  {fnum:3d}: raw='{raw}' | val={pv.get('value')} pct={pv.get('pct')}")
    # Also 76
    for fnum in [76, 77, 78]:
        if fnum in fields:
            raw = fields[fnum]["raw"][:150].replace("\n", " ")
            pv = _parse_numbered_value(fields[fnum]["raw"])
            print(f"  {fnum:3d}: raw='{raw}' | val={pv.get('value')} pct={pv.get('pct')}")
else:
    print("NO NUMBERED FIELDS - trying regex parse")

print("\n=== FULL PARSE RESULT ===")
result = parse_servicer_cert(html)
for k in sorted(result.keys()):
    print(f"  {k}: {result[k]}")

# Also dump a few rows from the DB
print("\n=== DB: pool_performance for 2020-P1 (last 3 rows) ===")
conn = get_connection(DB_PATH)
c = conn.cursor()
c.execute("""SELECT distribution_date, total_note_interest, aggregate_note_balance,
    note_balance_a1, note_balance_a2, note_balance_b
    FROM pool_performance WHERE deal='2020-P1'
    ORDER BY distribution_date DESC LIMIT 3""")
for row in c.fetchall():
    print(f"  {dict(row)}")
conn.close()
