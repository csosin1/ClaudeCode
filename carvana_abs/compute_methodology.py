"""Compute all derived analytics for the Methodology & Findings tab.

Writes a single JSON cache at deploy/methodology_cache/analytics.json. The
dashboard generator reads from the cache so regeneration stays fast.

Scope (one-shot computation, not per-deal):
  1. Coverage table (issuer x vintage x loan count x loan_performance recency)
  2. Transition-matrix examples for 4 representative cells (streamed)
  3. Default-hazard by age curve (streamed, per tier)
  4. Cure rates by delinquency state (streamed)
  5. Modification-impact table (streamed)
  6. Predictor associations (monthly default rate by FICO / LTV / term bucket)
  7. Hierarchical-ish logistic regression: monthly-default model with issuer
     dummy, FICO/LTV/term/age buckets, vintage-year FE, delinquency-state FE.
     Sampled to <= 3M loan-months; reports coefficient + 95% CI.
  8. Matched-cell consumer WAC comparison (at-origination, prime only)
  9. Cost-of-funds time series (per deal, using deal_terms)
 10. Residual-profit worked example numbers (pulled from LAST_MODEL_RESULTS
     and deal_terms for two sample deals).

Hard constraint: peak RSS < 1.5 GB. Nothing loads full loan_performance at once.
"""
from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('methodology')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRVNA_DB = os.path.join(REPO, 'carvana_abs', 'db', 'carvana_abs.db')
CARMX_DB = os.path.join(REPO, 'carmax_abs', 'db', 'carmax_abs.db')
CRVNA_DASH = os.path.join(REPO, 'carvana_abs', 'db', 'dashboard.db')
CARMX_DASH = os.path.join(REPO, 'carmax_abs', 'db', 'dashboard.db')
OUT = os.path.join(REPO, 'deploy', 'methodology_cache', 'analytics.json')

random.seed(42)
np.random.seed(42)

# --- bucket definitions (match unified_markov where possible) -------------
FICO_EDGES = [(0, 580, '<580'), (580, 620, '580-619'), (620, 660, '620-659'),
              (660, 700, '660-699'), (700, 740, '700-739'), (740, 999, '740+')]
LTV_EDGES = [(0, 80, '<80%'), (80, 100, '80-99%'), (100, 120, '100-119%'),
             (120, 9999, '120%+')]
TERM_EDGES = [(0, 49, '<=48mo'), (49, 61, '49-60mo'), (61, 73, '61-72mo'),
              (73, 999, '73+mo')]
AGE_EDGES = [(0, 7, '0-6'), (7, 13, '7-12'), (13, 25, '13-24'),
             (25, 37, '25-36'), (37, 9999, '37+')]


def _bucket(value, edges):
    if value is None:
        return None
    for lo, hi, label in edges:
        if lo <= value < hi:
            return label
    return None


def _days_to_state(days):
    """Map days-delinquent to Markov state label."""
    if days is None:
        return None
    if days < 30:
        return 'Current'
    if days < 60:
        return '1pmt'
    if days < 90:
        return '2pmt'
    if days < 120:
        return '3pmt'
    if days < 150:
        return '4pmt'
    return '5+pmt'


def _tier_for_deal(deal):
    """'P' suffix = Prime, 'N' suffix = Non-Prime. All CarMax deals treated as Prime."""
    if '-N' in deal:
        return 'Non-Prime'
    return 'Prime'


# ==========================================================================
# 1. Coverage table
# ==========================================================================
def coverage_table():
    out = []
    for label, path in [('Carvana', CRVNA_DB), ('CarMax', CARMX_DB)]:
        conn = sqlite3.connect(path)
        rows = conn.execute('''
            SELECT l.deal,
                   COUNT(*) AS loan_cnt,
                   MIN(l.origination_date) AS min_orig,
                   MAX(l.origination_date) AS max_orig,
                   AVG(l.obligor_credit_score) AS avg_fico,
                   AVG(l.original_ltv) AS avg_ltv,
                   AVG(l.original_interest_rate) AS avg_apr
            FROM loans l GROUP BY l.deal ORDER BY l.deal
        ''').fetchall()
        # loan_performance recency
        recency = dict(conn.execute('''
            SELECT deal, MAX(reporting_period_end) FROM loan_performance GROUP BY deal
        ''').fetchall())
        # deal_terms cutoff
        terms = dict(conn.execute('SELECT deal, cutoff_date FROM deal_terms').fetchall())
        for r in rows:
            deal, cnt, mino, maxo, fico, ltv, apr = r
            out.append({
                'issuer': label,
                'deal': deal,
                'tier': _tier_for_deal(deal),
                'cutoff_date': terms.get(deal),
                'loan_count': cnt,
                'avg_fico': round(fico, 1) if fico else None,
                'avg_ltv': round(ltv, 2) if ltv else None,
                'avg_apr_pct': round(apr * 100, 2) if apr and apr < 1.0 else round(apr, 2) if apr else None,
                'loan_perf_latest': recency.get(deal),
            })
        conn.close()
    return out


# ==========================================================================
# 2. Streamed per-cell transition counts and related aggregates
# ==========================================================================
def _load_loan_attrs(conn):
    """Return dict: (deal, asset_number) -> (fico_band, ltv_band, term_band, orig_apr_pct, original_amount)."""
    out = {}
    for row in conn.execute('''
        SELECT deal, asset_number, obligor_credit_score, original_ltv,
               original_loan_term, original_interest_rate, original_loan_amount
        FROM loans
    '''):
        deal, asset, fico, ltv, term, apr, amt = row
        if apr is not None and apr > 1.0:
            apr_pct = apr  # stored as percentage
        elif apr is not None:
            apr_pct = apr * 100.0
        else:
            apr_pct = None
        fb = _bucket(fico, FICO_EDGES)
        lb = _bucket(ltv, LTV_EDGES)
        tb = _bucket(term, TERM_EDGES)
        out[(deal, asset)] = (fb, lb, tb, apr_pct, amt, fico, ltv, term)
    return out


def _stream_loanperf(conn, order_by_asset=True):
    """Stream (deal, asset, rpe, days, remaining_term, zbcode, modind) rows.

    Sorted by (deal, asset, reporting_period_end) so we can detect transitions
    by comparing consecutive rows per-loan.
    """
    q = '''
        SELECT deal, asset_number, reporting_period_end, days_delinquent,
               remaining_term, zero_balance_code, modification_indicator,
               charged_off_amount, beginning_balance
        FROM loan_performance
    '''
    if order_by_asset:
        q += ' ORDER BY deal, asset_number, reporting_period_end'
    cur = conn.cursor()
    cur.arraysize = 10000
    cur.execute(q)
    return cur


def streamed_aggregates(sample_loans_per_deal=2000, sample_months_per_loan=None):
    """Walk loan_performance once per DB, accumulating:
       - transition-count table per (issuer, cell_key, from_state) -> {to_state: count}
       - age-bucket default rate per tier
       - cure-rate counts per delinquency state per tier
       - modification-impact counts (mod vs non-mod at comparable states)
       - regression sample (loan-months with covariates + default-next flag)

    Returns dict of all these.
    """
    # Representative cells we care about for the heatmap
    REP_CELLS = [
        ('700-739', '80-99%', '13-24'),   # prime sweet-spot
        ('620-659', '100-119%', '13-24'), # near-prime underwater
        ('580-619', '120%+',   '13-24'),  # subprime deep underwater
        ('740+',    '<80%',    '13-24'),  # super-prime equity
    ]
    rep_cells_set = set(REP_CELLS)

    # transition_counts: (issuer, fico_b, ltv_b, term_b, age_b, from_state) -> Counter(to_state)
    trans = defaultdict(lambda: defaultdict(int))
    # hazard_by_age: (issuer, tier, age_b) -> [default_events, months_exposed]
    hazard = defaultdict(lambda: [0, 0])
    # cure_by_state: (issuer, tier, from_state) -> {cured_to_current_3m: x, total: y}
    cure = defaultdict(lambda: {'cured': 0, 'total': 0})
    # modification impact: (issuer, tier, modified_bool) -> {def_events, exposed}
    mod_impact = defaultdict(lambda: [0, 0])
    # predictor-association aggregates: (issuer, tier, dim, bucket) -> [def, exposed]
    pred = defaultdict(lambda: [0, 0])
    # fico x ltv table @ age 13-24: (issuer, fico_b, ltv_b) -> [def, exposed]
    fico_ltv_grid = defaultdict(lambda: [0, 0])

    # Regression sample: list of dicts (we'll trim to cap rows)
    reg_sample = []
    REG_CAP = 3_000_000  # loan-months total (2 issuers combined; we'll undersample as we go)
    KEEP_PROB_BASE = {'Carvana': 1.0, 'CarMax': 1.0}  # may downsample CarMax later

    for issuer_label, db_path in [('Carvana', CRVNA_DB), ('CarMax', CARMX_DB)]:
        logger.info(f'Streaming {issuer_label} ...')
        conn = sqlite3.connect(db_path)
        conn.row_factory = None

        logger.info(f'  loading loan attrs...')
        attrs = _load_loan_attrs(conn)
        logger.info(f'  {len(attrs)} loan attrs')

        # Determine approximate keep-prob so we get ~1.5M loan-months per issuer
        total_lp = conn.execute('SELECT COUNT(*) FROM loan_performance').fetchone()[0]
        target = 1_500_000
        keep_prob = min(1.0, target / max(total_lp, 1))
        logger.info(f'  loan_perf rows ~= {total_lp:,}, keep_prob = {keep_prob:.4f}')

        # Deal -> cutoff_date (for vintage-year in regression)
        dealcut = dict(conn.execute('SELECT deal, cutoff_date FROM deal_terms').fetchall())

        # Stream ordered by (deal, asset, rpe) so we can track prev-state
        cur = _stream_loanperf(conn)
        last_key = None
        last_state = None
        last_days = None
        last_rpe = None
        states_seen_curr = []  # for cure: rolling 3-month after a delinquency
        n_rows = 0
        n_kept = 0
        t0 = time.time()

        rng = random.Random(hash(issuer_label) & 0xFFFFFFFF)

        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for row in batch:
                deal, asset, rpe, days, rem_term, zbcode, modind, chargeoff, beg_bal = row
                n_rows += 1
                key = (deal, asset)
                a = attrs.get(key)
                if a is None:
                    last_key = key; last_state = None; last_days = days; last_rpe = rpe
                    continue
                fb, lb, tb, apr, amt, fico, ltv, term = a
                tier = _tier_for_deal(deal)

                # Compute current state
                state = _days_to_state(days)
                defaulted = (zbcode == '03' or (chargeoff is not None and chargeoff > 0))
                paid_off = (zbcode in ('01', '02') and not defaulted)
                modified = (modind == 'Y' or modind == '1' or modind == 'true')

                # age_months: inferred from (original_term - remaining_term) when possible
                age_months = None
                if term and rem_term is not None:
                    age_months = max(0, term - rem_term)
                age_b = _bucket(age_months, AGE_EDGES)

                # ---- Transition counting (needs prev state same loan) ----
                if last_key == key and last_state is not None and age_b is not None:
                    # Only store for the 4 rep cells
                    cell = (fb, lb, age_b)
                    if cell in rep_cells_set:
                        to_state = state if not defaulted else 'Default'
                        if paid_off:
                            to_state = 'Payoff'
                        if to_state:
                            trans[(issuer_label, fb, lb, tb, age_b, last_state)][to_state] += 1

                # ---- Hazard by age ----
                if age_b is not None and last_key == key and last_state is not None:
                    hazard[(issuer_label, tier, age_b)][1] += 1  # months exposed
                    if defaulted:
                        hazard[(issuer_label, tier, age_b)][0] += 1

                # ---- Cure rate: "from state X, reached Current within 3 months" ----
                # We do a simpler approximation: at each delinquent-state observation,
                # record whether the SAME loan is in Current state 3 observations later.
                # Implementation below in regression pass is too memory-heavy; instead,
                # we do one-month cure: from state X, did it immediately return to
                # Current at next observation? Still informative.
                if last_key == key and last_state is not None and last_state != 'Current':
                    cure[(issuer_label, tier, last_state)]['total'] += 1
                    if state == 'Current':
                        cure[(issuer_label, tier, last_state)]['cured'] += 1

                # ---- Modification impact ----
                if last_key == key and last_state is not None and age_b is not None:
                    mod_impact[(issuer_label, tier, bool(modified))][1] += 1
                    if defaulted:
                        mod_impact[(issuer_label, tier, bool(modified))][0] += 1

                # ---- Predictor associations ----
                if last_key == key and last_state is not None:
                    # per-issuer,tier,FICO
                    if fb:
                        pred[(issuer_label, tier, 'fico', fb)][1] += 1
                        if defaulted:
                            pred[(issuer_label, tier, 'fico', fb)][0] += 1
                    if lb:
                        pred[(issuer_label, tier, 'ltv', lb)][1] += 1
                        if defaulted:
                            pred[(issuer_label, tier, 'ltv', lb)][0] += 1
                    if tb:
                        pred[(issuer_label, tier, 'term', tb)][1] += 1
                        if defaulted:
                            pred[(issuer_label, tier, 'term', tb)][0] += 1
                    if age_b:
                        pred[(issuer_label, tier, 'age', age_b)][1] += 1
                        if defaulted:
                            pred[(issuer_label, tier, 'age', age_b)][0] += 1
                    # fico x ltv grid @ age 13-24
                    if fb and lb and age_b == '13-24':
                        fico_ltv_grid[(issuer_label, fb, lb)][1] += 1
                        if defaulted:
                            fico_ltv_grid[(issuer_label, fb, lb)][0] += 1

                # ---- Regression sample (Prime only for issuer comparison) ----
                if (tier == 'Prime' and last_key == key and last_state is not None
                        and age_b is not None and fb and lb and tb
                        and not paid_off and rng.random() < keep_prob):
                    vintage = None
                    cd = dealcut.get(deal)
                    if cd and len(cd) >= 4:
                        try:
                            vintage = int(cd[:4])
                        except Exception:
                            vintage = None
                    reg_sample.append({
                        'issuer': issuer_label,
                        'fb': fb, 'lb': lb, 'tb': tb, 'age_b': age_b,
                        'from_state': last_state,
                        'modified': 1 if modified else 0,
                        'vintage': vintage,
                        'default_next': 1 if defaulted else 0,
                        'deal': deal,
                    })
                    n_kept += 1

                # Move window
                if last_key == key:
                    last_state = state
                else:
                    last_state = state
                last_key = key
                last_days = days
                last_rpe = rpe

                if n_rows % 2_000_000 == 0:
                    logger.info(f'  {issuer_label}: {n_rows:,} rows ({time.time()-t0:.0f}s), {n_kept:,} kept for reg, trans cells = {len(trans)}')

        cur.close()
        conn.close()
        logger.info(f'  {issuer_label} DONE: {n_rows:,} rows in {time.time()-t0:.0f}s')

    # Convert the nested defaultdicts to plain dicts for JSON
    trans_out = {}
    for k, v in trans.items():
        trans_out['|'.join(str(x) for x in k)] = dict(v)
    hazard_out = {
        '|'.join(str(x) for x in k): {'default_events': v[0], 'months_exposed': v[1]}
        for k, v in hazard.items()
    }
    cure_out = {
        '|'.join(str(x) for x in k): dict(v) for k, v in cure.items()
    }
    mod_out = {
        '|'.join([k[0], k[1], 'mod' if k[2] else 'nomod']):
        {'default_events': v[0], 'months_exposed': v[1]}
        for k, v in mod_impact.items()
    }
    pred_out = {
        '|'.join(str(x) for x in k):
        {'default_events': v[0], 'months_exposed': v[1]}
        for k, v in pred.items()
    }
    grid_out = {
        '|'.join(str(x) for x in k):
        {'default_events': v[0], 'months_exposed': v[1]}
        for k, v in fico_ltv_grid.items()
    }

    return {
        'transitions': trans_out,
        'hazard_by_age': hazard_out,
        'cure_by_state': cure_out,
        'mod_impact': mod_out,
        'predictor_assoc': pred_out,
        'fico_ltv_grid': grid_out,
        'reg_sample': reg_sample,  # list of dicts
    }


# ==========================================================================
# 3. Regression: logistic with issuer dummy + controls
# ==========================================================================
def run_regression(reg_sample):
    import statsmodels.api as sm
    import pandas as pd
    df = pd.DataFrame(reg_sample)
    logger.info(f'Regression input: {len(df):,} loan-months')
    if len(df) == 0:
        return None
    # Exclude loans without vintage year (rare)
    df = df.dropna(subset=['vintage'])
    df['vintage'] = df['vintage'].astype(int)
    # Build design matrix
    df['issuer_carmax'] = (df['issuer'] == 'CarMax').astype(int)
    # Categorical dummies
    X_list = [df['issuer_carmax']]
    drop_firsts = {'fb': '660-699', 'lb': '80-99%', 'tb': '61-72mo',
                   'age_b': '13-24', 'from_state': 'Current'}
    for col, drop in drop_firsts.items():
        dummies = pd.get_dummies(df[col], prefix=col, drop_first=False, dtype=int)
        if f'{col}_{drop}' in dummies.columns:
            dummies = dummies.drop(columns=[f'{col}_{drop}'])
        else:
            # drop first column alphabetically as fallback
            dummies = dummies.iloc[:, 1:]
        X_list.append(dummies)
    # modification
    X_list.append(df[['modified']])
    # vintage as categorical
    vintage_dummies = pd.get_dummies(df['vintage'], prefix='v', drop_first=True, dtype=int)
    X_list.append(vintage_dummies)
    X = pd.concat(X_list, axis=1).astype(float)
    X = sm.add_constant(X, has_constant='add')
    y = df['default_next'].astype(int).values

    logger.info(f'Fitting logit: n={len(df):,}, p={X.shape[1]}, default rate={y.mean():.4f}')
    # statsmodels Logit can be slow on large X; use regularized=False for SE
    # To keep memory sane, downsample to 600k rows with stratification on y
    if len(df) > 600_000:
        pos = np.where(y == 1)[0]
        neg = np.where(y == 0)[0]
        # keep all positives, sample negatives down
        target_neg = min(len(neg), 600_000 - len(pos))
        rng = np.random.default_rng(42)
        neg_keep = rng.choice(neg, size=target_neg, replace=False)
        keep = np.concatenate([pos, neg_keep])
        X_fit = X.iloc[keep].values
        y_fit = y[keep]
        # Compute offset to correct for undersampling: weights restore population balance
        # We use case-control-style weighting post-hoc on the intercept.
        sampling_ratio = len(neg_keep) / len(neg)
        logger.info(f'  stratified sample: {len(keep):,} rows (pos={len(pos)}, neg_keep={len(neg_keep)}); neg sampling ratio={sampling_ratio:.4f}')
    else:
        X_fit = X.values
        y_fit = y
        sampling_ratio = 1.0

    model = sm.Logit(y_fit, X_fit)
    try:
        res = model.fit(disp=False, maxiter=100, method='lbfgs')
    except Exception as e:
        logger.warning(f'lbfgs failed: {e}, trying newton')
        res = model.fit(disp=False, maxiter=200, method='newton')

    # Convert back to a {name: {coef, se, ci_lo, ci_hi, p}} dict
    names = list(X.columns)
    coefs = res.params
    ses = res.bse
    ci = res.conf_int(alpha=0.05)
    pvals = res.pvalues
    coef_table = []
    for i, nm in enumerate(names):
        coef_table.append({
            'name': nm,
            'coef': float(coefs[i]),
            'se': float(ses[i]),
            'ci_lo': float(ci[i, 0]),
            'ci_hi': float(ci[i, 1]),
            'p': float(pvals[i]),
        })

    # Key summary: issuer_carmax
    idx_issuer = names.index('issuer_carmax')
    issuer_coef = float(coefs[idx_issuer])
    issuer_se = float(ses[idx_issuer])
    issuer_ci_lo = float(ci[idx_issuer, 0])
    issuer_ci_hi = float(ci[idx_issuer, 1])

    # Marginal effect at sample means (in population terms):
    # corrected intercept = intercept + log(sampling_ratio) since we undersampled negatives
    # The marginal default prob at mean X with issuer=0 vs issuer=1:
    X_means = X.mean(axis=0).values
    # adjust intercept for sampling
    def _prob(x_row, corr):
        z = float(np.dot(x_row, res.params)) + corr
        return 1.0 / (1.0 + np.exp(-z))
    corr = np.log(sampling_ratio) if sampling_ratio < 1.0 else 0.0
    x0 = X_means.copy(); x0[names.index('issuer_carmax')] = 0.0
    x1 = X_means.copy(); x1[names.index('issuer_carmax')] = 1.0
    p0 = _prob(x0, corr)
    p1 = _prob(x1, corr)
    marginal_diff_monthly = p1 - p0

    return {
        'n_fit': int(len(y_fit)),
        'n_sample': int(len(y)),
        'n_positive': int(y.sum()),
        'default_rate_fit': float(y_fit.mean()),
        'default_rate_sample': float(y.mean()),
        'sampling_ratio_neg': float(sampling_ratio),
        'pseudo_r2_mcfadden': float(res.prsquared),
        'log_likelihood': float(res.llf),
        'llnull': float(res.llnull),
        'converged': bool(res.mle_retvals.get('converged', True)),
        'coefficients': coef_table,
        'issuer_effect': {
            'coef': issuer_coef,
            'se': issuer_se,
            'ci_lo': issuer_ci_lo,
            'ci_hi': issuer_ci_hi,
            'odds_ratio': float(np.exp(issuer_coef)),
            'odds_ratio_ci_lo': float(np.exp(issuer_ci_lo)),
            'odds_ratio_ci_hi': float(np.exp(issuer_ci_hi)),
            'marginal_prob_carvana': float(p0),
            'marginal_prob_carmax': float(p1),
            'marginal_diff_monthly_bps': float(marginal_diff_monthly * 10000),
        },
        # issuer effect by vintage (refit separately for each year)
        'by_vintage': _issuer_by_vintage(df),
    }


def _issuer_by_vintage(df):
    import statsmodels.api as sm
    import pandas as pd
    out = []
    for v in sorted(df['vintage'].dropna().unique().tolist()):
        sub = df[df['vintage'] == v]
        if len(sub) < 10000 or sub['issuer'].nunique() < 2:
            continue
        # Simple logit with just issuer + fb + lb + tb + age_b + from_state
        sub = sub.copy()
        sub['issuer_carmax'] = (sub['issuer'] == 'CarMax').astype(int)
        Xl = [sub[['issuer_carmax']]]
        for col, drop in [('fb','660-699'),('lb','80-99%'),('tb','61-72mo'),('age_b','13-24'),('from_state','Current')]:
            dum = pd.get_dummies(sub[col], prefix=col, dtype=int)
            if f'{col}_{drop}' in dum.columns:
                dum = dum.drop(columns=[f'{col}_{drop}'])
            else:
                dum = dum.iloc[:, 1:]
            Xl.append(dum)
        X = pd.concat(Xl, axis=1).astype(float)
        X = sm.add_constant(X, has_constant='add')
        y = sub['default_next'].astype(int).values
        if y.sum() < 50:
            continue
        # downsample negatives if huge
        if len(y) > 300_000:
            pos = np.where(y == 1)[0]
            neg = np.where(y == 0)[0]
            keep_neg = np.random.default_rng(int(v)).choice(neg, size=min(len(neg), 300_000 - len(pos)), replace=False)
            keep = np.concatenate([pos, keep_neg])
            X_fit = X.iloc[keep].values
            y_fit = y[keep]
        else:
            X_fit = X.values
            y_fit = y
        try:
            res = sm.Logit(y_fit, X_fit).fit(disp=False, maxiter=60, method='lbfgs')
            names = list(X.columns)
            idx = names.index('issuer_carmax')
            coef = float(res.params[idx])
            se = float(res.bse[idx])
            ci = res.conf_int(alpha=0.05)
            out.append({
                'vintage': int(v),
                'n': int(len(y_fit)),
                'coef': coef, 'se': se,
                'ci_lo': float(ci[idx, 0]), 'ci_hi': float(ci[idx, 1]),
                'odds_ratio': float(np.exp(coef)),
            })
        except Exception as e:
            logger.warning(f'  vintage {v} fit failed: {e}')
    return out


# ==========================================================================
# 4. Consumer-WAC matched-cell comparison (at origination)
# ==========================================================================
def consumer_wac_comparison():
    """Per (FICO band x LTV band x term band) cell, compute loan-weighted
    avg consumer APR for each issuer (prime only). Report weighted
    aggregate difference (CarMax - Carvana)."""
    cells = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # cell -> issuer -> [apr_sum_wtd, amt_sum]
    for issuer, path in [('Carvana', CRVNA_DB), ('CarMax', CARMX_DB)]:
        conn = sqlite3.connect(path)
        # Only prime deals
        rows = conn.execute('''
            SELECT deal, obligor_credit_score, original_ltv, original_loan_term,
                   original_interest_rate, original_loan_amount
            FROM loans
            WHERE obligor_credit_score IS NOT NULL
              AND original_ltv IS NOT NULL
              AND original_loan_term IS NOT NULL
              AND original_interest_rate IS NOT NULL
              AND original_loan_amount IS NOT NULL
        ''').fetchall()
        conn.close()
        for deal, fico, ltv, term, apr, amt in rows:
            if _tier_for_deal(deal) != 'Prime':
                continue
            fb = _bucket(fico, FICO_EDGES)
            lb = _bucket(ltv, LTV_EDGES)
            tb = _bucket(term, TERM_EDGES)
            if not (fb and lb and tb):
                continue
            apr_pct = apr if apr > 1.0 else apr * 100
            cells[(fb, lb, tb)][issuer][0] += apr_pct * amt
            cells[(fb, lb, tb)][issuer][1] += amt

    matched = []
    for cell, iss in cells.items():
        if 'Carvana' not in iss or 'CarMax' not in iss:
            continue
        crv = iss['Carvana']
        cmx = iss['CarMax']
        if crv[1] < 1e6 or cmx[1] < 1e6:  # need at least $1M in each to matter
            continue
        crv_apr = crv[0] / crv[1]
        cmx_apr = cmx[0] / cmx[1]
        matched.append({
            'cell_fico': cell[0], 'cell_ltv': cell[1], 'cell_term': cell[2],
            'carvana_apr_pct': crv_apr,
            'carmax_apr_pct': cmx_apr,
            'diff_pct': cmx_apr - crv_apr,
            'carvana_orig_amt': crv[1],
            'carmax_orig_amt': cmx[1],
        })

    # Weighted aggregate by min(amount) so cells with more data in both issuers count more
    total_wt = sum(min(c['carvana_orig_amt'], c['carmax_orig_amt']) for c in matched)
    if total_wt > 0:
        wtd_diff = sum(c['diff_pct'] * min(c['carvana_orig_amt'], c['carmax_orig_amt']) for c in matched) / total_wt
    else:
        wtd_diff = None
    return {
        'cells': matched,
        'weighted_avg_diff_pct': wtd_diff,
        'n_cells_matched': len(matched),
    }


# ==========================================================================
# 5. Cost-of-funds time series
# ==========================================================================
def cost_of_funds():
    """Weighted-avg note coupon per deal + cutoff_date, joined with 2Y Treasury."""
    # Load DGS2 as dict: date_str -> yield
    dgs2 = {}
    fp = os.path.join(REPO, 'deploy', 'benchmark_cache', 'DGS2.csv')
    if os.path.exists(fp):
        with open(fp) as f:
            next(f)  # header
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 2 and parts[1] not in ('.', ''):
                    try:
                        dgs2[parts[0]] = float(parts[1])
                    except Exception:
                        pass

    def lookup_2y(date_str):
        if not date_str:
            return None
        d = date_str[:10]
        if d in dgs2:
            return dgs2[d]
        # walk back up to 10 days
        from datetime import date, timedelta
        try:
            y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
            dt = date(y, m, dd)
            for i in range(1, 10):
                chk = (dt - timedelta(days=i)).isoformat()
                if chk in dgs2:
                    return dgs2[chk]
        except Exception:
            return None
        return None

    deals = []
    for issuer, path in [('Carvana', CRVNA_DB), ('CarMax', CARMX_DB)]:
        conn = sqlite3.connect(path)
        rows = conn.execute('''
            SELECT deal, cutoff_date, closing_date, weighted_avg_coupon,
                   class_a1_pct, class_a1_coupon, class_a2_pct, class_a2_coupon,
                   class_a3_pct, class_a3_coupon, class_a4_pct, class_a4_coupon,
                   class_b_pct, class_b_coupon, class_c_pct, class_c_coupon,
                   class_d_pct, class_d_coupon, class_n_pct, class_n_coupon,
                   initial_pool_balance
            FROM deal_terms
            WHERE terms_extracted = 1
              AND cutoff_date IS NOT NULL
        ''').fetchall()
        conn.close()
        for r in rows:
            (deal, cutoff, closing, wac, *pairs, ipb) = r
            # pairs: a1_pct,a1_coupon, ... n_pct,n_coupon (8 classes)
            pct_coup = list(zip(pairs[0::2], pairs[1::2]))
            # Recompute wac if missing or suspicious
            total_pct = sum(p for p,c in pct_coup if p and c)
            wac_calc = None
            if total_pct > 0:
                wac_calc = sum((p or 0) * (c or 0) for p, c in pct_coup) / total_pct
            wac_final = wac_calc if wac_calc else wac
            if wac_final and wac_final > 1:
                # already % form
                pass
            elif wac_final:
                wac_final = wac_final * 100
            tres = lookup_2y(cutoff)
            spread = (wac_final - tres) if (wac_final is not None and tres is not None) else None
            deals.append({
                'issuer': issuer,
                'deal': deal,
                'tier': _tier_for_deal(deal),
                'cutoff_date': cutoff,
                'closing_date': closing,
                'note_wac_pct': round(wac_final, 3) if wac_final else None,
                'treasury_2y_pct': round(tres, 3) if tres else None,
                'spread_pct': round(spread, 3) if spread else None,
                'initial_pool_balance': ipb,
            })
    deals.sort(key=lambda x: x['cutoff_date'] or '9999')
    return deals


# ==========================================================================
# Main
# ==========================================================================
def main():
    t0 = time.time()
    logger.info('=== Methodology analytics build ===')
    out = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'parameters': {
            'min_cell_obs': 30,
            'sigma_prior': 0.30,
            'fico_edges': FICO_EDGES,
            'ltv_edges': LTV_EDGES,
            'term_edges': TERM_EDGES,
            'age_edges': AGE_EDGES,
        },
    }

    logger.info('Coverage table ...')
    out['coverage'] = coverage_table()
    logger.info(f'  {len(out["coverage"])} deals covered')

    logger.info('Consumer-WAC matched-cell comparison ...')
    out['consumer_wac_comparison'] = consumer_wac_comparison()
    logger.info(f'  matched cells = {out["consumer_wac_comparison"]["n_cells_matched"]}')

    logger.info('Cost-of-funds time series ...')
    out['cost_of_funds'] = cost_of_funds()
    logger.info(f'  {len(out["cost_of_funds"])} deals')

    logger.info('Streaming loan_performance (both issuers) ...')
    agg = streamed_aggregates()
    out['hazard_by_age'] = agg['hazard_by_age']
    out['cure_by_state'] = agg['cure_by_state']
    out['mod_impact'] = agg['mod_impact']
    out['predictor_assoc'] = agg['predictor_assoc']
    out['fico_ltv_grid'] = agg['fico_ltv_grid']
    out['transitions'] = agg['transitions']
    logger.info(f'  reg_sample size: {len(agg["reg_sample"]):,}')

    logger.info('Running hierarchical-ish logit ...')
    out['regression'] = run_regression(agg['reg_sample'])
    del agg  # free

    logger.info(f'Total compute time: {time.time()-t0:.0f}s')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, default=str)
    sz = os.path.getsize(OUT)
    logger.info(f'Wrote {OUT} ({sz/1024:.0f} KB)')


if __name__ == '__main__':
    main()
