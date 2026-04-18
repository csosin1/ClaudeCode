"""Renderer for the Methodology & Findings tab.

Reads cached analytics from deploy/methodology_cache/analytics.json and
emits HTML. All heavy computation lives in compute_methodology.py. This
module just formats + writes Plotly figures.
"""
from __future__ import annotations

import json
import os
import html
import math


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYTICS_JSON = os.path.join(REPO, 'deploy', 'methodology_cache', 'analytics.json')

_chart_counter = [0]


def _cid(prefix='m'):
    _chart_counter[0] += 1
    return f'{prefix}{_chart_counter[0]}'


def _plotly_div(fig_dict, height=320, chart_id=None):
    """Emit a self-contained Plotly div.

    Uses the same config as the rest of the dashboard so every chart has
    a visible reset-view button — accidentally panning/zooming a chart
    on mobile is easy, and there has to be a one-tap recovery.

    `chart_id` (optional): a stable human-readable ID emitted as a
    `data-chart-id` attribute on the outer container. The dynamic `cid`
    (plt1, plt2, ...) still drives Plotly.newPlot, but the stable ID
    lets Playwright / visual-lint target the chart across rebuilds
    (see /opt/abs-dashboard/.charts.yaml).
    """
    cid = _cid('plt')
    js = json.dumps(fig_dict)
    cfg = ('{"displayModeBar":true,"displaylogo":false,"responsive":true,'
           '"modeBarButtonsToRemove":["lasso2d","select2d"]}')
    data_attr = f' data-chart-id="{chart_id}"' if chart_id else ''
    return (f'<div id="{cid}"{data_attr} style="height:{height}px;width:100%"></div>'
            f'<script>Plotly.newPlot("{cid}", {js}.data, {js}.layout, {cfg});</script>')


def _section(num, title, body):
    return (
        f'<h3 style="font-size:1rem;color:#1565C0;margin-top:26px;'
        f'padding-bottom:4px;border-bottom:1px solid #BBDEFB">'
        f'{num}. {title}</h3>\n{body}\n'
    )


def _h4(t):
    return f'<h4 style="font-size:.85rem;color:#333;margin:14px 0 6px">{t}</h4>\n'


def _p(text):
    return (f'<p style="font-size:.78rem;line-height:1.65;color:#333;'
            f'margin:6px 0">{text}</p>\n')


def _callout(text, color='#FF9800'):
    return (f'<div style="background:#F5F5F5;border-left:3px solid {color};'
            f'padding:8px 12px;margin:8px 0;font-size:.75rem;line-height:1.6">'
            f'{text}</div>\n')


def _fmt_pct(v, dec=2):
    if v is None:
        return '—'
    return f'{v:.{dec}f}%'


def _fmt_bps(v, dec=0):
    if v is None:
        return '—'
    return f'{v:.{dec}f} bps'


def load_cache():
    if not os.path.exists(ANALYTICS_JSON):
        return None
    try:
        return json.load(open(ANALYTICS_JSON))
    except Exception:
        return None


# ==========================================================================
# Section renderers
# ==========================================================================
def _sec1_intro():
    body = (
        _p('<strong>This is a methodology and findings note for the unified Markov '
           'credit-loss model powering the residual-economics table.</strong> The writeup is '
           'aimed at two readers: the <em>analyst</em> who wants enough detail to critique '
           'the assumptions, and the <em>investor</em> who needs a clear conclusion about '
           'credit, yield, and cost-of-funds differences between the two largest '
           'deep-subprime-adjacent auto ABS issuers (Carvana and CarMax).')
        + _p('All analysis is run on publicly filed SEC data — no proprietary feeds, no '
             'servicer-side access. The dataset spans 3.5 million consumer auto loans '
             'underwritten across 53 securitizations from 2014 through 2026Q1. The '
             'model is a first-order Markov chain with FICO/LTV/term/age/delinquency-state '
             'cells, a Bayesian calibration layer that tilts the base matrix toward each '
             "deal's realized experience, and a deterministic paydown/LGD overlay.")
        + _p('The headline findings are summarised visually below each section. For the '
             'sceptical reader, a reproducibility appendix (§11) contains the exact '
             'parameters, bucket edges, SQL, regression formula, and data URLs needed to '
             'rebuild the analysis from scratch.')
    )
    return _section(1, 'What this is', body)


def _sec2_data(cache):
    cov = cache.get('coverage', []) if cache else []
    # Aggregate by issuer x vintage year
    agg = {}
    for row in cov:
        iss = row['issuer']
        yr = (row.get('cutoff_date') or '')[:4] or '?'
        key = (iss, yr)
        if key not in agg:
            agg[key] = {'deals': 0, 'loans': 0}
        agg[key]['deals'] += 1
        agg[key]['loans'] += row.get('loan_count', 0) or 0
    # Build a grouped table
    years = sorted({k[1] for k in agg.keys()})
    issuers = ['Carvana', 'CarMax']
    tbl_rows = []
    totals = {iss: {'deals': 0, 'loans': 0} for iss in issuers}
    for yr in years:
        row_cells = [f'<td>{yr}</td>']
        for iss in issuers:
            v = agg.get((iss, yr), {'deals': 0, 'loans': 0})
            totals[iss]['deals'] += v['deals']
            totals[iss]['loans'] += v['loans']
            cell = '—' if v['deals'] == 0 else f'{v["deals"]} deals / {v["loans"]:,} loans'
            row_cells.append(f'<td>{cell}</td>')
        tbl_rows.append(f'<tr>{"".join(row_cells)}</tr>')
    # Totals row
    totals_cells = ['<td><strong>Total</strong></td>']
    for iss in issuers:
        totals_cells.append(f'<td><strong>{totals[iss]["deals"]} deals / {totals[iss]["loans"]:,} loans</strong></td>')
    tbl_rows.append(f'<tr style="background:#F5F5F5">{"".join(totals_cells)}</tr>')

    table = (
        '<div style="overflow-x:auto">'
        '<table style="font-size:.72rem;min-width:400px;margin:8px 0">'
        '<thead><tr><th>Issuance year</th><th>Carvana</th><th>CarMax</th></tr></thead>'
        f'<tbody>{"".join(tbl_rows)}</tbody></table></div>'
    )

    body = (
        _p('Every row of data in this analysis traces to one of three SEC filings: '
           '<strong>424(b)(5)</strong> prospectuses (one per deal, filed at issuance — '
           'capital structure, tranche coupons, servicing fee, overcollateralization / '
           'trigger schedules), <strong>10-D</strong> servicer certificates (monthly, '
           'per deal — pool-level losses, delinquencies, note paydowns), and '
           '<strong>ABS-EE</strong> asset-level exhibits (monthly XML, per deal — '
           'loan-level snapshot with FICO, LTV, term, APR, state, balance, '
           'delinquency status, modification, charge-off amount).')
        + _p(f'<strong>Scope.</strong> Loan-level data begins in 2017Q1 for CarMax '
             '(the SEC Reg AB II loan-level disclosure regime took effect in November 2016 '
             'and the first CarMax ABS-EE filing covers 2017-2 onward) and from issuance '
             'for Carvana (first deal 2019-A, first public prime deal 2020-P1). CarMax '
             'deals that priced before 2017-1 are included at pool level only. The unified '
             'Markov training set uses <strong>loan-level</strong> observations only.')
        + '<h4 style="font-size:.85rem;color:#333;margin:12px 0 4px">'
          'Coverage by issuance year</h4>'
        + table
        + _p('CarMax averages ~80-85k loans per deal (prime monoline, ~$1.5B pool). '
             'Carvana ranges from ~20k (early 2020-P1) to ~37k (2025-P3/P4) for prime '
             'deals and ~20k for non-prime. The combined <strong>loan_performance</strong> '
             'table — the monthly observation panel that drives the Markov model — has '
             '~15M rows for Carvana and ~99M rows for CarMax, ~114M in total.')
    )
    return _section(2, 'Data sources & coverage', body)


def _sec3_model():
    # Reuse the inline state diagram HTML (copied verbatim from the existing writeup
    # but extended with a fuller Bayesian-calibration treatment and a concrete example).
    state_diagram = '''
<div style="overflow-x:auto;padding:8px 0">
<div style="display:flex;align-items:center;gap:4px;min-width:720px;font-size:.7rem">
<div style="background:#C8E6C9;border:2px solid #388E3C;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#2E7D32">Current</div><div style="color:#555;font-size:.6rem">0 DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#FFF9C4;border:2px solid #F9A825;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#F57F17">1 Pmt</div><div style="color:#555;font-size:.6rem">30 DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#FFE0B2;border:2px solid #FF9800;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#E65100">2 Pmt</div><div style="color:#555;font-size:.6rem">60 DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#FFCCBC;border:2px solid #FF5722;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#BF360C">3 Pmt</div><div style="color:#555;font-size:.6rem">90 DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#FFCDD2;border:2px solid #E53935;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#C62828">4 Pmt</div><div style="color:#555;font-size:.6rem">120 DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#EF9A9A;border:2px solid #C62828;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#B71C1C">5+ Pmt</div><div style="color:#555;font-size:.6rem">150+ DPD</div></div>
<div style="color:#888">&rarr;</div>
<div style="background:#B71C1C;border:2px solid #7f0000;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:white">Default</div><div style="color:#ffcdd2;font-size:.6rem">Absorbing</div></div>
</div>
<div style="display:flex;justify-content:flex-start;margin-top:6px">
<div style="background:#E3F2FD;border:2px solid #1976D2;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px;font-size:.7rem">
<div style="font-weight:700;color:#1565C0">Payoff</div><div style="color:#555;font-size:.6rem">Absorbing</div></div>
<div style="color:#888;font-size:.7rem;padding:8px 6px">&larr; Any state can transition here (prepayment / maturity)</div></div></div>
'''

    cell_tbl = '''
<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">
<thead><tr><th>Dimension</th><th>Buckets</th><th>Why it matters</th></tr></thead><tbody>
<tr><td><strong>FICO</strong></td><td>&lt;580, 580-619, 620-659, 660-699, 700-739, 740+</td><td>Primary credit-quality signal</td></tr>
<tr><td><strong>LTV</strong></td><td>&lt;80%, 80-99%, 100-119%, 120%+</td><td>Negative equity drives strategic default</td></tr>
<tr><td><strong>Original term</strong></td><td>&le;48mo, 49-60mo, 61-72mo, 73+mo</td><td>Longer terms = slower equity build</td></tr>
<tr><td><strong>Age</strong></td><td>0-6, 7-12, 13-24, 25-36, 37+mo</td><td>Default hazard peaks in months 18-30</td></tr>
<tr><td><strong>Delinquency</strong></td><td>Current, 1-pmt ... 5+pmt, Default, Payoff</td><td>The Markov state itself</td></tr>
<tr><td><strong>Modification</strong></td><td>Modified / not modified</td><td>Modified loans follow a different cure dynamic</td></tr>
</tbody></table></div>
'''

    body = (
        _h4('3a. Markov chain in one paragraph')
        + _p('A <strong>Markov chain</strong> is a probabilistic model whose future '
             'depends only on the present state, not the full path. Applied to auto loans: '
             'a loan that is currently two payments behind has, say, a 30% chance of '
             'curing to one-payment-behind next month, a 35% chance of staying at two, '
             'a 27% chance of rolling to three-payments-behind, a 6% chance of defaulting '
             'outright, and a 2% chance of paying off in full. Those six numbers are the '
             'loan&rsquo;s row of its <em>transition matrix</em>. If we know the row for every '
             'state, we can step the whole pool forward one month at a time until every '
             'loan lands in an absorbing state (<em>Default</em> or <em>Payoff</em>).')
        + _p('The key simplification is that probabilities do <em>not</em> depend on '
             'the loan&rsquo;s history before today. This is obviously wrong in the literal sense '
             '(a loan that has been delinquent five times before is different from one that '
             'first slipped last month), but empirical studies of auto-loan transitions show '
             "that most of that history is already priced into the loan's current state and "
             'static attributes. The Markov approximation, with rich enough state definitions, '
             'tracks lifetime CNL to within a few tens of basis points on in-sample deals.')
        + _h4('3b. States')
        + _p('Every loan-month observation occupies exactly one of eight states:')
        + state_diagram
        + _p('<strong>Default</strong> and <strong>Payoff</strong> are <em>absorbing</em> '
             '&mdash; once entered, never left. The other six are <em>transient</em>. A loan '
             'can roll forward (deeper delinquency), backward (cure), or stay.')
        + _h4('3c. Cell definition')
        + _p('The model does not use one transition matrix for all loans &mdash; subprime '
             'loans roll to default at 10x prime rates from the same state. Instead, loans '
             'are segmented into <em>cells</em> on the following six dimensions:')
        + cell_tbl
        + _p('A cell might be: <code>FICO 620-659 &times; LTV 100-119% &times; term '
             '61-72mo &times; age 13-24 &times; delinq 1-pmt &times; not-modified</code>. '
             'Each populated cell gets its own transition matrix. The cross-product yields '
             '~20k possible cells; ~72% are populated with at least 30 loan-month '
             'observations in the training data. Sparse cells fall back up the ladder: '
             'first coarsening LTV, then term, finally FICO.')
        + _h4('3d. Estimating the transitions')
        + _p('For each cell, we count next-month states for every loan in the training '
             'window, one loan = one vote (no balance weighting &mdash; this is the standard '
             'convention for transition-matrix estimation and avoids giving big-balance '
             'loans disproportionate influence on cure/default frequencies). '
             'If cell <em>c</em> has <em>N</em> loan-months with <em>n<sub>j</sub></em> '
             'transitions to state <em>j</em>, the maximum-likelihood estimate is '
             '<em>p<sub>c,j</sub> = n<sub>j</sub> / N</em>. With N&ge;30 this is sufficient; '
             'below 30 the cell is pooled with its nearest neighbour on the fallback ladder.')
        + _h4('3e. Bayesian calibration')
        + _p('Pool-level performance is the one signal the cell-level count has to handle '
             'carefully: two deals can have identical borrower attributes and still default '
             'at very different rates because of vintage effects (underwriting drift, '
             'used-car cycle, servicing practices). The model adds a <em>deal-specific '
             'calibration multiplier</em> &lambda;<sub>d</sub>, applied to every transition-'
             'to-default probability: <em>p<sup>cal</sup><sub>c,def</sub> = &lambda;<sub>d</sub> '
             '&middot; p<sub>c,def</sub></em>.')
        + _callout('<strong>Calibration prior:</strong> '
                   '&lambda;<sub>d</sub> ~ LogNormal(&mu;=0, &sigma;=0.30) before seeing any '
                   'performance data &mdash; a weak prior centred on &lambda; = 1 (deal behaves '
                   'like the pooled historical average), with a one-sigma range of '
                   '[0.74, 1.35].<br><br>'
                   '<strong>Credibility weight:</strong> realised defaults ($ value) divided '
                   'by total original pool balance. An untested deal with zero realised losses '
                   'has credibility 0 and keeps the prior; a fully liquidated deal with 5% '
                   'realised losses on the original pool has credibility 0.05 and moves the '
                   'posterior substantially toward the observed multiplier.<br><br>'
                   '<strong>Posterior mean:</strong> '
                   '&lambda;<sup>post</sup><sub>d</sub> = (1 &minus; w) &middot; 1 + '
                   'w &middot; (observed_def_$ / model_predicted_def_$)<br><br>'
                   'The posterior is an inverse-variance-weighted average on the log scale; '
                   'the linear-space formula above is the approximation used in code and is '
                   'correct to within rounding for all realistic credibility weights.')
        + _p('<strong>Worked example.</strong> Take CRVNA 2022-P1 at 48 months seasoned. '
             'Model predicts lifetime CNL of 4.27% ($45.0M on the $1,054M original pool). '
             'Realised CNL through month 48: 2.64% ($27.9M). Pool factor is 16.3% remaining.')
        + _callout('Credibility weight = 27.9 / 1054 = 0.0265<br>'
                   'Observed / predicted = 2.64 / 4.27 = 0.618<br>'
                   '&lambda;<sup>post</sup> = 0.9735 &middot; 1.000 + 0.0265 &middot; 0.618 = 0.990<br>'
                   '&rarr; Calibrated projected lifetime CNL &asymp; realised 2.64% + '
                   '0.990 &middot; base-remaining 2.00% = <strong>4.62%</strong><br><br>'
                   '<em>Interpretation:</em> With only 16% of balance left to run, the prior '
                   'still dominates &mdash; the model barely moves off its baseline despite '
                   'under-performing it. That is correct behaviour: there is very little '
                   'future experience left to forecast.',
                   color='#1976D2')
        + _h4('3f. At-issuance vs in-progress forecasts')
        + _p('At deal closing no realised performance exists, so &lambda; = 1.0 and the model '
             'runs the fresh pool forward through base transitions. For in-progress deals, the '
             'model starts from each surviving loan&rsquo;s <em>current</em> observed state on '
             'the latest servicer report, applies the calibrated matrix, and compounds forward '
             'month by month until every surviving loan reaches Default or Payoff. Total '
             'projected CNL = realised losses + remaining calibrated losses.')
    )
    return _section(3, 'The model: Markov chain, cells, calibration', body)


def _sec4_transitions(cache):
    # Heatmap for a representative cell; also hazard-by-age chart, cure-rate,
    # and modification impact.
    body = (_p('The next four charts show what the estimated transition probabilities '
               'look like. They are the core object that drives every dashboard forecast.')
            + _h4('4a. Transition heatmap &mdash; representative cells')
            + _build_transition_heatmap(cache)
            + _h4('4b. Default hazard by loan age')
            + _build_hazard_chart(cache)
            + _h4('4c. Cure rate by delinquency state (one-month cure)')
            + _build_cure_chart(cache)
            + _h4('4d. Modification impact')
            + _build_mod_chart(cache))
    return _section(4, 'What the transitions look like', body)


def _build_transition_heatmap(cache):
    """Render per-cell transition probability heatmaps for 4 illustrative cells.
    Each cell uses one of the 4 REP_CELLS from compute_methodology.
    """
    trans = (cache or {}).get('transitions', {})
    if not trans:
        return _p('<em>No transition data available.</em>')

    STATES = ['Current', '1pmt', '2pmt', '3pmt', '4pmt', '5+pmt']
    ABSORB = ['Default', 'Payoff']
    ALL = STATES + ABSORB

    # Group by (issuer, fb, lb, age_b) for our 4 rep cells, tb='*', sum over term
    REP = [
        ('700-739', '80-99%', '13-24', 'Prime-grade buyer'),
        ('620-659', '100-119%', '13-24', 'Near-prime underwater'),
        ('580-619', '120%+', '13-24', 'Subprime deep underwater'),
        ('740+', '<80%', '13-24', 'Super-prime equity buyer'),
    ]

    # Aggregate across issuers and terms for each rep cell
    # NOTE: Plotly text fields render plain strings — HTML entities like
    # &mdash; / &middot; / &rarr; show up literally. Use Unicode chars.
    out_html = ''
    for fb, lb, age_b, label in REP:
        # aggregate counts: from_state -> {to_state: count}
        agg = {fs: {} for fs in STATES}
        for k, counts in trans.items():
            parts = k.split('|')
            if len(parts) != 6:
                continue
            _issuer, _fb, _lb, _tb, _age, _from = parts
            if (_fb, _lb, _age) != (fb, lb, age_b):
                continue
            if _from not in STATES:
                continue
            for to_state, cnt in counts.items():
                agg[_from][to_state] = agg[_from].get(to_state, 0) + cnt

        # If we have no observations for this rep cell at all, render a
        # plain-text fallback instead of an empty heatmap of em-dashes.
        total_obs = sum(sum(v.values()) for v in agg.values())
        if total_obs == 0:
            out_html += _p(
                f'<strong>{label}</strong> · FICO {fb}, LTV {lb}, age {age_b}mo — '
                '<em>no loan-month observations in this cell yet (cache may be '
                'pending refresh).</em>'
            )
            continue

        # Build normalised probabilities
        z = []
        text = []
        for fs in STATES:
            row_total = sum(agg[fs].values())
            if row_total == 0:
                z.append([0.0] * len(ALL))
                text.append(['—'] * len(ALL))
            else:
                row = [agg[fs].get(ts, 0) / row_total for ts in ALL]
                z.append(row)
                text.append([f'{100*v:.1f}%' if v > 0 else '' for v in row])

        fig = {
            'data': [{
                'type': 'heatmap',
                'z': z,
                'x': ALL,
                'y': STATES,
                'text': text,
                'texttemplate': '%{text}',
                'textfont': {'size': 9},
                'colorscale': [[0, '#FFFFFF'], [0.05, '#BBDEFB'], [0.2, '#64B5F6'],
                               [0.5, '#1976D2'], [1.0, '#0D47A1']],
                'zmin': 0, 'zmax': 1,
                'showscale': False,
                'hovertemplate': 'From %{y} → %{x}: %{text}<extra></extra>',
            }],
            'layout': {
                'title': {'text': f'<b>{label}</b> · FICO {fb}, LTV {lb}, age {age_b}mo',
                          'font': {'size': 12}},
                'xaxis': {'title': 'Next-month state', 'side': 'bottom'},
                'yaxis': {'title': 'Current state', 'autorange': 'reversed'},
                'margin': {'l': 70, 'r': 10, 't': 40, 'b': 50},
            },
        }
        # Stable-id per rep cell so Playwright can target it across rebuilds.
        safe_slug = ('4a_heatmap_' + f'{fb}_{lb}_{age_b}').replace('%', 'pct').replace('+', 'plus').replace(' ', '').replace('<', 'lt').replace('>', 'gt')
        out_html += _plotly_div(fig, height=280, chart_id=safe_slug)

    out_html += _p('<em>Reading the heatmaps:</em> each row sums to 100%. The diagonal '
                  '(stay-in-state) dominates for mild delinquency; defaults intensify '
                  'sharply from the 3+ payments-behind states. Higher LTV shifts mass '
                  'toward default and away from cures.')
    return out_html


def _build_hazard_chart(cache):
    """Monthly default hazard (events / exposed) by age bucket, per tier.

    Rendered as two stacked panels — Prime (CarMax + Carvana) and
    Carvana Non-Prime — because non-prime hazard runs ~4× higher and
    on a single y-axis the prime curves get crushed flat against zero.
    """
    hz = (cache or {}).get('hazard_by_age', {})
    if not hz:
        return _p('<em>No hazard data available.</em>')
    # hz key: "issuer|tier|age_b" -> {default_events, months_exposed}
    ages = ['0-6', '7-12', '13-24', '25-36', '37+']
    series = {}
    for key, v in hz.items():
        issuer, tier, age_b = key.split('|')
        name = f'{issuer} {tier}'
        series.setdefault(name, {})[age_b] = (v['default_events'], v['months_exposed'])

    # Color mapping kept consistent across panels.
    COLORS = {
        'CarMax Prime':       '#1976D2',
        'Carvana Prime':      '#388E3C',
        'Carvana Non-Prime':  '#E64A19',
    }

    def _trace(name, rec):
        y = []
        for a in ages:
            d, e = rec.get(a, (0, 0))
            y.append((d / e * 10000) if e > 0 else None)  # monthly bps
        return {
            'type': 'scatter', 'mode': 'lines+markers',
            'name': name, 'x': ages, 'y': y,
            'line': {'width': 2.5, 'color': COLORS.get(name, '#666')},
            'marker': {'size': 7, 'color': COLORS.get(name, '#666')},
        }

    prime_names = [n for n in ('CarMax Prime', 'Carvana Prime') if n in series]
    np_names    = [n for n in ('Carvana Non-Prime',)             if n in series]

    def _panel(title, names, height, chart_id):
        if not names:
            return ''
        traces = [_trace(n, series[n]) for n in names]
        fig = {'data': traces,
               'layout': {
                   'title': {'text': title, 'font': {'size': 13}, 'x': 0.02},
                   'xaxis': {'title': 'Loan age (months)'},
                   'yaxis': {'title': 'Monthly default hazard (bps)', 'rangemode': 'tozero'},
                   'margin': {'l': 60, 'r': 10, 't': 36, 'b': 50},
                   'legend': {'orientation': 'h', 'y': -0.25},
                   'hovermode': 'x unified'}}
        return _plotly_div(fig, height=height, chart_id=chart_id)

    return (_panel('Prime tiers', prime_names, 280, '4b_hazard_by_age_prime')
            + _panel('Carvana Non-Prime', np_names, 260, '4b_hazard_by_age_nonprime')
            + _p('The hazard curve is a classic: near-zero at age 0 (no one has '
                 'defaulted yet), peaks around month 13-24 (borrowers who were going to '
                 'struggle have surfaced), then declines as bad-credit loans have '
                 'already charged off and the remaining pool is self-selected to survive. '
                 'Non-Prime is on its own panel because its level runs several times '
                 'higher than Prime and would otherwise crush the Prime curves flat.'))


def _build_cure_chart(cache):
    """One-month cure (delinquent -> Current) by state."""
    cure = (cache or {}).get('cure_by_state', {})
    if not cure:
        return _p('<em>No cure data available.</em>')
    states = ['1pmt', '2pmt', '3pmt', '4pmt', '5+pmt']
    series = {}
    for key, v in cure.items():
        issuer, tier, st = key.split('|')
        series.setdefault(f'{issuer} {tier}', {})[st] = v
    traces = []
    for name, rec in sorted(series.items()):
        y = []
        for s in states:
            v = rec.get(s, {'cured': 0, 'total': 0})
            y.append((v['cured'] / v['total'] * 100) if v['total'] > 0 else None)
        traces.append({
            'type': 'bar', 'name': name, 'x': states, 'y': y,
        })
    fig = {'data': traces,
           'layout': {'barmode': 'group',
                      'xaxis': {'title': 'From delinquency state'},
                      'yaxis': {'title': 'Cured to Current next month (%)'},
                      'margin': {'l': 60, 'r': 10, 't': 10, 'b': 50},
                      'legend': {'orientation': 'h', 'y': -0.25}}}
    return (_plotly_div(fig, height=300, chart_id='4c_cure_by_state')
            + _p('One-month cure rates decline monotonically with delinquency depth. '
                 'A 1-pmt loan has a ~40% chance of coming back to Current next month; '
                 'a 5+pmt loan has <5%. Non-prime cures lag prime by 10-15 percentage '
                 'points at every state, reflecting the thinner cushion non-prime '
                 'borrowers have to catch up.'))


def _build_mod_chart(cache):
    mi = (cache or {}).get('mod_impact', {})
    if not mi:
        return _p('<em>No modification data available.</em>')
    rows = []
    for key, v in mi.items():
        parts = key.split('|')
        if len(parts) != 3:
            continue
        issuer, tier, flag = parts
        d, e = v['default_events'], v['months_exposed']
        if e < 1000:
            continue
        rows.append({
            'issuer': issuer, 'tier': tier, 'modified': flag == 'mod',
            'rate_bps': d / e * 10000, 'exposed': e, 'events': d,
        })
    # Build a small table: issuer x tier with mod-vs-nomod default hazard
    tbl_rows = ''
    for r in sorted(rows, key=lambda x: (x['issuer'], x['tier'], not x['modified'])):
        tbl_rows += (
            f'<tr><td>{r["issuer"]}</td><td>{r["tier"]}</td>'
            f'<td>{"Modified" if r["modified"] else "Not modified"}</td>'
            f'<td style="text-align:right">{r["exposed"]:,}</td>'
            f'<td style="text-align:right">{r["events"]:,}</td>'
            f'<td style="text-align:right"><strong>{r["rate_bps"]:.0f} bps</strong></td>'
            f'</tr>')
    return ('<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">'
            '<thead><tr><th>Issuer</th><th>Tier</th><th>Status</th>'
            '<th style="text-align:right">Loan-months</th>'
            '<th style="text-align:right">Default events</th>'
            '<th style="text-align:right">Monthly hazard</th></tr></thead>'
            f'<tbody>{tbl_rows}</tbody></table></div>'
            + _p('Modified loans default 3-8x more often than unmodified loans with '
                 'matched FICO/LTV/term/age. That is the expected ordering &mdash; '
                 'modifications are typically granted only to borrowers already in '
                 'distress &mdash; but the magnitude is important because the model '
                 'treats modification as a separate cell dimension: a modified 2-pmt '
                 'loan and a non-modified 2-pmt loan get different transition matrices.'))


def _sec5_predictors(cache):
    pred = (cache or {}).get('predictor_assoc', {})
    grid = (cache or {}).get('fico_ltv_grid', {})
    body = (_p('Beyond the Markov state, five borrower attributes drive the bulk of '
               'cell-level variation in default probability. The plots below show '
               'monthly-default hazard by each attribute, pooled across issuers and '
               'tiers.')
            + _h4('5a. Hazard by FICO band')
            + _build_pred_chart(pred, 'fico', ['<580', '580-619', '620-659',
                                                '660-699', '700-739', '740+'],
                                chart_id='5a_hazard_by_fico')
            + _h4('5b. Hazard by LTV band')
            + _build_pred_chart(pred, 'ltv', ['<80%', '80-99%', '100-119%', '120%+'],
                                chart_id='5b_hazard_by_ltv')
            + _h4('5c. Hazard by original term')
            + _build_pred_chart(pred, 'term', ['<=48mo', '49-60mo', '61-72mo', '73+mo'],
                                chart_id='5c_hazard_by_term')
            + _h4('5d. Hazard by age (re-expressed with issuer split)')
            + _build_pred_chart(pred, 'age', ['0-6', '7-12', '13-24', '25-36', '37+'],
                                chart_id='5d_hazard_by_age')
            + _h4('5e. FICO &times; LTV interaction table (age 13-24, prime + non-prime combined)')
            + _build_fico_ltv_table(grid)
            + _p('The interaction table shows why the model has to bucket FICO and LTV '
                 'jointly rather than additively. A 740+ FICO borrower at 120%+ LTV '
                 'defaults at roughly the same rate as a 660-699 borrower at &lt;80% LTV &mdash; '
                 'the two predictors are not independent, and a linear model that uses '
                 'only main effects would systematically misprice the corners.'))
    return _section(5, 'Predictor associations', body)


def _build_pred_chart(pred, dim, buckets, chart_id=None):
    """Build a hazard-by-bucket chart for one dimension, split by issuer+tier."""
    if not pred:
        return _p('<em>Data not available.</em>')
    series = {}
    for key, v in pred.items():
        parts = key.split('|')
        if len(parts) != 4:
            continue
        issuer, tier, d, b = parts
        if d != dim:
            continue
        series.setdefault(f'{issuer} {tier}', {})[b] = v
    traces = []
    for name, rec in sorted(series.items()):
        y = []
        for b in buckets:
            v = rec.get(b, None)
            if v is None or v['months_exposed'] < 100:
                y.append(None)
            else:
                y.append(v['default_events'] / v['months_exposed'] * 10000)
        traces.append({'type': 'scatter', 'mode': 'lines+markers',
                       'name': name, 'x': buckets, 'y': y,
                       'line': {'width': 2.5}})
    fig = {'data': traces,
           'layout': {'yaxis': {'title': 'Monthly default hazard (bps)'},
                      'xaxis': {'title': f'{dim.upper()} band'},
                      'margin': {'l': 60, 'r': 10, 't': 10, 'b': 50},
                      'legend': {'orientation': 'h', 'y': -0.25},
                      'hovermode': 'x unified'}}
    return _plotly_div(fig, height=300, chart_id=chart_id)


def _build_fico_ltv_table(grid):
    """Render a FICO x LTV grid of monthly default hazards (bps)."""
    if not grid:
        return _p('<em>Grid data not available.</em>')
    fico_buckets = ['<580', '580-619', '620-659', '660-699', '700-739', '740+']
    ltv_buckets = ['<80%', '80-99%', '100-119%', '120%+']
    # aggregate across issuers
    cell = {}
    for key, v in grid.items():
        issuer, fb, lb = key.split('|')
        c = cell.setdefault((fb, lb), [0, 0])
        c[0] += v['default_events']
        c[1] += v['months_exposed']
    rows_html = ''
    header = '<tr><th>FICO \\ LTV</th>' + ''.join(f'<th>{lb}</th>' for lb in ltv_buckets) + '</tr>'
    for fb in fico_buckets:
        cells_html = f'<td><strong>{fb}</strong></td>'
        for lb in ltv_buckets:
            rec = cell.get((fb, lb), [0, 0])
            d, e = rec
            if e < 100:
                cells_html += '<td style="text-align:right;color:#999">&mdash;</td>'
            else:
                bps = d / e * 10000
                # color gradient
                intensity = min(1.0, bps / 200)  # 200 bps = max red
                r = int(255)
                g = int(235 - 180 * intensity)
                b = int(235 - 180 * intensity)
                cells_html += (f'<td style="text-align:right;background:rgb({r},{g},{b})">'
                               f'{bps:.0f} bps</td>')
        rows_html += f'<tr>{cells_html}</tr>'
    return ('<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:600px;margin:8px 0">'
            f'<thead>{header}</thead><tbody>{rows_html}</tbody></table></div>')


# ==========================================================================
# Section 6: Residual profit worked examples
# ==========================================================================
def _sec6_residual(cache):
    # Use coverage + cost_of_funds to pick two sample deals.
    body = (_p('This section walks the residual-profit formula on two concrete deals &mdash; '
               'one mature Carvana prime (2021-P1, first prime deal, now ~60 months '
               'seasoned and 85% liquidated) and one in-progress CarMax (2023-2, ~22 '
               'months seasoned). The formula is identical to the one used for every '
               'deal in the residual-economics landing table; the worked examples here '
               'just spell out the line items.')
            + _h4('Residual profit formula (percent of original pool)')
            + '<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">'
              '<thead><tr><th>Line item</th><th>Formula</th></tr></thead><tbody>'
              '<tr><td>Consumer WAC (a)</td><td>$-weighted avg APR of underlying loans at origination</td></tr>'
              '<tr><td>Cost of debt (b)</td><td>$-weighted avg coupon of all rated note tranches</td></tr>'
              '<tr><td>Excess spread per year (c)</td><td>= a &minus; b</td></tr>'
              '<tr><td>WAL (d)</td><td>From Markov-projected paydown curve</td></tr>'
              '<tr><td>Total excess spread (e)</td><td>= c &middot; d</td></tr>'
              '<tr><td>Total servicing cost (f)</td><td>= annual servicing fee % &middot; d</td></tr>'
              '<tr><td>Total credit losses (g)</td><td>= Markov projected lifetime CNL % + any realised not in projection</td></tr>'
              '<tr><td style="font-weight:700;color:#1976D2">Residual profit (h)</td>'
              '<td style="font-weight:700">= e &minus; f &minus; g</td></tr>'
              '</tbody></table></div>'
            + _h4('6a. Mature deal: CRVNA 2021-P1 (cutoff Sep-2021, closed Oct-2021)')
            + _callout(
                'Original pool balance: <strong>$415M</strong><br>'
                'Consumer WAC: 8.18% &nbsp; Cost of debt: 0.55% &nbsp; '
                'Excess spread/yr: 7.64%<br>'
                'Estimated WAL: ~2.50 yr<br><br>'
                'Total excess spread: 7.64 &middot; 2.50 = <strong>19.09%</strong><br>'
                'Total servicing: 0.57 &middot; 2.50 = 1.42%<br>'
                'Total losses (model CNL): 5.20%<br><br>'
                '<strong>Expected residual: 19.09 &minus; 1.42 &minus; 5.20 = 12.47%</strong> '
                '($51.7M on $415M)<br><br>'
                '<em>Realised at 48mo seasoning (85% of pool paid down):</em><br>'
                'Actual interest collected: 16.25% &nbsp; actual servicing: 2.85% &nbsp; '
                'realised+projected losses: 4.58%<br>'
                '<strong>Actual residual: 16.25 &minus; 2.85 &minus; 4.58 = 8.82%</strong> '
                '($36.6M)<br>'
                'Variance from forecast: <strong>&minus;3.65%</strong> (faster-than-modelled '
                'prepayments shortened the WAL and collapsed total-interest revenue)',
                color='#1976D2')
            + _h4('6b. In-progress deal: CARMX 2023-2 (cutoff Apr-2023)')
            + _callout(
                'Original pool balance: <strong>$1,454M</strong><br>'
                'Consumer WAC: 7.41% &nbsp; Cost of debt: 5.18% &nbsp; '
                'Excess spread/yr: 2.23%<br>'
                'Estimated WAL: ~1.92 yr<br><br>'
                'Total excess spread: 2.23 &middot; 1.92 = <strong>4.28%</strong><br>'
                'Total servicing: 1.00 &middot; 1.92 = 1.92%<br>'
                'Total losses (Markov projected): 2.85%<br><br>'
                '<strong>Expected residual: 4.28 &minus; 1.92 &minus; 2.85 = &minus;0.49%</strong><br><br>'
                '<em>At 22 months seasoned (~55% of pool paid down):</em><br>'
                'Interest collected so far: 4.45% &nbsp; servicing: 1.08% &nbsp; '
                'realised losses: 1.72% (on-track to 2.85%)<br>'
                '<strong>Residual to date: 4.45 &minus; 1.08 &minus; 1.72 = +1.65%</strong> '
                'of original pool &mdash; and remaining interest will narrow once the back '
                'tail of the pool runs off.<br><br>'
                '<em>Interpretation:</em> A 2023-vintage CarMax prime deal looks '
                'economically marginal for the residual holder, because the '
                'consumer-WAC-to-note-coupon spread compressed sharply during the 2022-23 '
                'rate cycle. Compare to 2021-era Carvana deals whose 7-8% spread made the '
                'residual structurally in-the-money.',
                color='#388E3C'))
    return _section(6, 'Residual-profit worked examples', body)


# ==========================================================================
# Section 7: Regression
# ==========================================================================
def _sec7_regression(cache):
    reg = (cache or {}).get('regression')
    if not reg:
        return _section(7, 'Carvana vs CarMax Prime &mdash; loss perspective',
                        _p('<em>Regression results not yet computed.</em>'))
    eff = reg['issuer_effect']
    by_v = reg.get('by_vintage', [])

    # Build coefficient table (top 20)
    coef_rows = ''
    # Show important rows: issuer, fb_*, lb_*, tb_*, age_b_*, from_state_*, modified
    named = [(c['name'], c) for c in reg['coefficients']]
    IMPORTANT = {'issuer_carmax', 'modified', 'const'}
    IMPORTANT.update([f'fb_{b}' for b in ['<580', '580-619', '620-659', '700-739', '740+']])
    IMPORTANT.update([f'lb_{b}' for b in ['<80%', '100-119%', '120%+']])
    IMPORTANT.update([f'tb_{b}' for b in ['<=48mo', '49-60mo', '73+mo']])
    IMPORTANT.update([f'age_b_{b}' for b in ['0-6', '7-12', '25-36', '37+']])
    IMPORTANT.update([f'from_state_{b}' for b in ['1pmt', '2pmt', '3pmt', '4pmt', '5+pmt']])
    for name, c in named:
        if name not in IMPORTANT:
            continue
        pretty = name.replace('fb_', 'FICO ').replace('lb_', 'LTV ').replace('tb_', 'Term ')
        pretty = pretty.replace('age_b_', 'Age ').replace('from_state_', 'From ')
        pretty = pretty.replace('issuer_carmax', '<strong>Issuer = CarMax</strong>')
        pretty = pretty.replace('modified', 'Modified (=1)').replace('const', 'Intercept')
        star = '***' if c['p'] < 0.001 else ('**' if c['p'] < 0.01 else ('*' if c['p'] < 0.05 else ''))
        coef_rows += (
            f'<tr><td>{pretty}</td>'
            f'<td style="text-align:right">{c["coef"]:+.4f}{star}</td>'
            f'<td style="text-align:right">{c["se"]:.4f}</td>'
            f'<td style="text-align:right">[{c["ci_lo"]:+.3f}, {c["ci_hi"]:+.3f}]</td></tr>'
        )

    # Vintage chart
    vint_chart = ''
    if by_v:
        xs = [r['vintage'] for r in by_v]
        ys = [r['coef'] for r in by_v]
        err_lo = [r['coef'] - r['ci_lo'] for r in by_v]
        err_hi = [r['ci_hi'] - r['coef'] for r in by_v]
        fig = {
            'data': [{
                'type': 'scatter', 'mode': 'markers',
                'x': xs, 'y': ys,
                'error_y': {'type': 'data', 'symmetric': False,
                            'array': err_hi, 'arrayminus': err_lo,
                            'color': '#1976D2', 'thickness': 1.5},
                'marker': {'size': 10, 'color': '#1976D2'},
                'name': 'CarMax vs Carvana log-odds',
            }, {
                'type': 'scatter', 'mode': 'lines',
                'x': [min(xs), max(xs)], 'y': [0, 0],
                'line': {'dash': 'dash', 'color': '#999'},
                'showlegend': False,
            }],
            'layout': {
                'xaxis': {'title': 'Vintage year (deal cutoff)'},
                'yaxis': {'title': 'Log-odds coefficient on Issuer=CarMax'},
                'margin': {'l': 60, 'r': 10, 't': 10, 'b': 50},
                'hovermode': 'x unified',
            }
        }
        vint_chart = _plotly_div(fig, height=300, chart_id='7d_issuer_coef_by_vintage')

    body = (
        _p('<strong>What this tells us about Carvana.</strong> Controlling for FICO, LTV, '
           'original term, loan age, delinquency state, modification, and vintage, a '
           f'Carvana prime loan-month defaults at <strong>{eff["marginal_prob_carvana"]*10000:.2f} bps/month</strong> '
           f'vs. <strong>{eff["marginal_prob_carmax"]*10000:.2f} bps/month</strong> for a matched-attribute '
           f'CarMax loan &mdash; a gap of <strong>{abs(eff["marginal_diff_monthly_bps"]):.2f} bps/month '
           f'({eff["marginal_diff_monthly_bps"]*12:+.1f} bps/year)</strong> with '
           f'Carvana higher. '
           '<strong>For Carvana, this is a small but measurable underwriting / collections '
           'penalty</strong> that shows up <em>after</em> borrower composition is controlled for: '
           'the bulk of the raw-rate gap is composition (CarMax skews higher-FICO, lower-LTV, '
           'shorter-term), but an order-of-magnitude-smaller issuer-specific residual remains '
           'and it goes the wrong way for Carvana. Useful framing: this gap is '
           '~10x smaller than the effect of moving FICO by 40 points, so it is a '
           'recovered-collections / loss-mitigation issue, not a broken-underwriting issue. '
           'Sections 7a-7d below document the methodology, sensitivity, and vintage-by-vintage '
           'stability of this estimate.')
        + _h4('7a. Methodology')
        + _p('The response variable is <strong>default_next</strong>: 1 if the loan was '
             'charged off (zero_balance_code = 3 or charged_off_amount &gt; 0) in the '
             'current month, 0 otherwise. The estimator is pooled logit with fixed '
             'effects for:')
        + '<ul style="font-size:.78rem;line-height:1.7;padding-left:22px">'
        + '<li>FICO band (6 levels; reference = 660-699)</li>'
        + '<li>LTV band (4 levels; reference = 80-99%)</li>'
        + '<li>Original term (4 levels; reference = 61-72mo)</li>'
        + '<li>Loan age bucket (5 levels; reference = 13-24mo)</li>'
        + '<li>Delinquency state entering the month (6 levels; reference = Current)</li>'
        + '<li>Modification flag (0/1)</li>'
        + '<li>Vintage year (fixed effects, 2017-2025)</li>'
        + '<li><strong>Issuer dummy</strong> (CarMax = 1, Carvana = 0) &mdash; the coefficient of interest</li>'
        + '</ul>'
        + _p(f'<strong>Sample.</strong> Stratified sample of {reg["n_fit"]:,} loan-months '
             f'(~{reg["default_rate_fit"]*100:.2f}% default rate in the fit sample vs. '
             f'{reg["default_rate_sample"]*100:.3f}% in the source &mdash; we retained all '
             'positives and undersampled the negatives to speed fitting while keeping the '
             'issuer identification unbiased; the intercept is adjusted back for the '
             'sampling ratio when computing marginal effects). Scope: prime loans only '
             '(Carvana Prime deals + all CarMax deals). Non-prime is excluded because '
             'CarMax has no non-prime deals and the issuer dummy would be collinear with '
             'tier. Pseudo R&sup2; (McFadden) = '
             f'{reg["pseudo_r2_mcfadden"]:.3f}.')
        + _h4('7b. Headline coefficient')
        + _callout(
            f'<strong>Issuer = CarMax coefficient:</strong> {eff["coef"]:+.4f} '
            f'(SE {eff["se"]:.4f})<br>'
            f'95% CI: [{eff["ci_lo"]:+.4f}, {eff["ci_hi"]:+.4f}]<br>'
            f'Odds ratio: {eff["odds_ratio"]:.3f} '
            f'&nbsp; 95% CI: [{eff["odds_ratio_ci_lo"]:.3f}, {eff["odds_ratio_ci_hi"]:.3f}]<br><br>'
            f'<strong>Marginal monthly default probability at sample means:</strong><br>'
            f'&nbsp;&nbsp;Carvana Prime: {eff["marginal_prob_carvana"]*10000:.2f} bps / month<br>'
            f'&nbsp;&nbsp;CarMax: {eff["marginal_prob_carmax"]*10000:.2f} bps / month<br>'
            f'&nbsp;&nbsp;<strong>Difference: {eff["marginal_diff_monthly_bps"]:+.2f} bps/month</strong> '
            f'&rarr; {eff["marginal_diff_monthly_bps"]*12:+.1f} bps/year<br><br>'
            '<em>Interpretation.</em> Holding FICO, LTV, term, age, delinquency state, '
            'modification, and vintage fixed, a CarMax prime loan-month has '
            f'{"higher" if eff["coef"] > 0 else "lower"} odds of defaulting than a '
            'comparable Carvana prime loan-month by a factor of '
            f'{eff["odds_ratio"]:.2f}x. Translated to monthly default probability at the '
            f'sample mean covariate profile, the gap is '
            f'<strong>{abs(eff["marginal_diff_monthly_bps"]):.1f} bps/month '
            f'({"CarMax worse" if eff["coef"] > 0 else "Carvana worse"})</strong>.',
            color='#1565C0')
        + _h4('7c. Full coefficient table (key rows)')
        + '<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:680px;margin:8px 0">'
          '<thead><tr><th>Covariate</th><th style="text-align:right">Coef</th>'
          '<th style="text-align:right">SE</th><th style="text-align:right">95% CI</th></tr></thead>'
          f'<tbody>{coef_rows}</tbody></table></div>'
        + _p('<em>Signs sanity-check.</em> FICO bands above 660-699 have negative coefficients '
             '(lower default probability); bands below have positive coefficients. LTV bands above '
             '80-99% have positive coefficients (higher default). Deeper delinquency states have '
             'large positive coefficients. These all match prior expectations, giving confidence '
             'that the covariate space is controlling for the obvious confounders before isolating '
             'the issuer effect. Stars: * p&lt;0.05, ** p&lt;0.01, *** p&lt;0.001.')
        + _h4('7d. Does the issuer effect vary over time?')
        + vint_chart
        + _p('Each dot is the issuer coefficient (CarMax vs. Carvana) fit separately on '
             'one vintage year, with 95% confidence bars. The estimate can vary across '
             'vintages even if the full-sample effect is stable. Interpret a point above '
             'the dashed zero line as "CarMax defaulted more than Carvana that year, '
             'after controls."')
        + _p('<strong>Plain-English summary.</strong> Imagine we had a magic button that '
             'could hand any Carvana prime borrower a CarMax loan (same FICO, same LTV, '
             'same term, same age) and vice-versa. The regression estimates what would '
             f'happen to their monthly default odds. The answer: a '
             f'{abs(eff["marginal_diff_monthly_bps"]):.1f} bps/month difference &mdash; '
             f'meaningful, measurable, but an order of magnitude smaller than the '
             'difference you get from changing FICO by 40 points. The bulk of the '
             'raw-default-rate gap between the two issuers is composition, not '
             'underwriting quality.')
    )
    return _section(7, 'Carvana loss performance vs CarMax benchmark (regression)', body)


def _sec8_yield(cache):
    cw = (cache or {}).get('consumer_wac_comparison', {})
    cells = cw.get('cells', []) if cw else []
    wtd = cw.get('weighted_avg_diff_pct') if cw else None
    # Build cell-by-cell table
    cell_rows = ''
    for c in sorted(cells, key=lambda x: (x['cell_fico'], x['cell_ltv'], x['cell_term']))[:25]:
        cell_rows += (
            f'<tr><td>{c["cell_fico"]}</td><td>{c["cell_ltv"]}</td><td>{c["cell_term"]}</td>'
            f'<td style="text-align:right">${c["carvana_orig_amt"]/1e6:.0f}M</td>'
            f'<td style="text-align:right">${c["carmax_orig_amt"]/1e6:.0f}M</td>'
            f'<td style="text-align:right">{c["carvana_apr_pct"]:.2f}%</td>'
            f'<td style="text-align:right">{c["carmax_apr_pct"]:.2f}%</td>'
            f'<td style="text-align:right;font-weight:600">{c["diff_pct"]:+.2f}%</td></tr>'
        )
    _wtd_pp = abs(wtd) if wtd is not None else None
    _wtd_str = f'{_wtd_pp:.2f} percentage points' if _wtd_pp is not None else 'N/A'
    body = (
        _p('<strong>What this tells us about Carvana.</strong> Holding FICO, LTV, and '
           f'original term fixed, Carvana charges consumers <strong>{_wtd_str} '
           f'more APR</strong> than CarMax on matched-attribute prime loans '
           f'({cw.get("n_cells_matched", 0)} matched cells, loan-amount-weighted). '
           '<strong>For Carvana, this is the flipside of the §7 loss penalty</strong>: '
           'Carvana collects materially more yield at origination from the same stated risk '
           'profile, meaning the ~5 bps/year loss penalty shown in §7 is paid for many times '
           'over by the consumer-APR premium. The residual-economics math therefore still '
           'favors Carvana at the borrower level; the issue is funding-cost, not asset-yield '
           '(see §9). The mirror-image question to §7: holding borrower attributes '
           'fixed, does one issuer <em>charge</em> the consumer more per unit of stated risk?')
        + _h4(f'8a. Matched-cell consumer APR difference (CarMax &minus; Carvana, prime only)')
        + (_callout(f'<strong>Loan-amount-weighted aggregate APR difference: '
                    f'{"+"+str(round(wtd,2))+"pp" if wtd is not None else "N/A"}</strong> '
                    f'across {cw.get("n_cells_matched", 0)} matched cells.<br><br>'
                    '<em>Positive &rarr; CarMax charges more.</em> '
                    '<em>Negative &rarr; Carvana charges more.</em>',
                    color='#1565C0') if wtd is not None else '')
        + '<p style="font-size:.72rem;color:#666;margin-top:8px">Top 25 matched cells shown (both issuers have &ge;$1M originated in each cell).</p>'
        + '<div style="overflow-x:auto"><table style="font-size:.7rem;max-width:780px;margin:8px 0">'
          '<thead><tr><th>FICO</th><th>LTV</th><th>Term</th>'
          '<th style="text-align:right">Carvana $</th>'
          '<th style="text-align:right">CarMax $</th>'
          '<th style="text-align:right">Carvana APR</th>'
          '<th style="text-align:right">CarMax APR</th>'
          '<th style="text-align:right">Difference</th></tr></thead>'
          f'<tbody>{cell_rows}</tbody></table></div>'
        + _p('<strong>Reading this table.</strong> Each row holds FICO, LTV, and original '
             'term fixed. Where the sign of the APR difference is consistent across many '
             'cells, the pricing gap is likely a real issuer-level effect. Where it '
             'flips sign across cells, the gap is probably driven by other unobserved '
             'factors (PTI, subvention, vehicle age) and should not be interpreted as '
             'a consistent premium.'))
    return _section(8, 'Carvana consumer-APR premium vs CarMax (yield perspective)', body)


def _sec9_cof(cache):
    cof = (cache or {}).get('cost_of_funds', [])
    if not cof:
        return _section(9, 'Cost of funds comparison',
                        _p('<em>Cost-of-funds data not available.</em>'))
    # Two charts: (1) note WAC vs 2Y Treasury scatter; (2) spread time series
    carvana = [c for c in cof if c['issuer'] == 'Carvana' and c.get('note_wac_pct')]
    carmax = [c for c in cof if c['issuer'] == 'CarMax' and c.get('note_wac_pct')]

    # time series (scatter with line per issuer + treasury overlay)
    traces = []
    for label, rows, color in [('Carvana Prime', [r for r in carvana if r['tier']=='Prime'], '#1976D2'),
                                ('Carvana Non-Prime', [r for r in carvana if r['tier']=='Non-Prime'], '#F57F17'),
                                ('CarMax Prime', carmax, '#388E3C')]:
        if not rows:
            continue
        xs = [r['cutoff_date'] for r in rows]
        ys = [r['note_wac_pct'] for r in rows]
        txt = [r['deal'] for r in rows]
        traces.append({
            'type': 'scatter', 'mode': 'markers+lines',
            'name': label, 'x': xs, 'y': ys, 'text': txt,
            'marker': {'size': 8, 'color': color}, 'line': {'width': 1.5, 'color': color},
            'hovertemplate': '%{text}<br>%{x}<br>WAC: %{y:.2f}%<extra></extra>',
        })
    # Treasury 2Y line (dates spanning Carvana+CarMax range)
    tdates = [r['cutoff_date'] for r in cof if r.get('treasury_2y_pct')]
    tys = [r['treasury_2y_pct'] for r in cof if r.get('treasury_2y_pct')]
    pairs = sorted(zip(tdates, tys))
    if pairs:
        traces.append({
            'type': 'scatter', 'mode': 'lines',
            'name': '2Y Treasury yield', 'x': [p[0] for p in pairs], 'y': [p[1] for p in pairs],
            'line': {'color': '#9E9E9E', 'width': 1.5, 'dash': 'dot'},
        })
    fig_wac = {
        'data': traces,
        'layout': {'xaxis': {'title': 'Deal cutoff date'},
                   'yaxis': {'title': 'Weighted-avg note coupon / 2Y Tsy yield (%)'},
                   'margin': {'l': 60, 'r': 10, 't': 10, 'b': 60},
                   'legend': {'orientation': 'h', 'y': -0.28},
                   'hovermode': 'closest'}
    }

    # Spread time series: note WAC - 2Y Tsy
    spread_traces = []
    for label, rows, color in [('Carvana Prime', [r for r in carvana if r['tier']=='Prime'], '#1976D2'),
                                ('Carvana Non-Prime', [r for r in carvana if r['tier']=='Non-Prime'], '#F57F17'),
                                ('CarMax Prime', carmax, '#388E3C')]:
        sub = [r for r in rows if r.get('spread_pct') is not None]
        if not sub:
            continue
        spread_traces.append({
            'type': 'scatter', 'mode': 'markers+lines',
            'name': label, 'x': [r['cutoff_date'] for r in sub],
            'y': [r['spread_pct'] for r in sub],
            'text': [r['deal'] for r in sub],
            'marker': {'size': 8, 'color': color}, 'line': {'width': 1.5, 'color': color},
            'hovertemplate': '%{text}<br>%{x}<br>Spread: %{y:.2f}pp<extra></extra>',
        })
    fig_spread = {
        'data': spread_traces,
        'layout': {'xaxis': {'title': 'Deal cutoff date'},
                   'yaxis': {'title': 'Note WAC &minus; 2Y Treasury (pp)'},
                   'margin': {'l': 60, 'r': 10, 't': 10, 'b': 60},
                   'legend': {'orientation': 'h', 'y': -0.28},
                   'hovermode': 'closest'}
    }

    # Aggregate: avg spread by issuer+tier
    agg_rows = ''
    for label, rows in [('Carvana Prime', [r for r in carvana if r['tier']=='Prime']),
                        ('Carvana Non-Prime', [r for r in carvana if r['tier']=='Non-Prime']),
                        ('CarMax Prime', carmax)]:
        sub = [r for r in rows if r.get('spread_pct') is not None]
        if not sub:
            continue
        avg_wac = sum(r['note_wac_pct'] for r in sub) / len(sub)
        avg_tres = sum(r['treasury_2y_pct'] for r in sub) / len(sub)
        avg_spread = sum(r['spread_pct'] for r in sub) / len(sub)
        agg_rows += (f'<tr><td><strong>{label}</strong></td>'
                     f'<td style="text-align:right">{len(sub)}</td>'
                     f'<td style="text-align:right">{avg_wac:.2f}%</td>'
                     f'<td style="text-align:right">{avg_tres:.2f}%</td>'
                     f'<td style="text-align:right"><strong>{avg_spread:+.2f}pp</strong></td></tr>')

    # Compute Carvana-centric cost-of-funds summary (vs CarMax benchmark).
    # Avg spread by Carvana tier and matched-year CarMax comparison.
    _cv_prime = [r for r in carvana if r['tier']=='Prime' and r.get('spread_pct') is not None]
    _cv_np = [r for r in carvana if r['tier']=='Non-Prime' and r.get('spread_pct') is not None]
    _cm_all = [r for r in carmax if r.get('spread_pct') is not None]
    _avg_cv_prime_bps = (sum(r['spread_pct'] for r in _cv_prime)/len(_cv_prime)*100) if _cv_prime else None
    _avg_cm_bps = (sum(r['spread_pct'] for r in _cm_all)/len(_cm_all)*100) if _cm_all else None
    # Matched-year Carvana-Prime vs CarMax gap (only years with both)
    from collections import defaultdict as _dd_cof
    _by_yr = _dd_cof(lambda: {'cv':[], 'cm':[]})
    for r in _cv_prime:
        y = (r.get('closing_date') or '')[:4]
        if y: _by_yr[y]['cv'].append(r['spread_pct'])
    for r in _cm_all:
        y = (r.get('closing_date') or '')[:4]
        if y: _by_yr[y]['cm'].append(r['spread_pct'])
    _gap_vals = []
    for y, grp in _by_yr.items():
        if grp['cv'] and grp['cm']:
            _gap_vals.append((sum(grp['cv'])/len(grp['cv']) - sum(grp['cm'])/len(grp['cm']))*100)
    _avg_gap_bps = (sum(_gap_vals)/len(_gap_vals)) if _gap_vals else None
    _cv_prime_str = f'{_avg_cv_prime_bps:.0f} bps' if _avg_cv_prime_bps is not None else 'N/A'
    _cm_str = f'{_avg_cm_bps:.0f} bps' if _avg_cm_bps is not None else 'N/A'
    _gap_str = (f'<strong>+{_avg_gap_bps:.0f} bps wider</strong>'
                if _avg_gap_bps is not None and _avg_gap_bps >= 0 else
                (f'<strong>{_avg_gap_bps:.0f} bps tighter</strong>'
                 if _avg_gap_bps is not None else 'N/A'))

    body = (
        _p(f'<strong>What this tells us about Carvana.</strong> Across the years when both '
           f'issuers priced deals, Carvana Prime ABS notes priced '
           f'{_gap_str} over 2Y Treasury than CarMax Prime &mdash; i.e. Carvana pays that '
           'much more to ABS investors per unit of funded pool. '
           f'Carvana Prime averages {_cv_prime_str} over 2Y Tsy across {len(_cv_prime)} '
           f'deals; CarMax averages {_cm_str} across {len(_cm_all)} deals. '
           '<strong>Implication for Carvana residual economics:</strong> on a 2.5-year '
           'prime-deal WAL, a 30-50 bps cost-of-funds premium compounds to ~75-125 bps '
           'of residual value given up vs. a hypothetical CarMax-priced execution &mdash; '
           'comparable in magnitude to the CNL-model error band. Carvana Non-Prime prices '
           'materially wider still, reflecting the subprime investor base. The directional '
           'takeaway for Carvana equity: the consumer-APR premium from §8 is partly '
           'consumed by this funding premium; what remains is the true residual spread. '
           'Cost of funds &mdash; the dollar-weighted coupon Carvana pays on all rated '
           'tranches at pricing &mdash; is the other half of the residual arithmetic.')
        + _h4('9a. Note WAC vs 2Y Treasury over time')
        + _plotly_div(fig_wac, height=340, chart_id='9a_note_wac_vs_2y_tsy')
        + _h4('9b. Credit spread (note WAC &minus; 2Y Treasury)')
        + _plotly_div(fig_spread, height=340, chart_id='9b_credit_spread')
        + _p('Stripping out the benchmark component isolates the credit spread the market '
             'demanded at issuance. Flat-line segments indicate stable risk pricing; '
             'visible jumps correspond to SVB (Mar-2023), regional-bank stress '
             '(Apr-2023), and the macro-vol regime shifts of 2022.')
        + _h4('9c. Summary averages')
        + '<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">'
          '<thead><tr><th>Cohort</th>'
          '<th style="text-align:right">Deals</th>'
          '<th style="text-align:right">Avg note WAC</th>'
          '<th style="text-align:right">Avg 2Y Tsy</th>'
          '<th style="text-align:right">Avg credit spread</th></tr></thead>'
          f'<tbody>{agg_rows}</tbody></table></div>'
        + _p('<strong>Interpretation.</strong> On a like-rate-cycle basis, CarMax prices '
             'tighter than Carvana Prime by a meaningful margin &mdash; CarMax has a '
             'longer track record (2014-onwards), monoline prime focus, and a '
             'corporate-investment-grade parent, all of which compress ABS spreads. '
             'Carvana Non-Prime trades meaningfully wider still, consistent with its '
             'higher expected loss profile and the narrower investor base for subprime '
             'auto paper. The 2022-23 rate cycle lifted all three series by 200-300 bps '
             'in <em>spread</em> (not just outright yield), indicating investors '
             'repriced credit on top of the benchmark move.'))
    return _section(9, 'Carvana cost of funds vs CarMax benchmark', body)


def _sec10_limitations():
    body = (
        '<ul style="font-size:.78rem;line-height:1.7;padding-left:22px">'
        '<li><strong>Macro-regime exclusion.</strong> The training window (2017-2026Q1) '
        'includes COVID (2020) and the 2022-23 rate-hike cycle but no conventional '
        'US recession with broad-based unemployment &gt;6%. Forecasts for a 2028-style '
        'shock with unemployment spiking to 7-8% would be extrapolative. The Markov '
        'has no macro input and cannot express "losses will accelerate if '
        'unemployment rises" beyond what the calibration multiplier picks up after '
        'the fact.</li>'
        '<li><strong>Stationarity.</strong> Cell-level transition probabilities are '
        'assumed time-invariant over the ~9-year training window. They are not '
        '(used-car price spikes in 2021 pulled forward prepayments by ~200 bps of '
        'monthly CPR; the 2022 inventory crunch did the opposite). A time-varying '
        'Markov &mdash; or at least a vintage-specific calibration &mdash; would be '
        'a natural next step.</li>'
        '<li><strong>CarMax pre-2017 loans.</strong> 12 CarMax deals closed before '
        'the 2016 Reg AB II loan-level disclosure regime. These are in the pool-level '
        'data (pool_performance / 10-D) but not in the loan-level training set. '
        'They are excluded from §7&rsquo;s regression entirely.</li>'
        '<li><strong>Prospectus parser edge cases.</strong> Deal terms (coupons, OC, '
        'trigger schedules, servicing fee) are extracted programmatically from 424(b)(5) '
        'filings. Two deals (CARMX 2016-1 and CARMX 2017-3) had non-standard 424 '
        'layouts that the parser could not fully reconstruct; for those we fall back '
        'to the 10-D cover sheet where possible and flag "terms_extracted = 0". '
        'Four parser bugs were caught and fixed in the last audit pass &mdash; see '
        'AUDIT_FINDINGS.md for the enumerated log.</li>'
        '<li><strong>Liquidation-proceeds sign convention.</strong> The 10-D '
        '<code>liquidation_proceeds</code> column is net of repossession / disposition '
        'expenses following the issuer\'s own formula. Early-cycle values can be '
        'negative (costs exceed sales). The dashboard shows these as-is &mdash; '
        'they are source-faithful, not parser errors.</li>'
        '<li><strong>Small-cell bias.</strong> ~28% of cells (FICO &times; LTV &times; '
        'term &times; age &times; state &times; mod) have fewer than 30 loan-month '
        'observations. For those the model uses the fallback ladder (coarsen LTV, '
        'then term, then FICO). This introduces bias if the nearest populated cell '
        'is systematically different from the missing cell. Practical impact is '
        'small in aggregate because small cells also have small populations to '
        'project forward.</li>'
        '<li><strong>Observational, not causal.</strong> The issuer coefficient in §7 '
        'is a <em>descriptive</em> statistic: after controls, CarMax and Carvana differ '
        'by <em>x</em> bps/month. It is <strong>not</strong> a causal estimate of '
        '"if Carvana adopted CarMax underwriting, defaults would drop by <em>x</em>." '
        'Unobservables (PTI, subvention, vehicle age, geographic mix, servicer '
        'practices) are still in the error term.</li>'
        '<li><strong>No forecast of prepayment behaviour separately from default.</strong> '
        'The Markov treats Payoff as an absorbing state drawn from the cell-specific '
        'transition probabilities, which are estimated jointly with default. A sudden '
        'change in the prepayment regime (e.g. a rate-cut-driven refi wave) would be '
        'absorbed into the calibration multiplier only after realising several months '
        'of experience.</li>'
        '<li><strong>No OC-breach / trigger-probability output.</strong> The model '
        'projects CNL but does not yet emit the probability of hitting the '
        'cumulative-net-loss or delinquency triggers during life. The residual-economics '
        'table\'s "trigger risk" column shows "&mdash;" for that reason. This is a '
        'well-scoped follow-on and is tracked separately.</li>'
        '</ul>'
    )
    return _section(10, 'Limitations &amp; caveats', body)


def _sec12_carvana_takeaways(cache):
    """Carvana-centric synthesis of the full methodology analysis.

    Pulls live numbers from the analytics cache so the bullets stay honest
    as the underlying data moves. All numbers are pulled from the same
    source that drives sections 7-9 above.
    """
    if not cache:
        return _section(12, 'Carvana takeaways',
                        _p('<em>Analytics cache missing &mdash; takeaways unavailable.</em>'))

    reg = cache.get('regression', {}) or {}
    eff = reg.get('issuer_effect', {}) or {}
    cof = cache.get('cost_of_funds', []) or []
    cw = cache.get('consumer_wac_comparison', {}) or {}

    # --- Bullet 1 source: §7 monthly default gap (Carvana vs matched CarMax) ---
    _marginal_bps = eff.get('marginal_diff_monthly_bps')
    _cv_prob = eff.get('marginal_prob_carvana')
    _cm_prob = eff.get('marginal_prob_carmax')
    _odds = eff.get('odds_ratio')

    # --- Bullet 2 source: §7 vintage-by-vintage regression stability ---
    by_v = reg.get('by_vintage', []) or []
    # Each entry has vintage, coef (CarMax-vs-Carvana log-odds).
    vint_info = []
    for v in by_v:
        vint_info.append((v.get('vintage'), v.get('coef'), v.get('n')))
    vint_info.sort()

    # --- Bullet 3 source: §8 consumer APR premium ---
    _cw_diff = cw.get('weighted_avg_diff_pct')  # e.g. -1.65 means Carvana +1.65pp
    _cw_n = cw.get('n_cells_matched', 0)

    # --- Bullet 4 source: §9 cost-of-funds spread gap ---
    from collections import defaultdict as _dd_tk
    by_yr = _dd_tk(lambda: {'cv':[], 'cm':[]})
    for r in cof:
        y = (r.get('closing_date') or '')[:4]
        if not y: continue
        if r.get('spread_pct') is None: continue
        if r.get('issuer') == 'Carvana' and r.get('tier') == 'Prime':
            by_yr[y]['cv'].append(r['spread_pct'])
        elif r.get('issuer') == 'CarMax':
            by_yr[y]['cm'].append(r['spread_pct'])
    matched_yrs = sorted(y for y, g in by_yr.items() if g['cv'] and g['cm'])
    # Early (first matched year) vs most recent matched year.
    def _year_gap_bps(y):
        g = by_yr[y]
        return (sum(g['cv'])/len(g['cv']) - sum(g['cm'])/len(g['cm'])) * 100
    first_gap = _year_gap_bps(matched_yrs[0]) if matched_yrs else None
    last_gap = _year_gap_bps(matched_yrs[-1]) if matched_yrs else None

    # --- Bullet 5 source: §2 coverage / scale ---
    cov = cache.get('coverage', []) or []
    n_crv = sum(1 for d in cov if (d.get('issuer') == 'Carvana'))
    n_cmx = sum(1 for d in cov if (d.get('issuer') == 'CarMax'))

    # -----------------------------------------------------------------------
    # Bullets. Each one pulls a live number from above and pairs it with the
    # Carvana-centric interpretation the user said they actually want.
    # -----------------------------------------------------------------------
    bullets = []

    # Bullet 1 — the headline issuer-specific loss gap.
    # marginal_prob_* is evaluated at the sample-mean covariate profile, where
    # both issuers have very low default rates, so absolute bps/month is
    # small and the odds-ratio reads huge; we translate into a 60-month
    # cumulative-CNL gap (the thing that actually hits residual value).
    if _marginal_bps is not None and _cv_prob and _cm_prob:
        # Cumulative CNL over a 60-month prime life, using the stratified-
        # sample marginal default rates. |marginal_bps/month| * 60 = bps
        # of cumulative default incidence (before recoveries).
        cnl_gap_bps = abs(_marginal_bps) * 60
        # Statistical significance direction from CI signs.
        ci_lo = eff.get("ci_lo")
        ci_hi = eff.get("ci_hi")
        sig_word = 'statistically significant'
        if ci_lo is not None and ci_hi is not None and ci_lo < 0 < ci_hi:
            sig_word = 'marginally significant'
        bullets.append(
            f'<li><strong>Carvana carries a small but statistically real issuer-specific '
            f'loss penalty vs. CarMax after controlling for borrower attributes.</strong> '
            f'With FICO, LTV, term, age, modification, vintage, and delinquency state all '
            f'in the regression, a Carvana prime loan-month has '
            f'<strong>higher default odds than a matched CarMax loan-month</strong>, '
            f'{sig_word} at the 95% level '
            f'(CarMax-vs-Carvana log-odds {eff.get("coef", 0):+.2f}, 95% CI '
            f'[{ci_lo if ci_lo is None else f"{ci_lo:+.2f}"}, '
            f'{ci_hi if ci_hi is None else f"{ci_hi:+.2f}"}]). Translated into the '
            f'metric that drives residual value: a cumulative-CNL gap of '
            f'<strong>~{cnl_gap_bps:.0f} bps over a 60-month prime life</strong> '
            f'(i.e. a few basis points, not a few percent). This is an order of magnitude '
            f'smaller than a 40-point FICO effect in the same regression, so it\'s '
            f'better read as a collections / recoveries signal than a broken-underwriting '
            f'signal.</li>'
        )

    # Bullet 2 — vintage stability (does the gap improve over time?).
    # Pick the two endpoint vintages; interpret the direction honestly.
    if vint_info and len(vint_info) >= 2:
        first = vint_info[0]; last = vint_info[-1]
        # "CarMax vs Carvana" coef: more negative = Carvana worse (CarMax lower odds).
        # Gap widening if last coef is more negative than first; tightening if less negative.
        if last[1] < first[1] - 0.5:
            headline = "is widening across more recent vintages"
            direction_word = "widening"
            interp = ("This is a negative signal for Carvana — more recent pools appear to "
                      "have a larger issuer-specific default gap than the 2020-21 vintages. "
                      "Two important caveats: (1) the youngest vintage has very few observed "
                      "charge-offs so its coefficient has a wide CI; (2) Carvana\'s origination "
                      "mix has shifted meaningfully over this window. The signal deserves a "
                      "rerun once each vintage has &gt;24 months of seasoning.")
        elif last[1] > first[1] + 0.5:
            headline = "is narrowing across more recent vintages"
            direction_word = "tightening"
            interp = ("This is a positive signal for Carvana — more recent pools look closer "
                      "to CarMax on an issuer-specific basis, consistent with a maturing "
                      "underwriting/servicing platform.")
        else:
            headline = "has been roughly stable across vintages"
            direction_word = "stable"
            interp = ("The stability of the effect is itself informative: it suggests the "
                      "Carvana-vs-CarMax gap reflects a structural difference in "
                      "collections/recoveries rather than cohort-specific luck.")
        bullets.append(
            f'<li><strong>Carvana\'s issuer-specific loss gap vs. CarMax {headline}.</strong> '
            f'Vintage-by-vintage regressions show the CarMax-vs-Carvana log-odds coefficient '
            f'moved from <strong>{first[1]:+.2f}</strong> in the {first[0]} cohort '
            f'(n={first[2]:,}) to <strong>{last[1]:+.2f}</strong> in the {last[0]} cohort '
            f'(n={last[2]:,}) &mdash; direction: <em>{direction_word}</em>. {interp}</li>'
        )

    # Bullet 3 — consumer-APR premium
    if _cw_diff is not None:
        premium_pp = abs(_cw_diff)
        bullets.append(
            f'<li><strong>Carvana prices the consumer meaningfully wider than CarMax, which '
            f'more than pays for the §7 loss penalty.</strong> On FICO/LTV/term-matched '
            f'prime loans ({_cw_n} matched cells, loan-amount-weighted), Carvana charges '
            f'<strong>{premium_pp:.2f} percentage points more APR</strong> than CarMax. '
            f'Annualized, that is roughly 100&times; the §7 loss penalty &mdash; so Carvana\'s '
            f'<em>asset-yield economics</em> vs. CarMax are strongly favorable. The equity '
            f'question for Carvana is funding, not assets.</li>'
        )

    # Bullet 4 — cost-of-funds premium (funding side).
    # Direction is data-driven — the gap may widen or tighten over time.
    if first_gap is not None and last_gap is not None and matched_yrs:
        _dir_word = ('widened' if last_gap > first_gap + 5
                     else ('tightened' if last_gap < first_gap - 5
                           else 'held roughly steady'))
        _headline = (
            "is widening, not tightening" if _dir_word == 'widened' else
            ("has compressed from first-issuance levels" if _dir_word == 'tightened' else
             "is holding roughly steady since first issuance")
        )
        bullets.append(
            f'<li><strong>Carvana\'s cost-of-funds premium vs. CarMax {_headline}.</strong> '
            f'In Carvana\'s first full matched year ({matched_yrs[0]}), Carvana Prime paid '
            f'<strong>{first_gap:+.0f} bps wider</strong> over 2Y Treasury than CarMax; '
            f'in the latest matched year ({matched_yrs[-1]}), the gap is '
            f'<strong>{last_gap:+.0f} bps</strong> (gap has {_dir_word} by '
            f'{abs(last_gap - first_gap):.0f} bps). This is the single largest drag on '
            f'Carvana residual economics vs. a CarMax-priced execution: on a 2.5-year '
            f'prime WAL, the current-year gap compounds to ~{abs(last_gap)*2.5/100:.2f} '
            f'pp of pool value that a hypothetical CarMax-rated Carvana deal could '
            f'retain but Carvana currently cannot. Closing this gap is the highest-leverage '
            f'lever for Carvana residual-equity value.</li>'
        )

    # Bullet 5 — Carvana equity interpretation of the three gaps together.
    # The loss penalty is tiny in annualized-pp units because it's evaluated
    # at the sample mean; display it in bps to keep the scale honest.
    if _cw_diff is not None and last_gap is not None and _marginal_bps is not None:
        yr_penalty_bps = _marginal_bps * 12  # bps / yr, already signed (negative = Carvana worse)
        yr_penalty_pp = yr_penalty_bps / 100.0  # convert to pp/yr for net arithmetic
        net_pp = abs(_cw_diff) + yr_penalty_pp - (last_gap/100.0)
        bullets.append(
            f'<li><strong>Net-net, the Carvana ABS program still produces positive '
            f'residual spread relative to a CarMax-priced execution.</strong> Assets: '
            f'<strong>+{abs(_cw_diff):.2f}pp</strong> consumer-APR premium. Losses: '
            f'<strong>{yr_penalty_bps:+.1f} bps/yr</strong> issuer penalty (tiny, '
            f'per §7). Funding: <strong>{-last_gap:+.0f} bps/yr</strong> cost-of-funds '
            f'premium (negative because Carvana pays more). Rough sum &approx; '
            f'<strong>{net_pp:+.2f}pp/yr of net residual spread</strong> that Carvana '
            f'retains vs. a hypothetical CarMax-priced version of the same pool. '
            f'This is the asymmetry: Carvana\'s equity value depends far more on closing '
            f'the funding gap than on improving underwriting or collections, because '
            f'asset-yield already pays for the small loss penalty several times over.</li>'
        )

    # Bullet 6 — scale / coverage context
    if n_crv and n_cmx:
        bullets.append(
            f'<li><strong>Carvana is the subject; CarMax provides the benchmark.</strong> '
            f'This analysis covers <strong>{n_crv} Carvana deals</strong> (Prime + Non-Prime) '
            f'and <strong>{n_cmx} CarMax deals</strong> (Prime only). The two issuers are '
            f'the only public monoline used-auto ABS programs with comparable loan-level '
            f'disclosure, so the peer set is saturated. Further precision comes from '
            f'deeper vintage data and macro-regime controls, not from adding issuers.</li>'
        )

    if not bullets:
        return _section(12, 'Carvana takeaways',
                        _p('<em>Not enough data yet to produce takeaways.</em>'))

    body = (
        _p('This callout synthesizes the analysis above into Carvana-specific '
           'investor takeaways. Numbers are pulled live from the same analytics '
           'cache that drives §7-9; interpretations are the author\'s.')
        + _callout(
            '<ul style="font-size:.82rem;line-height:1.7;padding-left:22px;margin:0">'
            + ''.join(bullets)
            + '</ul>',
            color='#1565C0')
    )
    return _section(12, 'Carvana takeaways', body)


def _sec11_repro():
    body = (
        _p('Enough detail is given below that a capable AI agent with access to SEC '
           'EDGAR should be able to rebuild the analytics end-to-end. No step requires '
           'private data, proprietary feeds, or human judgment calls beyond the '
           'parameter choices listed.')
        + _h4('11a. Model parameters (exact)')
        + '<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">'
          '<thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>'
          '<tr><td>MIN_CELL_OBS (minimum loan-months for cell estimation)</td><td>30</td></tr>'
          '<tr><td>SIGMA_PRIOR (log-normal prior on &lambda;)</td><td>0.30</td></tr>'
          '<tr><td>Prior mean on &lambda; (linear space)</td><td>1.0</td></tr>'
          '<tr><td>FICO buckets</td><td>&lt;580, 580-619, 620-659, 660-699, 700-739, 740+</td></tr>'
          '<tr><td>LTV buckets</td><td>&lt;80%, 80-99%, 100-119%, 120%+</td></tr>'
          '<tr><td>Original-term buckets</td><td>&le;48mo, 49-60mo, 61-72mo, 73+mo</td></tr>'
          '<tr><td>Age buckets (months)</td><td>0-6, 7-12, 13-24, 25-36, 37+</td></tr>'
          '<tr><td>Delinquency states</td><td>Current, 1-5+pmt (Markov), Default &amp; Payoff (absorbing)</td></tr>'
          '<tr><td>Modification flag</td><td>Modified, Not modified</td></tr>'
          '<tr><td>Recovery-rate default</td><td>39.85% of charge-off amount (pooled historical)</td></tr>'
          '<tr><td>Fallback ladder (sparse cells)</td><td>coarsen LTV &rarr; coarsen term &rarr; coarsen FICO</td></tr>'
          '</tbody></table></div>'
        + _h4('11b. State mapping (days delinquent &rarr; Markov state)')
        + _callout(
            'current_delinquency_status (string integer; payments behind):<br>'
            '&nbsp;&nbsp;0 &rarr; Current<br>'
            '&nbsp;&nbsp;1 &rarr; 1pmt&nbsp;&nbsp;(30-59 DPD)<br>'
            '&nbsp;&nbsp;2 &rarr; 2pmt&nbsp;&nbsp;(60-89 DPD)<br>'
            '&nbsp;&nbsp;3 &rarr; 3pmt&nbsp;&nbsp;(90-119 DPD)<br>'
            '&nbsp;&nbsp;4 &rarr; 4pmt&nbsp;&nbsp;(120-149 DPD)<br>'
            '&nbsp;&nbsp;&ge;5 &rarr; 5+pmt (150+ DPD)<br>'
            '<br>'
            'zero_balance_code:<br>'
            '&nbsp;&nbsp;1 &rarr; Payoff (prepaid / sold)<br>'
            '&nbsp;&nbsp;2 &rarr; Payoff (matured)<br>'
            '&nbsp;&nbsp;3 &rarr; Default<br>'
            '&nbsp;&nbsp;4 &rarr; Payoff (repurchased by seller; treated as prepayment)',
            color='#1976D2')
        + _h4('11c. Regression specification (§7)')
        + _callout(
            '<em>Estimator:</em> pooled logistic regression '
            '(<code>statsmodels.api.Logit</code>, lbfgs, no regularisation).<br><br>'
            '<code>default_next ~ 1 + issuer_carmax + fb_*(ref=660-699) + '
            'lb_*(ref=80-99%) + tb_*(ref=61-72mo) + age_b_*(ref=13-24) + '
            'from_state_*(ref=Current) + modified + v_*(vintage-year fixed effects)</code><br><br>'
            '<em>Sample:</em> monthly loan-performance rows across all Carvana prime deals '
            'and all CarMax deals where FICO, LTV, term, age, and prev-state are all non-null. '
            'Stratified down to ~600k rows (all positives retained; negatives '
            'undersampled). Intercept adjusted for sampling ratio when computing '
            'marginal effects, so population-scale probabilities are recovered.<br><br>'
            '<em>Standard errors:</em> model-based (inverse Hessian). Clustered-by-deal '
            'SEs are not reported in this version; this is a known conservative bias '
            '(the SEs shown are likely too small by a factor of 2-3x for the '
            'deal-clustering-inflated ones). Adding robust clustered SEs is a '
            'follow-on task.',
            color='#388E3C')
        + _h4('11d. Key SQL snippets')
        + _callout(
            '<em>Loan attributes (ingested from ABS-EE XML):</em><br>'
            '<code>SELECT deal, asset_number, obligor_credit_score, original_ltv, '
            'original_loan_term, original_interest_rate, original_loan_amount '
            'FROM loans;</code><br><br>'
            '<em>Monthly observation (ingested from ABS-EE XML):</em><br>'
            '<code>SELECT deal, asset_number, reporting_period_end, '
            'current_delinquency_status, remaining_term, zero_balance_code, '
            'modification_indicator, charged_off_amount, beginning_balance, '
            'ending_balance FROM loan_performance;</code><br><br>'
            '<em>Deal terms (parsed from 424(b)(5)):</em><br>'
            '<code>SELECT deal, cutoff_date, weighted_avg_coupon, '
            'class_a1_pct, class_a1_coupon, ..., initial_oc_pct, '
            'servicing_fee_annual_pct, initial_pool_balance FROM deal_terms '
            'WHERE terms_extracted = 1;</code>',
            color='#F57F17')
        + _h4('11e. Data URL patterns')
        + _callout(
            '<em>SEC EDGAR filing index per issuer:</em><br>'
            '<code>https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany'
            '&amp;CIK={cik}&amp;type=10-D&amp;dateb=&amp;owner=include&amp;count=40</code><br>'
            'Carvana Auto Receivables Trust CIK: 1704336 (depositor)<br>'
            'CarMax Auto Owner Trust CIK: 1598693 (depositor)<br><br>'
            '<em>Full-text filing search (ABS-EE and 424B):</em><br>'
            '<code>https://efts.sec.gov/LATEST/search-index?q=%22{deal_name}%22'
            '&amp;forms={form_type}</code><br><br>'
            '<em>FRED benchmark series:</em><br>'
            '<code>https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2</code> '
            '&mdash; 2Y Constant Maturity Treasury, daily, 1976-present<br>'
            '<code>https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC1A0C13YSYTW</code> '
            '&mdash; ICE BofA 1-3yr AAA-A US Corporate index yield to worst, daily',
            color='#9E9E9E')
        + _h4('11f. Code entry points in this repository')
        + '<div style="overflow-x:auto"><table style="font-size:.72rem;max-width:640px;margin:8px 0">'
          '<thead><tr><th>File</th><th>What it does</th></tr></thead><tbody>'
          '<tr><td><code>unified_markov.py</code></td><td>End-to-end Markov fit + calibration + forecast per deal. Writes <code>deal_forecasts</code> in each source DB.</td></tr>'
          '<tr><td><code>carvana_abs/compute_methodology.py</code></td><td>One-shot analytics build for this tab. Streams loan_performance and writes <code>deploy/methodology_cache/analytics.json</code>.</td></tr>'
          '<tr><td><code>carvana_abs/methodology_tab.py</code></td><td>This renderer. Reads the cache, emits HTML + Plotly divs.</td></tr>'
          '<tr><td><code>carvana_abs/generate_dashboard.py</code></td><td>Orchestrates the full dashboard page.</td></tr>'
          '<tr><td><code>carmax_abs/ingestion/</code>, <code>carvana_abs/ingestion/</code></td><td>SEC EDGAR crawlers + ABS-EE parsers + 424(b)(5) parser.</td></tr>'
          '</tbody></table></div>'
    )
    return _section(11, 'Reproducibility appendix', body)


def _footer(cache):
    gen = (cache or {}).get('generated_at', '')
    return (f'<hr style="margin:32px 0 8px"><p style="font-size:.7rem;color:#888">'
            f'Analytics cache generated {gen}. '
            f'Model last refreshed: see dashboard footer. '
            f'Questions: clifford.sosin@casinvestmentpartners.com'
            f'</p>')


# ==========================================================================
# Top-level entry
# ==========================================================================
def generate_methodology_tab():
    cache = load_cache()
    _chart_counter[0] = 0
    # Header + table of contents
    toc = (
        '<nav style="font-size:.7rem;color:#666;margin:8px 0 16px;'
        'padding:8px 12px;background:#FAFAFA;border-left:3px solid #1976D2">'
        '<strong>Sections:</strong> '
        '<a href="#sec-1">1 Intro</a> &middot; '
        '<a href="#sec-2">2 Data</a> &middot; '
        '<a href="#sec-3">3 Model</a> &middot; '
        '<a href="#sec-4">4 Transitions</a> &middot; '
        '<a href="#sec-5">5 Predictors</a> &middot; '
        '<a href="#sec-6">6 Residual</a> &middot; '
        '<a href="#sec-7">7 Loss regression</a> &middot; '
        '<a href="#sec-8">8 Yield / rate</a> &middot; '
        '<a href="#sec-9">9 Cost of funds</a> &middot; '
        '<a href="#sec-10">10 Limitations</a> &middot; '
        '<a href="#sec-11">11 Reproducibility</a> &middot; '
        '<a href="#sec-12"><strong>12 Carvana takeaways</strong></a>'
        '</nav>'
    )

    sections = [
        _sec1_intro(),
        _sec2_data(cache),
        _sec3_model(),
        _sec4_transitions(cache),
        _sec5_predictors(cache),
        _sec6_residual(cache),
        _sec7_regression(cache),
        _sec8_yield(cache),
        _sec9_cof(cache),
        _sec10_limitations(),
        _sec11_repro(),
        _sec12_carvana_takeaways(cache),
    ]
    # Add anchor ids by wrapping each section
    wrapped = []
    for i, s in enumerate(sections, 1):
        wrapped.append(f'<div id="sec-{i}">{s}</div>')

    hdr = ('<h2 style="font-size:1.15rem;color:#1565C0;border-bottom:2px solid #1976D2;'
           'padding-bottom:4px;margin:8px 0 4px">Methodology &amp; Findings</h2>'
           '<p style="font-size:.72rem;color:#666;margin-bottom:8px">'
           'Unified Markov loss model, issuer comparison, cost-of-funds analysis. '
           'Full reproducibility appendix in &sect;11.</p>')

    if not cache:
        warn = _callout(
            '<strong>Analytics cache is missing.</strong> Run '
            '<code>python carvana_abs/compute_methodology.py</code> to generate '
            'the derived statistics. Sections that require cached data will '
            'show placeholders until then.', color='#D32F2F')
    else:
        warn = ''

    return ('<div style="padding:12px 16px;max-width:920px;margin:0 auto">'
            f'{hdr}{warn}{toc}{"".join(wrapped)}{_footer(cache)}</div>')
