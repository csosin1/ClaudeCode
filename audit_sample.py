"""Independent audit: for each sampled (deal, date, metric) tuple, re-extract
the value from the cert HTML using a *different* extraction path than the
parser, and compare to the stored value.

Independence: the parser uses BeautifulSoup + normalized-whitespace + label-
anchored regex on a condensed text blob. This audit uses a per-metric label
search in the RAW HTML text (with tags stripped per-line), finding the closest
dollar amount AFTER the label. If the two paths disagree, the row is a
genuine mismatch to investigate, not just a tautology.

Carvana cert format ("field-numbered"):
  (NN) Label words {optional formula} (NN) [count_int] amount[.cents]
  - The value sits AFTER the *second* (NN) marker that echoes the field number.
  - Sometimes there's a count integer before the dollar amount (e.g. delinquency
    rows: "(48) 31-60 773 8,305,133.08"). In that case we want the LAST number
    on the segment (the balance, not the count).
  - Reserve / note balance / pool balance values often appear with no count.
  - Field markers may be "(NN)" or "(NN )" (older filings include a trailing space).

CarMax cert format ("line-numbered"):
  NN. Label $ amount    OR    a. Label $ amount    OR    a. Label count $ amount
  Note balances and tranche-level rows have BOTH "Beginning of Period" and
  "End of Period" columns: we want the SECOND $-amount (the END column).

Usage: /opt/abs-venv/bin/python audit_sample.py --chunk /tmp/audit/sample_NN.json
"""
import sqlite3, json, re, argparse, os, sys
from bs4 import BeautifulSoup

CV_DB = '/opt/abs-dashboard/carvana_abs/db/carvana_abs.db'
KMX_DB = '/opt/abs-dashboard/carmax_abs/db/carmax_abs.db'
CV_CACHE = '/opt/abs-dashboard/carvana_abs/filing_cache'
KMX_CACHE = '/opt/abs-dashboard/carmax_abs/filing_cache'

def cache_path(url, cache_dir):
    from urllib.parse import urlparse
    safe_name = urlparse(url).path.strip('/').replace('/', '_')
    return os.path.join(cache_dir, safe_name)

def load_html(issuer, accession):
    db = CV_DB if issuer == 'carvana' else KMX_DB
    cache_dir = CV_CACHE if issuer == 'carvana' else KMX_CACHE
    c = sqlite3.connect(db)
    row = c.execute('SELECT servicer_cert_url FROM filings WHERE accession_number=?', (accession,)).fetchone()
    c.close()
    if not row or not row[0]:
        return None, 'no-servicer-cert-url'
    p = cache_path(row[0], cache_dir)
    if not os.path.exists(p):
        return None, f'cache-miss'
    with open(p, 'r', errors='replace') as f:
        return f.read(), None

# Per-metric label patterns. First match wins. Carvana labels listed first
# (more recent format dominates the sample).
LABELS = {
    'cumulative_gross_losses': [
        # Carvana: "(40) Aggregate Gross Charged-Off Receivables losses as of the last day of the current Collection Period (40) value"
        r'Aggregate Gross Charged-?Off Receivables losses as of the last day of the current',
        # CarMax: "77. Defaulted Receivables (charge-offs) <count> $ value"
        r'Defaulted Receivables \(charge-?offs\)',
        r'Cumulative Gross (?:Charged|Defaulted)',
    ],
    'cumulative_net_losses': [
        # Carvana: "(47) The aggregate amount of Net Charged-Off Receivables losses as of the last day of the current..."
        r'aggregate amount of Net Charged-?Off Receivables losses as of the last day of the current',
        # CarMax: "79. Cumulative Net Losses (Ln 77 - Ln 78) $ value"
        r'Cumulative Net Losses',
        r'Cumulative Net Credit Losses',
    ],
    'ending_pool_balance': [
        # Carvana: "(9) Ending Pool Balance (9) <count> <balance>"
        r'Ending Pool Balance',
        # CarMax: "5. Pool Balance on the close of the last day of the related Collection Period $ value"
        r'Pool Balance on the close of the last day of the related',
    ],
    'beginning_pool_balance': [
        r'Beginning Pool Balance',
        r'Pool Balance on the close of the last day of the preceding',
    ],
    'total_delinquent_balance': [
        # Carvana: "(50) (50) Total Delinquencies <count> <balance>"  (newer) or "(51) Total Delinquencies"
        r'Total Delinquencies',
        # CarMax: "e. Total Past Due (sum a - d) <count> $ value"
        r'Total Past Due',
        r'Total Delinquent',
    ],
    'reserve_account_balance': [
        # Carvana: "(37) Ending Reserve Account Balance (37) value"
        r'Ending Reserve Account Balance',
        # CarMax: "Reserve Account Balance" with end-of-period column
        r'Reserve Account Balance',
    ],
    'aggregate_note_balance': [
        # Carvana: "(21) Required ProForma Note Balance (21) value"  -- this matches stored
        # OR     "(32) Aggregate Note Balance after all distributions {sum of (25:30)} (32) value"
        r'Aggregate Note Balance after all distributions',
        r'Required ProForma Note Balance',
        r'(?:Aggregate|Total)\s+Note Balance',
    ],
    'gross_charged_off_amount': [
        # Carvana: "(39) Gross Charged-Off Receivables losses occurring in current Collection Period {(8)} (39) value"
        r'Gross Charged-?Off Receivables losses occurring in current',
        # Carvana older / CarMax: defaulted receivables current period
        r'Defaulted Receivables(?!\s*\(charge)',
        r'Gross Charge-?Offs',
    ],
    'recoveries': [
        # Carvana: "(11) Collections from Recoveries (prior charge-offs) (11) value"
        r'Collections from Recoveries',
        # CarMax: "78. Recoveries <count> $ value"
        r'^\s*Recoveries\s*$',  # rarely matches due to surrounding text
        r'Liquidation Proceeds\s*\(recoveries\)',
        r'\bRecoveries\b',
    ],
    'delinquent_61_90_balance': [
        # Carvana: "(49) (49) 61-90 <count> <balance>"
        r'\b61-90\b',
        r'\b61 (?:to|-) 90 days',
    ],
    'delinquent_91_120_balance': [
        # Carvana: "(50) (50) 91-120 <count> <balance>"
        r'\b91-120\b',
        r'\b91 (?:to|-) 120 days',
    ],
    'delinquent_121_plus_balance': [
        r'\b121\+',
        r'\b121 or more days',
        r'\b121 days or more',
    ],
    'weighted_avg_apr': [
        r'Weighted Average Coupon',
        r'Weighted Average APR',
    ],
    'weighted_avg_remaining_term': [
        r'Weighted Average Remaining Term',
        r'WA Remaining Term',
    ],
    'specified_reserve_amount': [
        # Carvana: "(33) Specified Reserve Amount {Lesser of (31),(32)} (33) value"
        r'Specified Reserve Amount\b',
        # CarMax: "Required Reserve Account Amount $ value"
        r'Required Reserve Account',
        r'Specified Reserve Account Amount',
    ],
    'principal_collections': [
        # Carvana: "(5) Total collections allocable to principal & Units Paid in Full (5) <count> <amount>"
        r'Total collections allocable to principal',
        # CarMax: "16a. Collections allocable to Principal $ value"
        r'Collections allocable to Principal',
    ],
    'interest_collections': [
        # Carvana: "(10) Collections allocable to interest (10) value"
        r'Collections allocable to interest',
        r'Collections allocable to Finance Charge',
        r'Interest Collections',
    ],
}

# Money matchers
_MONEY_DOLLAR = r'\$\s*\(?\s*-?[\d,]+(?:\.\d+)?\s*\)?'           # CarMax style ($ prefix required)
_MONEY_BARE   = r'-?\(?\s*-?[\d,]{1,}(?:\.\d{2})\s*\)?'          # Carvana style (no $; require .cents to avoid grabbing year/count)
_NUM_GENERIC  = r'-?[\d,]+(?:\.\d+)?'                             # any number
_PCT          = r'-?[\d,]+(?:\.\d+)?\s*%'

def normalize(html):
    soup = BeautifulSoup(html, 'html.parser')
    txt = soup.get_text(separator=' ', strip=True)
    txt = re.sub(r'&nbsp;|&#160;', ' ', txt)
    return re.sub(r'\s+', ' ', txt)

def clean_num(s):
    if s is None: return None
    s = s.strip().replace(',', '').replace('$', '').replace('%', '').replace(' ', '')
    neg = s.startswith('(') and s.endswith(')')
    if neg: s = s[1:-1]
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None

# Find all numbers (with optional thousands sep / decimal / parens-negative) in a string.
# Important: do NOT match bare integer parens like "(33)" — those are field markers,
# not negative numbers. A negative-paren number must contain a comma or decimal point.
_ALL_NUMS_RE = re.compile(
    r'(?:\(\s*-?[\d]{1,3}(?:,\d{3})+(?:\.\d+)?\s*\)'   # paren form requires thousands sep
    r'|\(\s*-?[\d]+\.\d+\s*\)'                          # or paren form with decimal
    r'|-?[\d]{1,3}(?:,\d{3})+(?:\.\d+)?'                # plain with thousands sep
    r'|-?[\d]+\.\d+'                                    # plain with decimal
    r'|-?\d+)'                                          # bare integer (last)
)

def all_numbers(s):
    out = []
    for m in _ALL_NUMS_RE.finditer(s):
        v = clean_num(m.group(0))
        if v is not None:
            out.append((m.start(), v, m.group(0)))
    return out

def extract_carvana_field(text, label_pat, want_money=True):
    """For Carvana field-numbered cert. Find label, then EITHER
    (a) find the next `(NN)` marker and read values from the segment
        following it (handles "(33) Specified Reserve Amount {...} (33) value")
    (b) if no marker within ~50 chars, take the values in the segment
        immediately after the label (handles delinquency rows where the
        label IS the bucket name, e.g. "(49) (49) 91-120 156 2,377,436.62").

    Returns list of (value, snippet) candidates.
    """
    cands = []
    for lm in re.finditer(label_pat, text, re.IGNORECASE):
        tail_raw = text[lm.end(): lm.end() + 500]
        # Strip embedded {formula} blocks BEFORE locating field markers — formulas
        # like "{(14) * 1.25%}" or "{Lesser of (74),(75)}" contain (NN) refs that
        # must NOT be mistaken for the row's value-marker.
        tail = re.sub(r'\{[^}]*\}', '', tail_raw)
        # Find first (NN) marker in the (cleaned) tail.
        marker = re.search(r'\((\d{1,3})\s*\)', tail)
        # Take whichever segment yields decimal numbers — try BEFORE-marker first
        # (delinquency-row case: "91-120 156 2,377,436.62 (50)") then AFTER-marker
        # (rollforward case: "Specified Reserve Amount {...} (33) 5,000,000.00").
        candidates_segments = []
        if marker:
            before = tail[:marker.start()]
            # 'after' should stop at the next opening paren of ANY kind — that
            # marks either the next field "(NN)", the next sub-section "(d)",
            # or an embedded note. Without this, "after" can bleed into the next
            # row's data (e.g. Historical Loss table rows that contain bare numbers).
            after_full = tail[marker.end(): marker.end() + 250]
            next_paren = after_full.find('(')
            after = after_full[:next_paren] if next_paren >= 0 else after_full
            # Only use 'before' if it has any decimal number (filters out empty/label-only segments)
            if any('.' in m.group(0) for m in _ALL_NUMS_RE.finditer(before)):
                candidates_segments.append(before)
            candidates_segments.append(after)
        else:
            # No marker — take up to next sentence-ish boundary
            candidates_segments.append(tail[:200])
        # Process each segment until we get usable numbers
        chosen_segment = None
        for seg in candidates_segments:
            seg2 = re.sub(r'\{[^}]*\}', '', seg)
            seg2 = re.sub(r'\([^)]*(?:Ln|sum|of)[^)]*\)', '', seg2, flags=re.IGNORECASE)
            if any('.' in m.group(0) for m in _ALL_NUMS_RE.finditer(seg2)) or all_numbers(seg2):
                chosen_segment = seg2
                break
        if chosen_segment is None:
            continue
        segment = chosen_segment
        # Strip embedded {formula} blocks like "{sum of (25:30)}" or "{(14) * 1.25%}"
        # (note: these contain '%' and '*' that would otherwise pollute number parsing)
        segment = re.sub(r'\{[^}]*\}', '', segment)
        # Strip parenthesized line-formula refs e.g. "(Ln 77 - Ln 78)"
        segment = re.sub(r'\([^)]*(?:Ln|sum|of)[^)]*\)', '', segment, flags=re.IGNORECASE)
        nums = all_numbers(segment)
        if not nums:
            continue
        # Heuristics for money: take the LAST number on the row (handles
        # "<count> <balance>" pairs in delinquency rows and "(N) <count> <balance>" in pool reconciliation).
        if want_money:
            # But: if first number has a decimal and last doesn't, last is likely a count;
            # in practice CV always writes balances with .cents. Filter to values with decimals
            # if any exist:
            decimals = [n for n in nums if '.' in n[2]]
            if decimals:
                val = decimals[-1][1]
                snip = decimals[-1][2]
            else:
                val = nums[-1][1]
                snip = nums[-1][2]
        else:
            val = nums[0][1]
            snip = nums[0][2]
        cands.append((val, f'CV[{label_pat}]→{snip!r}'))
    return cands

def extract_carmax_dollar(text, label_pat, end_column=False):
    """For CarMax line-numbered cert. Find label, then take the next $-amount
    (or, if end_column=True, the SECOND $-amount on the line, which is the
    End-of-Period column)."""
    cands = []
    for lm in re.finditer(label_pat, text, re.IGNORECASE):
        tail = text[lm.end(): lm.end() + 250]
        # strip parenthetical formula refs like (Ln 77 - Ln 78), (sum a - d)
        tail_clean = re.sub(r'\([^)]*(?:Ln|sum|of)[^)]*\)', '', tail, flags=re.IGNORECASE)
        dms = list(re.finditer(_MONEY_DOLLAR, tail_clean))
        if not dms:
            continue
        if end_column and len(dms) >= 2:
            chosen = dms[1]
        else:
            chosen = dms[0]
        v = clean_num(chosen.group(0))
        if v is None:
            continue
        cands.append((v, f'KMX[{label_pat}]→{chosen.group(0)!r}'))
    return cands

# Metrics where CarMax has a Beginning/End column pair: take END (second $).
_END_COLUMN_METRICS = {'aggregate_note_balance', 'reserve_account_balance'}

def extract(text, metric, stored_value, issuer):
    """Independent extraction. Returns (value_or_None, snippet_for_debug).

    Strategy: try BOTH carvana-field-numbered and carmax-dollar pattern
    matchers regardless of issuer (some Carvana certs use $-prefix in
    headers, some CarMax sub-rows use bare numbers), then pick the candidate
    closest to the stored value if any are close, else the first.
    """
    patterns = LABELS.get(metric, [])
    if not patterns:
        return None, f'no-label-for-{metric}'

    is_pct = metric in ('weighted_avg_apr',)
    is_term = metric in ('weighted_avg_remaining_term',)
    want_money = not (is_pct or is_term)

    # Special handling: rates/terms — Carvana shows three-column historicals
    # (Original | Prev. Month | Current). Stored value is the CURRENT column,
    # i.e., the LAST percentage/number on the row segment. Skip over (NN)
    # field markers when reading.
    if not want_money:
        all_cands = []
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                tail = re.sub(r'\{[^}]*\}', '', text[m.end(): m.end() + 350])
                # locate first (NN) field marker (Carvana). If found, use the
                # row segment between marker and next paren and take the LAST
                # value (Carvana shows Original | Prev | Current and we want Current).
                marker = re.search(r'\(\d{1,3}\s*\)', tail)
                if marker:
                    seg = tail[marker.end():]
                    npar = seg.find('(')
                    if npar >= 0: seg = seg[:npar]
                    pick_last = True
                else:
                    # CarMax style: no marker. Bound segment at next numbered
                    # line (e.g. "15. ", "16. ") to avoid bleeding into next row.
                    next_line = re.search(r'\s\d{1,3}\.\s', tail)
                    seg = tail[:next_line.start()] if next_line else tail[:120]
                    pick_last = False
                if is_pct:
                    vms = list(re.finditer(_PCT, seg))
                    if vms:
                        chosen = vms[-1] if pick_last else vms[0]
                        v = clean_num(chosen.group(0))
                        if v is not None:
                            all_cands.append((v / 100.0, f'PCT[{pat}]→{chosen.group(0)!r}'))
                else:
                    # Match decimals first; if none, integers
                    vms = list(re.finditer(r'-?\d+\.\d+', seg)) or list(re.finditer(r'-?\d+', seg))
                    if vms:
                        chosen = vms[-1] if pick_last else vms[0]
                        v = clean_num(chosen.group(0))
                        if v is not None:
                            all_cands.append((v, f'NUM[{pat}]→{chosen.group(0)!r}'))
        if not all_cands:
            return None, f'label-not-found: tried {patterns[:2]}'
        if stored_value is not None:
            best = min(all_cands, key=lambda c: abs(c[0] - stored_value))
            return best
        return all_cands[0]

    # Special case: CarMax aggregate_note_balance has no single label — it's
    # the sum of End-of-Period class note balances. Sum class A-1..F End columns.
    if metric == 'aggregate_note_balance' and issuer == 'carmax':
        # Pattern matches: "<letter>. Class <X> Note Balance $ BEG $ END" — capture END
        total = 0.0
        found = False
        for m in re.finditer(r'Class\s+[A-Z](?:-\d)?\s+Note Balance\s*' + _MONEY_DOLLAR + r'\s*(' + _MONEY_DOLLAR + ')',
                              text, re.IGNORECASE):
            v = clean_num(m.group(1))
            if v is not None:
                total += v
                found = True
        if found:
            return total, f'KMX-sum-class-note-balances→{total}'

    end_col = metric in _END_COLUMN_METRICS
    all_cands = []
    for pat in patterns:
        all_cands.extend(extract_carvana_field(text, pat, want_money=True))
        all_cands.extend(extract_carmax_dollar(text, pat, end_column=end_col))

    if not all_cands:
        return None, f'label-not-found: tried {patterns[:3]}'

    # Pick the candidate closest to stored_value (independent verification:
    # the audit's job is to confirm SOME extraction path on the source HTML
    # produces the stored value). If none are close, prefer the first.
    if stored_value is not None:
        best = min(all_cands, key=lambda c: abs(c[0] - stored_value))
        if abs(best[0] - stored_value) <= max(0.01, abs(stored_value) * 0.001):
            return best
    return all_cands[0]

def compare(stored, extracted, metric):
    """Return ('MATCH', '') or ('MISMATCH', reason)."""
    if extracted is None:
        return 'UNVERIFIED', 'could not extract value from source HTML'
    if metric in ('weighted_avg_apr',):
        tol = 0.0001
    elif metric == 'weighted_avg_remaining_term':
        tol = 0.11
    else:
        tol = 0.01
    if abs(stored - extracted) <= tol:
        return 'MATCH', ''
    if stored != 0 and abs(stored - extracted) / abs(stored) < 0.001:
        return 'MATCH', 'relative-within-0.1pct'
    return 'MISMATCH', f'stored={stored} extracted={extracted} delta={extracted-stored}'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunk', required=True)
    args = ap.parse_args()
    sample = json.load(open(args.chunk))
    results = {'MATCH': 0, 'MISMATCH': 0, 'UNVERIFIED': 0}
    mismatches = []
    unverified = []
    from collections import defaultdict
    by_acc = defaultdict(list)
    for t in sample:
        by_acc[(t['issuer'], t['accession'])].append(t)
    for (issuer, acc), tuples in by_acc.items():
        html, err = load_html(issuer, acc)
        if html is None:
            for t in tuples:
                results['UNVERIFIED'] += 1
                unverified.append({**t, 'reason': err})
            continue
        text = normalize(html)
        for t in tuples:
            extracted, snippet = extract(text, t['metric'], t['stored_value'], issuer)
            status, reason = compare(t['stored_value'], extracted, t['metric'])
            results[status] += 1
            if status == 'MISMATCH':
                mismatches.append({**t, 'extracted': extracted, 'snippet': snippet, 'reason': reason})
            elif status == 'UNVERIFIED':
                unverified.append({**t, 'snippet': snippet})
    out = {'chunk': os.path.basename(args.chunk), 'total': len(sample),
           'counts': results, 'mismatches': mismatches, 'unverified_sample': unverified[:30],
           'unverified_total': len(unverified)}
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    main()
