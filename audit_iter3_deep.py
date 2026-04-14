"""Deeper eyeball dive on ambiguous cases."""
import os
from urllib.parse import urlparse
from bs4 import BeautifulSoup

CARVANA_CACHE = '/opt/abs-dashboard/carvana_abs/filing_cache'
CARMAX_CACHE = '/opt/abs-dashboard/carmax_abs/filing_cache'


def load(url, cache):
    p = os.path.join(cache, urlparse(url).path.strip('/').replace('/', '_'))
    with open(p, 'rb') as f:
        return BeautifulSoup(f.read(), 'html.parser').get_text(' ', strip=True)


def find_all(text, needle, before=120, after=200):
    results = []
    i = 0
    while True:
        idx = text.find(needle, i)
        if idx == -1:
            break
        results.append(text[max(0, idx - before):idx + len(needle) + after].replace('\n', ' '))
        i = idx + 1
    return results


# CASE A: Carvana 2021-P2 aggregate_note_balance — find "Aggregate Note Balance" line
print('=== Carvana 2021-P2 aggregate_note_balance ===')
t = load('https://www.sec.gov/Archives/edgar/data/1843657/000119312522194692/d369891dex991.htm', CARVANA_CACHE)
for w in find_all(t, 'Aggregate Note Balance', 80, 200):
    print('  [AGG]', w, '\n')
# also look for 479,154,814.42
for w in find_all(t, '479,154,814.42', 200, 100):
    print('  [VAL]', w, '\n')

# CASE B: Carvana 2022-P1 reserve (9/12/2022 filing)
print('\n=== Carvana 2022-P1 reserve_account_balance (9/12/2022) ===')
t = load('https://www.sec.gov/Archives/edgar/data/1903763/000119312522245534/d379986dex991.htm', CARVANA_CACHE)
for w in find_all(t, 'Ending Reserve Account', 100, 200):
    print('  [END RSV]', w, '\n')
for w in find_all(t, 'Specified Reserve', 100, 200):
    print('  [SPEC]', w, '\n')
for w in find_all(t, '6,237,090', 200, 100):
    print('  [VAL]', w, '\n')

# CASE C: Carvana 2022-P1 reserve (1/12/2026 filing)
print('\n=== Carvana 2022-P1 reserve_account_balance (1/12/2026 - random #3) ===')
t = load('https://www.sec.gov/Archives/edgar/data/1903763/000190376326000004/crvna2022-p1servicerrepo.htm', CARVANA_CACHE)
for w in find_all(t, 'Ending Reserve Account', 100, 200):
    print('  [END RSV]', w, '\n')
for w in find_all(t, '6,237,090', 200, 100):
    print('  [VAL 6237090]', w, '\n')

# CASE D: Carvana 2021-N3 reserve
print('\n=== Carvana 2021-N3 reserve_account_balance ===')
t = load('https://www.sec.gov/Archives/edgar/data/1843653/000119312522245528/d378499dex991.htm', CARVANA_CACHE)
for w in find_all(t, 'Ending Reserve Account', 100, 200):
    print('  [END RSV]', w, '\n')
for w in find_all(t, '5,250,000', 200, 100):
    print('  [VAL 5250000]', w, '\n')

# CASE E: Carvana 2022-P2 aggregate_note_balance
print('\n=== Carvana 2022-P2 aggregate_note_balance ===')
t = load('https://www.sec.gov/Archives/edgar/data/1903753/000190375323000004/crvna2022-p2servicerrepo.htm', CARVANA_CACHE)
for w in find_all(t, 'Aggregate Note Balance', 80, 200):
    print('  [AGG]', w, '\n')
for w in find_all(t, '379,161,031.35', 200, 100):
    print('  [VAL]', w, '\n')

# CASE F: CarMax 2021-1 reserve
print('\n=== CarMax 2021-1 reserve (9/16/2024) ===')
t = load('https://www.sec.gov/Archives/edgar/data/1836214/000183621424000048/a2021-1ex991091624.htm', CARMAX_CACHE)
for w in find_all(t, 'Ending Balance', 100, 200):
    print('  [END BAL]', w, '\n')
for w in find_all(t, '7,526,352.80', 200, 100):
    print('  [VAL]', w, '\n')

# CASE G: CarMax 2024-3 aggregate_note_balance (BONUS - stored 1,303,373,001.03)
print('\n=== CarMax 2024-3 aggregate_note_balance (9/16/2024 - bonus) ===')
t = load('https://www.sec.gov/Archives/edgar/data/2029255/000202925524000011/a2024-3ex991091624.htm', CARMAX_CACHE)
for w in find_all(t, 'Note Balance (sum', 80, 200):
    print('  [NB]', w, '\n')
for w in find_all(t, '1,303,373,001.03', 200, 100):
    print('  [VAL]', w, '\n')

# Also check the original 8/15/2025 filing for 874M expected
print('\n=== CarMax 2024-3 — looking for older filing with 874M ===')
# I need to find the 8/15/2025 distribution for 2024-3
import sqlite3
c = sqlite3.connect('/opt/abs-dashboard/carmax_abs/db/carmax_abs.db')
rows = c.execute("""
    SELECT pp.deal, pp.distribution_date, pp.aggregate_note_balance, f.servicer_cert_url
    FROM pool_performance pp JOIN filings f USING(accession_number)
    WHERE pp.deal = '2024-3' ORDER BY pp.dist_date_iso
""").fetchall()
for r in rows:
    print(r)
