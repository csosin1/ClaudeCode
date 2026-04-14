import sys, os, sqlite3
from urllib.parse import urlparse
sys.path.insert(0, '/opt/abs-dashboard')
from carmax_abs.ingestion.servicer_parser import store_pool_data
DB = '/opt/abs-dashboard/carmax_abs/db/carmax_abs.db'
CACHE = '/opt/abs-dashboard/carmax_abs/filing_cache'
conn = sqlite3.connect(DB)
rows = list(conn.execute("SELECT deal, accession_number, servicer_cert_url FROM filings WHERE servicer_cert_url IS NOT NULL"))
print(f'Reparsing {len(rows)} CarMax certs...')
ok, miss, fail = 0, 0, 0
for deal, acc, url in rows:
    p = urlparse(url); path = os.path.join(CACHE, p.path.strip('/').replace('/','_'))
    if not os.path.exists(path): miss += 1; continue
    with open(path, errors='replace') as f: html = f.read()
    try:
        if store_pool_data(html, acc, deal, DB): ok += 1
        else: fail += 1
    except Exception as e:
        print(f'  FAIL {deal} {acc}: {e}'); fail += 1
print(f'Done: ok={ok} miss={miss} fail={fail}')
