#!/usr/bin/env python3
"""Test script: Download a few sample files and attempt to parse them.

Usage:
    python test_parse_sample.py

This downloads 2 servicer certs + 1 XML file, shows the HTML structure,
attempts parsing, and reports what worked and what didn't.
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from carvana_abs.config import HEADERS, ARCHIVES_BASE
from carvana_abs.ingestion.edgar_client import fetch_url, download_document
from carvana_abs.ingestion.servicer_parser import parse_servicer_certificate
from carvana_abs.ingestion.xml_parser import parse_auto_loan_xml

os.makedirs("debug_output", exist_ok=True)

# ---- Step 1: Test index.json URL format ----
print("\n" + "="*60)
print("STEP 1: Test filing index URL format")
print("="*60)

test_acc = "0001801738-25-000053"
acc_nodashes = test_acc.replace("-", "")
cik = "1801738"

# Try the corrected format
url = f"{ARCHIVES_BASE}/{cik}/{acc_nodashes}/index.json"
print(f"Trying: {url}")
data = fetch_url(url, max_retries=0, as_json=True)
if data:
    print("SUCCESS! index.json works.")
    items = data.get("directory", {}).get("item", [])
    print(f"Files in this filing ({len(items)}):")
    for item in items:
        print(f"  {item.get('name', '?')} ({item.get('size', '?')} bytes)")
else:
    print("FAILED. Trying alternate format...")
    # Try with accession in filename
    url2 = f"{ARCHIVES_BASE}/{cik}/{acc_nodashes}/{test_acc}-index.json"
    print(f"Trying: {url2}")
    data = fetch_url(url2, max_retries=0, as_json=True)
    if data:
        print("SUCCESS with alternate format!")
    else:
        print("Both formats failed. Trying HTML index...")
        url3 = f"{ARCHIVES_BASE}/{cik}/{acc_nodashes}/"
        print(f"Trying directory listing: {url3}")
        resp = fetch_url(url3, max_retries=0)
        if resp:
            print(f"Got response ({len(resp.text)} chars). First 500 chars:")
            print(resp.text[:500])

# ---- Step 2: Download and diagnose servicer cert HTML ----
print("\n" + "="*60)
print("STEP 2: Diagnose servicer certificate HTML format")
print("="*60)

servicer_urls = [
    ("recent (2025)", f"{ARCHIVES_BASE}/{cik}/{acc_nodashes}/crvna2020-p1servicerrepo.htm"),
    ("older (2021)", f"{ARCHIVES_BASE}/{cik}/000119312521047833/d143744dex991.htm"),
]

for label, url in servicer_urls:
    print(f"\n--- {label} ---")
    print(f"URL: {url}")
    html = download_document(url)
    if not html:
        print("  FAILED to download")
        continue

    # Save for inspection
    safe_label = label.replace(" ", "_").replace("(", "").replace(")", "")
    filepath = f"debug_output/servicer_{safe_label}.htm"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved to {filepath} ({len(html)} chars)")

    # Analyze structure
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    divs = soup.find_all("div")
    spans = soup.find_all("span")
    ps = soup.find_all("p")

    print(f"  <table>: {len(tables)}")
    print(f"  <div>:   {len(divs)}")
    print(f"  <span>:  {len(spans)}")
    print(f"  <p>:     {len(ps)}")

    all_tags = set(tag.name for tag in soup.find_all(True))
    print(f"  All tags: {sorted(all_tags)}")

    # Show text content sample
    text = soup.get_text(separator="\n", strip=True)
    lines = [l for l in text.split("\n") if l.strip()]
    print(f"  Text lines: {len(lines)}")
    print(f"\n  First 30 text lines:")
    for line in lines[:30]:
        print(f"    {line[:120]}")

    # Try parsing
    result = parse_servicer_certificate(html)
    print(f"\n  Parse result: {len(result)} fields extracted")
    for key, val in result.items():
        if val is not None:
            print(f"    {key}: {val}")

# ---- Step 3: Test XML parsing via ABS-EE filing ----
print("\n" + "="*60)
print("STEP 3: Test XML loan data parsing")
print("="*60)

# The XML is in the ABS-EE filing (accession 0001801738-25-000051),
# which is paired with 10-D filing 0001801738-25-000053
absee_acc = "0001801738-25-000051"
absee_nodashes = absee_acc.replace("-", "")

# First, look up the ABS-EE index to find the XML filename
absee_index_url = f"{ARCHIVES_BASE}/{cik}/{absee_nodashes}/index.json"
print(f"Fetching ABS-EE index: {absee_index_url}")
absee_index = fetch_url(absee_index_url, max_retries=1, as_json=True)
xml_url = None
if absee_index:
    items = absee_index.get("directory", {}).get("item", [])
    print(f"Files in ABS-EE filing ({len(items)}):")
    for item in items:
        name = item.get("name", "")
        print(f"  {name}")
        if name.lower().endswith(".xml") and ("ex102" in name.lower()):
            xml_url = f"{ARCHIVES_BASE}/{cik}/{absee_nodashes}/{name}"

if xml_url:
    print(f"\nDownloading XML: {xml_url}")
    xml_content = download_document(xml_url)
    if xml_content:
        print(f"Downloaded {len(xml_content)} chars")
        with open("debug_output/sample_xml.txt", "w", encoding="utf-8") as f:
            f.write(xml_content[:5000])

        result = parse_auto_loan_xml(xml_content)
        print(f"Loans parsed: {len(result['loans'])}")
        print(f"Performance records: {len(result['performance'])}")

        if result["loans"]:
            loan = result["loans"][0]
            print(f"\nFirst loan sample:")
            for key, val in loan.items():
                if val is not None:
                    print(f"  {key}: {val}")

        if result["performance"]:
            perf = result["performance"][0]
            print(f"\nFirst performance sample:")
            for key, val in perf.items():
                if val is not None:
                    print(f"  {key}: {val}")
    else:
        print("FAILED to download XML")
else:
    print("Could not find XML URL in ABS-EE index")

# ---- Step 4: Test full re-discovery with new index.json logic ----
print("\n" + "="*60)
print("STEP 4: Quick re-ingestion test (resets DB, discovers fresh)")
print("="*60)
print("To re-run full ingestion with the fixes, delete the old database first:")
print("  Remove-Item db\\carvana_abs.db")
print("  python run_ingestion.py")
print("This will be MUCH faster now (no 404 retries).")

print("\n" + "="*60)
print("DONE. Paste this output back to Claude.")
print("="*60)
