#!/usr/bin/env python3
"""Diagnostic: Download one servicer cert and one XML file, show their structure.

Run from the carvana_abs directory:
    python debug_downloads.py

This will save samples to debug_output/ and print a summary.
"""

import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import HEADERS

os.makedirs("debug_output", exist_ok=True)

# One recent servicer cert (self-filed, 2025)
SERVICER_URLS = [
    ("recent_servicer.htm", "https://www.sec.gov/Archives/edgar/data/1801738/000180173825000053/crvna2020-p1servicerrepo.htm"),
    # One older servicer cert (Donnelley-filed, 2021)
    ("older_servicer.htm", "https://www.sec.gov/Archives/edgar/data/1801738/000119312521047833/d143744dex991.htm"),
]

for filename, url in SERVICER_URLS:
    print(f"\n{'='*60}")
    print(f"Downloading: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        content = resp.text

        # Save full file
        filepath = os.path.join("debug_output", filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Saved to: {filepath} ({len(content)} chars)")

        # Show first 100 lines
        lines = content.split("\n")
        print(f"Total lines: {len(lines)}")
        print(f"\n--- First 100 lines ---")
        for line in lines[:100]:
            print(line[:200])  # Truncate long lines

        # Check for tables
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        tables = soup.find_all("table")
        print(f"\n--- Structure summary ---")
        print(f"<table> tags found: {len(tables)}")
        print(f"<div> tags found: {len(soup.find_all('div'))}")
        print(f"<iframe> tags found: {len(soup.find_all('iframe'))}")
        print(f"<pre> tags found: {len(soup.find_all('pre'))}")
        print(f"<p> tags found: {len(soup.find_all('p'))}")
        print(f"<span> tags found: {len(soup.find_all('span'))}")

        # If no tables, show all unique tag names
        if len(tables) == 0:
            all_tags = set(tag.name for tag in soup.find_all(True))
            print(f"All HTML tags used: {sorted(all_tags)}")

            # Show the first 500 chars of text content
            text = soup.get_text(separator="\n", strip=True)
            print(f"\n--- First 500 chars of text content ---")
            print(text[:500])

    except Exception as e:
        print(f"ERROR: {e}")

print(f"\n{'='*60}")
print("Done. Now paste the output above back to Claude.")
print("Or if the output is very long, just paste the '--- Structure summary ---' sections.")
