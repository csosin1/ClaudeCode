#!/usr/bin/env python3
"""Diagnostic: Extract ALL text from a JPG-based servicer certificate.

The recent Carvana servicer certs embed JPG images but may have text in
alt attributes, title attributes, or surrounding elements. This script
downloads one and dumps every scrap of text it can find.

Run:  python debug_jpg_servicer.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carvana_abs.config import HEADERS, ARCHIVES_BASE
from carvana_abs.ingestion.edgar_client import download_document
from bs4 import BeautifulSoup

os.makedirs("debug_output", exist_ok=True)

# Recent JPG-based servicer cert
cik = "1801738"
url = f"{ARCHIVES_BASE}/{cik}/000180173825000053/crvna2020-p1servicerrepo.htm"

print(f"Downloading: {url}")
html = download_document(url)
if not html:
    print("FAILED")
    sys.exit(1)

with open("debug_output/jpg_servicer_raw.htm", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved raw HTML ({len(html)} chars)")

soup = BeautifulSoup(html, "html.parser")

# 1. All text content
print("\n=== ALL TEXT CONTENT ===")
text = soup.get_text(separator="\n", strip=True)
for i, line in enumerate(text.split("\n")):
    if line.strip():
        print(f"  [{i}] {line[:300]}")

# 2. All img tags with their attributes
print("\n=== IMG TAGS ===")
for img in soup.find_all("img"):
    print(f"  src: {img.get('src', '?')}")
    print(f"  alt: {img.get('alt', '(none)')[:200]}")
    print(f"  title: {img.get('title', '(none)')[:200]}")
    print(f"  all attrs: {dict(img.attrs)}")
    print()

# 3. All <p> tags with content
print("\n=== P TAGS ===")
for p in soup.find_all("p"):
    text = p.get_text(strip=True)
    if text:
        print(f"  {text[:300]}")

# 4. All <div> tags with content
print("\n=== DIV TAGS WITH TEXT ===")
for div in soup.find_all("div"):
    text = div.get_text(strip=True)
    if text and len(text) > 20:
        print(f"  {text[:300]}")
        print()

# 5. All <font> tags
print("\n=== FONT TAGS ===")
for font in soup.find_all("font"):
    text = font.get_text(strip=True)
    if text:
        print(f"  {text[:300]}")

# 6. Check for hidden/commented text
print("\n=== HTML COMMENTS ===")
from bs4 import Comment
comments = soup.find_all(string=lambda text: isinstance(text, Comment))
for c in comments[:10]:
    print(f"  {str(c)[:300]}")

# 7. Raw strings that look like numbers
import re
print("\n=== NUMBER-LIKE STRINGS IN RAW HTML ===")
numbers = re.findall(r'[\d,]{5,}\.?\d*', html)
for n in numbers[:30]:
    print(f"  {n}")

print("\n=== DONE ===")
print("Check debug_output/jpg_servicer_raw.htm for the full HTML source.")
