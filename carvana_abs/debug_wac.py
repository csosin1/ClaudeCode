#!/usr/bin/env python3
"""Check what WAC looks like in a Donnelley filing."""
import requests, re

h = {"User-Agent": "Clifford Sosin clifford.sosin@casinvestmentpartners.com"}
url = "https://www.sec.gov/Archives/edgar/data/1801738/000119312521047833/d143744dex991.htm"
r = requests.get(url, headers=h)
text = r.text

print(f"Downloaded {len(text)} chars")
for m in re.finditer(r'(?i)(weighted.{0,30}apr|weighted.{0,30}coupon)', text):
    start = max(0, m.start()-30)
    end = min(len(text), m.end()+100)
    print(f"\n...{text[start:end]}...")
