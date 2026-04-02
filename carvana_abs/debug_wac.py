#!/usr/bin/env python3
"""Check what WAC looks like in a Donnelley filing."""
import requests, re
from bs4 import BeautifulSoup

h = {"User-Agent": "Clifford Sosin clifford.sosin@casinvestmentpartners.com"}
url = "https://www.sec.gov/Archives/edgar/data/1801738/000119312521047833/d143744dex991.htm"
r = requests.get(url, headers=h)

soup = BeautifulSoup(r.text, "html.parser")
tables = soup.find_all("table")
print(f"Tables: {len(tables)}")

for table in tables:
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        text = " ".join(c.get_text(strip=True) for c in cells)
        if "weighted" in text.lower() and "apr" in text.lower():
            print(f"\nFound WAC row with {len(cells)} cells:")
            for i, c in enumerate(cells):
                print(f"  [{i}] '{c.get_text(strip=True)}'")

# Also check what the numbered text parser sees
all_text = soup.get_text(separator=" ", strip=True)
m = re.search(r'(?i)weighted.{0,20}apr.{0,200}', all_text)
if m:
    print(f"\nFull text around WAC:\n{m.group()}")

# Check for (105)
m2 = re.search(r'\(105\).{0,200}', all_text)
if m2:
    print(f"\nField (105):\n{m2.group()}")
