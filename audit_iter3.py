"""Eyeball audit iter3 — 10 random + 3 bonus fixed-cell checks.

Pulls raw cached servicer-cert HTML, strips to text via BeautifulSoup,
prints a 150-char window around each metric so a human can eyeball it.
"""
import sqlite3
import random
import os
from urllib.parse import urlparse
from bs4 import BeautifulSoup

CARVANA_DB = '/opt/abs-dashboard/carvana_abs/db/carvana_abs.db'
CARMAX_DB = '/opt/abs-dashboard/carmax_abs/db/carmax_abs.db'
CARVANA_CACHE = '/opt/abs-dashboard/carvana_abs/filing_cache'
CARMAX_CACHE = '/opt/abs-dashboard/carmax_abs/filing_cache'

METRICS = [
    'reserve_account_balance',
    'aggregate_note_balance',
    'total_delinquent_balance',
    'cumulative_net_losses',
    'ending_pool_balance',
    'beginning_pool_balance',
    'cumulative_gross_losses',
    'principal_collections',
]


def url_to_path(url: str, cache_dir: str) -> str:
    path = urlparse(url).path.strip('/').replace('/', '_')
    return os.path.join(cache_dir, path)


def load_text(url: str, cache_dir: str) -> str:
    p = url_to_path(url, cache_dir)
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    return soup.get_text(' ', strip=True)


def pick_samples(seed: int = 99):
    random.seed(seed)
    # desired mix: 2 reserve, 2 agg note, 2 delinquency, 2 cum loss, 2 other
    desired_metrics = [
        'reserve_account_balance', 'reserve_account_balance',
        'aggregate_note_balance', 'aggregate_note_balance',
        'total_delinquent_balance', 'total_delinquent_balance',
        'cumulative_net_losses', 'cumulative_net_losses',
        'ending_pool_balance', 'principal_collections',
    ]
    # 5 carvana + 5 carmax — shuffle metrics between them
    random.shuffle(desired_metrics)
    issuers = ['carvana'] * 5 + ['carmax'] * 5
    random.shuffle(issuers)

    samples = []
    for issuer, metric in zip(issuers, desired_metrics):
        db = CARVANA_DB if issuer == 'carvana' else CARMAX_DB
        c = sqlite3.connect(db)
        rows = c.execute(
            f"""
            SELECT pp.deal, pp.distribution_date, pp.{metric}, f.servicer_cert_url
            FROM pool_performance pp JOIN filings f USING(accession_number)
            WHERE f.servicer_cert_url IS NOT NULL AND pp.{metric} IS NOT NULL
            """
        ).fetchall()
        row = random.choice(rows)
        samples.append({
            'issuer': issuer, 'deal': row[0], 'date': row[1],
            'metric': metric, 'stored': row[2], 'url': row[3],
        })
        c.close()
    return samples


def find_window(text: str, value: float, metric: str) -> str:
    """Search raw text for the value formatted as a number. Return 150-char window."""
    if value is None:
        return '<NULL>'
    # try formatting w/ commas 2 decimals, then various forms
    candidates = [
        f'{value:,.2f}',
        f'{value:,.0f}',
        f'{int(value):,}',
        f'{value:.2f}',
        str(int(value)),
    ]
    # dedupe
    seen = set()
    cands = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            cands.append(c)
    for c in cands:
        idx = text.find(c)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(text), idx + 50 + len(c))
            return '...' + text[start:end].replace('\n', ' ') + '...'
    return f'<VALUE {value} NOT FOUND in text>'


def audit(samples, label='RANDOM'):
    results = []
    for i, s in enumerate(samples, 1):
        cache = CARVANA_CACHE if s['issuer'] == 'carvana' else CARMAX_CACHE
        text = load_text(s['url'], cache)
        if text is None:
            window = '<cache miss>'
        else:
            window = find_window(text, s['stored'], s['metric'])
        s['window'] = window
        print(f"\n--- {label} {i}: {s['issuer']} {s['deal']} {s['date']} {s['metric']}")
        print(f"  stored={s['stored']}")
        print(f"  url={s['url']}")
        print(f"  window: {window}")
        results.append(s)
    return results


def bonus():
    """Check the 3 cells fixed by parser updates."""
    checks = [
        ('carvana', '2022-P1', 'reserve_account_balance', 6237090.00, 'was 3,118,545'),
        ('carmax', '2021-1', 'reserve_account_balance', 7526352.80, 'was NULL'),
        ('carmax', '2024-3', 'aggregate_note_balance', 874511262.33, 'was NULL'),
    ]
    out = []
    for issuer, deal, metric, expected, note in checks:
        db = CARVANA_DB if issuer == 'carvana' else CARMAX_DB
        cache = CARVANA_CACHE if issuer == 'carvana' else CARMAX_CACHE
        c = sqlite3.connect(db)
        # use a specific distribution date from prior audit if possible - take most recent with non-null
        row = c.execute(
            f"""
            SELECT pp.deal, pp.distribution_date, pp.{metric}, f.servicer_cert_url
            FROM pool_performance pp JOIN filings f USING(accession_number)
            WHERE pp.deal = ? AND f.servicer_cert_url IS NOT NULL
            ORDER BY pp.distribution_date DESC LIMIT 1
            """,
            (deal,),
        ).fetchone()
        c.close()
        if not row:
            out.append({'issuer': issuer, 'deal': deal, 'metric': metric,
                        'stored': None, 'expected': expected, 'window': '<no row>',
                        'note': note})
            continue
        text = load_text(row[3], cache)
        stored = row[2]
        window = find_window(text, stored, metric) if text else '<cache miss>'
        out.append({
            'issuer': issuer, 'deal': deal, 'date': row[1], 'metric': metric,
            'stored': stored, 'expected': expected, 'window': window, 'note': note,
            'url': row[3],
        })
        print(f"\n--- BONUS {issuer} {deal} {metric} ({note})")
        print(f"  stored={stored}  expected~{expected}")
        print(f"  date={row[1]}")
        print(f"  url={row[3]}")
        print(f"  window: {window}")
    return out


if __name__ == '__main__':
    samples = pick_samples(99)
    rand_results = audit(samples, 'RANDOM')
    print('\n\n============ BONUS (3 previously-fixed cells) ============')
    bonus_results = bonus()
    # stash for writer
    import json
    with open('/tmp/audit_iter3.json', 'w') as f:
        json.dump({'random': rand_results, 'bonus': bonus_results}, f, indent=2, default=str)
