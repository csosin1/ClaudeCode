#!/usr/bin/env python3
"""Conditional-Markov loss forecast for Carvana ABS pools.

Replaces the time-homogeneous Markov absorption with a forward
simulation driven by:
  • State-transition probabilities binned by (tier, current_state,
    age_bucket, FICO_bucket, LTV_bucket, modified_flag)
  • Empirical balance trajectory (current/original) by (tier,
    term_bucket, age) — captures real-world amort, partial prepays,
    extensions
  • LGD lookup by (tier, age_bucket, FICO_bucket, LTV_bucket)

Per loan, simulate state-vector forward month-by-month to original
term, accumulating expected loss = mass-into-Default × balance × LGD.
Sum across loans per deal.

Outputs are stored in dashboard.db's model_results table under key
'conditional_markov' so generate_dashboard can render the build-up
table without re-running the simulation.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
PRIME_DEALS = ["2020-P1", "2021-P1", "2021-P2", "2022-P1", "2022-P2",
               "2022-P3", "2024-P2", "2024-P3", "2024-P4",
               "2025-P2", "2025-P3", "2025-P4"]
NONPRIME_DEALS = ["2021-N1", "2021-N2", "2021-N3", "2021-N4"]
TIER_OF_DEAL = {**{d: "Prime" for d in PRIME_DEALS},
                **{d: "NonPrime" for d in NONPRIME_DEALS}}

STATES = [0, 1, 2, 3, 4, 5]   # current_delinquency_status, capped at 5
N_STATES = 6
ABSORBING = ["Default", "Payoff"]

AGE_BUCKETS = [(0, 6), (6, 12), (12, 24), (24, 36), (36, 48), (48, 60), (60, 999)]
FICO_BUCKETS = [(0, 620), (620, 660), (660, 700), (700, 740), (740, 999)]
LTV_BUCKETS  = [(0, 0.90), (0.90, 1.00), (1.00, 1.10), (1.10, 1.20), (1.20, 99)]
TERM_BUCKETS = [36, 48, 60, 72, 84]

MIN_CELL_OBS = 30  # below this, fall back to coarser stratum

CARVANA_DB = "/opt/abs-dashboard/carvana_abs/db/carvana_abs.db"
DASHBOARD_DB = "/opt/abs-dashboard/carvana_abs/db/dashboard.db"

# Chronological sort key for "MM-DD-YYYY" date strings
SORT_KEY = ("substr(reporting_period_end,7,4)||"
            "substr(reporting_period_end,1,2)||"
            "substr(reporting_period_end,4,2)")


# ── Utilities ──────────────────────────────────────────────────────────

def _bucket(value, bins):
    for i, (lo, hi) in enumerate(bins):
        if lo <= value < hi:
            return i
    return len(bins) - 1


def _term_bucket(term):
    if term is None:
        return 60  # default bucket
    for t in TERM_BUCKETS:
        if term <= t:
            return t
    return TERM_BUCKETS[-1]


def _state(cds):
    if cds is None:
        return None
    try:
        return min(int(cds), 5)
    except (ValueError, TypeError):
        return None


def _modified(mod_indicator):
    if mod_indicator is None:
        return 0
    s = str(mod_indicator).strip().lower()
    return 1 if s in ("1", "y", "yes", "true", "t") else 0


def _parse_date_mdy(s):
    """Origination dates are MM/YYYY in this dataset (no day); period dates
    can be MM-DD-YYYY or YYYY-MM-DD. Try a few formats."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%m/%Y", "%m-%Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except (ValueError, TypeError):
            continue
    return None


# ── Loan covariates loader ────────────────────────────────────────────

def load_loan_covariates(conn, deals):
    """Returns dict[(deal, asset_number)] = (tier, fico, ltv, term, orig_amount, orig_dt)."""
    qm = ",".join(["?"] * len(deals))
    cur = conn.execute(f"""
        SELECT deal, asset_number, obligor_credit_score, original_ltv,
               original_loan_term, original_loan_amount, origination_date
        FROM loans WHERE deal IN ({qm})""", deals)
    out = {}
    for deal, asset, fico, ltv, term, amount, orig_date in cur:
        if not asset:
            continue
        tier = TIER_OF_DEAL.get(deal)
        if tier is None:
            continue
        out[(deal, asset)] = {
            "tier": tier,
            "fico": float(fico) if fico is not None else None,
            "ltv": float(ltv) if ltv is not None else None,
            "term": int(term) if term is not None else None,
            "term_bucket": _term_bucket(int(term)) if term is not None else 60,
            "orig_amount": float(amount) if amount is not None else None,
            "orig_dt": _parse_date_mdy(orig_date),
        }
    return out


# ── Pass 1: build transitions, paydown curves, LGD samples ────────────

def build_aggregates(conn, deals, covariates):
    """Single streaming pass over loan_performance to build all empirical
    aggregates. Memory-efficient: only state per (deal, asset) is held.
    """
    # Per-loan terminal: did this loan end in default? (charged_off_amount > 0
    # in any row, equivalent to membership in loan_loss_summary > 0 verified
    # earlier).
    qm = ",".join(["?"] * len(deals))
    defaulted = set()
    for deal, asset in conn.execute(
            f"SELECT deal, asset_number FROM loan_loss_summary "
            f"WHERE total_chargeoff > 0 AND deal IN ({qm})", deals):
        defaulted.add((deal, asset))
    paidoff = set()
    for deal, asset in conn.execute(
            f"SELECT DISTINCT deal, asset_number FROM loan_performance "
            f"WHERE deal IN ({qm}) AND zero_balance_code IS NOT NULL", deals):
        if (deal, asset) not in defaulted:
            paidoff.add((deal, asset))
    logger.info(f"  defaulted: {len(defaulted):,}  paid-off: {len(paidoff):,}")

    # Aggregates
    # Transitions: trans[(tier, state, age_b, fico_b, ltv_b, mod)][to_state] = count
    trans = defaultdict(lambda: defaultdict(int))
    # Paydown: paydown[(tier, term_bucket, age_int)][0]=sum_ratio, [1]=count
    paydown_perf = defaultdict(lambda: [0.0, 0])
    paydown_mod  = defaultdict(lambda: [0.0, 0])
    # LGD samples per defaulted loan: keyed by (tier, age_b, fico_b, ltv_b)
    lgd_samples = defaultdict(lambda: [0.0, 0.0, 0])  # [sum_co, sum_rec, count]

    # Also record current snapshot per loan = latest state + balance + age,
    # for the forecast pass.
    latest_state = {}

    cur = conn.execute(f"""
        SELECT deal, asset_number, current_delinquency_status,
               zero_balance_code, charged_off_amount, recoveries,
               ending_balance, modification_indicator,
               substr(reporting_period_end,7,4)||'-'||
               substr(reporting_period_end,1,2)||'-'||
               substr(reporting_period_end,4,2) AS iso_dt
        FROM loan_performance WHERE deal IN ({qm})
        ORDER BY deal, asset_number, {SORT_KEY}""", deals)

    prev_key = None
    prev_state = None
    rows = 0
    for deal, asset, cds, zbc, coa, rec, end_bal, mod_ind, iso_dt in cur:
        rows += 1
        key = (deal, asset)
        cov = covariates.get(key)
        if not cov or cov.get("orig_dt") is None:
            continue
        period_dt = None
        if iso_dt:
            try:
                period_dt = datetime.strptime(iso_dt, "%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        if period_dt is None:
            continue
        age_months = max(0, int((period_dt - cov["orig_dt"]).days / 30.4))
        age_b = _bucket(age_months, AGE_BUCKETS)
        fico_b = _bucket(cov["fico"] or 0, FICO_BUCKETS)
        ltv_b = _bucket(cov["ltv"] or 0, LTV_BUCKETS)
        is_modified = _modified(mod_ind)

        # Loan crossover: flush previous loan terminal
        if key != prev_key:
            if prev_key is not None and prev_state is not None:
                t = "Default" if prev_key in defaulted else (
                    "Payoff" if prev_key in paidoff else None)
                if t:
                    pcov = covariates.get(prev_key)
                    if pcov:
                        pcell = (pcov["tier"], prev_state, prev_age_b,
                                 prev_fico_b, prev_ltv_b, prev_mod)
                        trans[pcell][t] += 1
            prev_key = key
            prev_state = None

        # Skip rows that mark a terminal state for transition-counting purposes
        is_terminal_row = (zbc is not None and str(zbc) in ("1", "2", "3", "4")) or \
                          (coa is not None and coa > 0)

        if is_terminal_row:
            # If charged-off this row: record LGD sample (chargeoff value is in coa)
            if (key in defaulted) and (coa is not None and coa > 0):
                lgd_key = (cov["tier"], age_b, fico_b, ltv_b)
                lgd_samples[lgd_key][0] += float(coa)
                lgd_samples[lgd_key][1] += float(rec or 0)
                lgd_samples[lgd_key][2] += 1
            # don't advance state from this row
            continue

        cur_state = _state(cds)
        if cur_state is None:
            continue

        # Paydown sample (only state 0, performing)
        if cov["orig_amount"] and end_bal is not None and float(end_bal) > 0:
            ratio = float(end_bal) / cov["orig_amount"]
            if 0 < ratio < 1.5:  # filter wild outliers
                pkey = (cov["tier"], cov["term_bucket"], age_months)
                if cur_state == 0 and not is_modified:
                    paydown_perf[pkey][0] += ratio
                    paydown_perf[pkey][1] += 1
                if is_modified:
                    paydown_mod[pkey][0] += ratio
                    paydown_mod[pkey][1] += 1

        # Transition from prev_state to cur_state, attributed to prev cell
        if prev_state is not None:
            pcov = covariates.get(prev_key) or cov
            pcell = (pcov["tier"], prev_state, prev_age_b, prev_fico_b,
                     prev_ltv_b, prev_mod)
            trans[pcell][cur_state] += 1

        # Save last snapshot (used for the per-loan forecast pass)
        latest_state[key] = {
            "state": cur_state,
            "balance": float(end_bal) if end_bal is not None else 0.0,
            "age_months": age_months,
            "modified": is_modified,
            "tier": cov["tier"],
            "fico_b": fico_b,
            "ltv_b": ltv_b,
            "term_bucket": cov["term_bucket"],
            "orig_amount": cov["orig_amount"],
            "term": cov["term"],
            "is_active": True,  # if zero_balance_code never set in this loan, it's active
        }
        prev_state = cur_state
        prev_age_b = age_b
        prev_fico_b = fico_b
        prev_ltv_b = ltv_b
        prev_mod = is_modified

    # Final loan flush
    if prev_key is not None and prev_state is not None:
        t = "Default" if prev_key in defaulted else (
            "Payoff" if prev_key in paidoff else None)
        if t:
            pcov = covariates.get(prev_key)
            if pcov:
                pcell = (pcov["tier"], prev_state, prev_age_b, prev_fico_b,
                         prev_ltv_b, prev_mod)
                trans[pcell][t] += 1

    # Drop terminated loans from latest_state — only keep currently-active
    for key in list(latest_state):
        if key in defaulted or key in paidoff:
            del latest_state[key]

    logger.info(f"  rows scanned: {rows:,}")
    logger.info(f"  transition cells: {len(trans):,}  paydown cells (perf): "
                f"{len(paydown_perf):,}  LGD cells: {len(lgd_samples):,}")
    logger.info(f"  active loans for forecast: {len(latest_state):,}")
    return trans, paydown_perf, paydown_mod, lgd_samples, latest_state


# ── Cell-level transition matrix with smoothing fallback ──────────────

def cell_transition_matrix(trans, tier, state, age_b, fico_b, ltv_b, mod):
    """Try fully-stratified cell. Fall back to coarser strata if too sparse."""
    def _make(cell):
        d = trans.get(cell)
        if not d:
            return None, 0
        total = sum(d.values())
        if total < MIN_CELL_OBS:
            return None, total
        row = np.zeros(N_STATES + 2)  # 6 states + Default + Payoff
        for k, v in d.items():
            if isinstance(k, int):
                row[k] = v
            elif k == "Default":
                row[N_STATES] = v
            elif k == "Payoff":
                row[N_STATES + 1] = v
        return row / total, total

    # Try most-specific first, then fallback
    ladder = [
        (tier, state, age_b, fico_b, ltv_b, mod),
        (tier, state, age_b, fico_b, ltv_b, 0),       # drop modified flag
        (tier, state, age_b, fico_b, "any", mod),     # drop LTV
        (tier, state, age_b, "any", "any", mod),      # drop FICO + LTV
        (tier, state, age_b, "any", "any", 0),
        (tier, state, "any", "any", "any", 0),        # tier+state only
    ]
    # Build "any" aggregates lazily on first request
    return _resolve_ladder(trans, ladder, _make)


_AGG_CACHE = {}


def _resolve_ladder(trans, ladder, _make):
    """Walk fallback ladder. For "any" wildcards, sum across that dimension."""
    for cell in ladder:
        if "any" not in cell:
            row, n = _make(cell)
            if row is not None:
                return row, n
        else:
            # Aggregate across wildcard dimension(s)
            if cell in _AGG_CACHE:
                row, n = _AGG_CACHE[cell]
                if row is not None and n >= MIN_CELL_OBS:
                    return row, n
                continue
            agg = defaultdict(int)
            tier, state, age_b, fico_b, ltv_b, mod = cell
            for k, d in trans.items():
                kt, ks, kab, kfb, klb, km = k
                if kt != tier or ks != state: continue
                if age_b != "any" and kab != age_b: continue
                if fico_b != "any" and kfb != fico_b: continue
                if ltv_b != "any" and klb != ltv_b: continue
                if mod != "any" and km != mod: continue
                for outk, v in d.items():
                    agg[outk] += v
            total = sum(agg.values())
            if total >= MIN_CELL_OBS:
                row = np.zeros(N_STATES + 2)
                for k, v in agg.items():
                    if isinstance(k, int): row[k] = v
                    elif k == "Default": row[N_STATES] = v
                    elif k == "Payoff": row[N_STATES + 1] = v
                row = row / total
                _AGG_CACHE[cell] = (row, total)
                return row, total
            _AGG_CACHE[cell] = (None, total)
    return None, 0


# ── Paydown curve & LGD lookup ────────────────────────────────────────

def build_paydown_curves(paydown_perf, paydown_mod):
    """Returns (perf_curve, mod_curve) where curve[(tier, term_bucket)] is a
    sorted list of (age, ratio) tuples. Smooth missing ages by linear
    interpolation between observed points."""
    def _curve(samples):
        out = defaultdict(list)
        for (tier, tb, age), (s, n) in samples.items():
            if n < 5: continue  # need a few samples to trust the average
            out[(tier, tb)].append((age, s / n))
        # Sort by age
        for k in out: out[k].sort()
        return dict(out)
    return _curve(paydown_perf), _curve(paydown_mod)


def lookup_paydown(curve, tier, term_bucket, age):
    """Linear interpolation in the paydown curve at (tier, term_bucket, age)."""
    pts = curve.get((tier, term_bucket))
    if not pts:
        # Fallback: any term bucket for this tier
        for tb in TERM_BUCKETS:
            if (tier, tb) in curve:
                pts = curve[(tier, tb)]
                break
    if not pts:
        return 1.0  # no data → no amort (overstates)
    # Find bracketing points
    if age <= pts[0][0]: return pts[0][1]
    if age >= pts[-1][0]: return pts[-1][1]
    for i in range(len(pts) - 1):
        a1, r1 = pts[i]
        a2, r2 = pts[i + 1]
        if a1 <= age <= a2:
            if a2 == a1: return r1
            return r1 + (r2 - r1) * (age - a1) / (a2 - a1)
    return pts[-1][1]


def build_lgd_lookup(lgd_samples):
    """Returns lgd[(tier, age_b, fico_b, ltv_b)] = mean LGD with fallbacks."""
    out = {}
    for k, (sco, srec, n) in lgd_samples.items():
        if n < 5 or sco <= 0: continue
        out[k] = max(0.0, min(1.0, 1.0 - srec / sco))
    return out


def lookup_lgd(lgd, tier, age_b, fico_b, ltv_b):
    """Try most-specific cell, then coarser fallbacks."""
    for k in [
        (tier, age_b, fico_b, ltv_b),
        (tier, age_b, fico_b, "any"),
        (tier, age_b, "any", "any"),
        (tier, "any", "any", "any"),
    ]:
        if "any" not in k:
            v = lgd.get(k)
            if v is not None: return v
        else:
            # Aggregate across wildcards
            if k in _LGD_AGG_CACHE: return _LGD_AGG_CACHE[k]
            tier_, age_b_, fico_b_, ltv_b_ = k
            sco = srec = n = 0
            for kk, vv in lgd.items():
                kt, ka, kf, kl = kk
                if kt != tier_: continue
                if age_b_ != "any" and ka != age_b_: continue
                if fico_b_ != "any" and kf != fico_b_: continue
                if ltv_b_ != "any" and kl != ltv_b_: continue
                # vv is the LGD itself; we don't have raw counts here, so just average
                n += 1; sco += vv
            if n > 0:
                _LGD_AGG_CACHE[k] = sco / n
                return _LGD_AGG_CACHE[k]
    return 0.55  # last-resort default


_LGD_AGG_CACHE = {}


# ── Per-loan forward simulation ───────────────────────────────────────

def forecast_loan(loan, trans, perf_curve, mod_curve, lgd_lookup,
                  cum_severity_by_tier=None):
    """Walk forward month-by-month from loan's current state to original term.
    Returns (expected_loss, variance_proxy, terminal_default_prob)."""
    tier = loan["tier"]
    state = loan["state"]
    age = loan["age_months"]
    term = loan["term"] or 60
    months_remaining = max(1, term - age)
    fico_b = loan["fico_b"]
    ltv_b = loan["ltv_b"]
    mod = loan["modified"]
    orig = loan["orig_amount"] or loan["balance"]
    tb = loan["term_bucket"]
    curve = mod_curve if mod else perf_curve

    # State vector (transient + 2 absorbing)
    sv = np.zeros(N_STATES + 2)
    sv[state] = 1.0

    expected_loss = 0.0
    variance = 0.0
    cur_age = age
    for step in range(months_remaining):
        cur_age += 1
        age_b = _bucket(cur_age, AGE_BUCKETS)
        # Build transition matrix for this month: rows are CURRENT transient states 0..5
        Q = np.zeros((N_STATES + 2, N_STATES + 2))
        # Absorbing rows are identity
        Q[N_STATES, N_STATES] = 1.0
        Q[N_STATES + 1, N_STATES + 1] = 1.0
        for s in STATES:
            row, n = cell_transition_matrix(trans, tier, s, age_b, fico_b, ltv_b, mod)
            if row is None:
                # Stay-in-place fallback
                Q[s, s] = 1.0
            else:
                Q[s, :] = row
        new_sv = sv @ Q
        # Newly absorbed mass into Default this step
        new_def_mass = new_sv[N_STATES] - sv[N_STATES]
        if new_def_mass > 0:
            # Look up balance fraction at this age
            ratio = lookup_paydown(curve, tier, tb, cur_age)
            balance_at_default = orig * ratio
            lgd = lookup_lgd(lgd_lookup, tier, age_b, fico_b, ltv_b)
            loss = new_def_mass * balance_at_default * lgd
            expected_loss += loss
            # Variance proxy (Bernoulli-ish): p*(1-p) * (balance*lgd)^2
            variance += new_def_mass * (1 - new_def_mass) * (balance_at_default * lgd) ** 2
        sv = new_sv
    return expected_loss, variance


# ── Main ──────────────────────────────────────────────────────────────

def run(carvana_db=CARVANA_DB, dashboard_db=DASHBOARD_DB):
    """Run the full pipeline and store results in dashboard_db."""
    conn = sqlite3.connect(carvana_db)
    deals = list(TIER_OF_DEAL.keys())
    logger.info(f"Loading covariates for {len(deals)} deals...")
    covariates = load_loan_covariates(conn, deals)
    logger.info(f"  loaded {len(covariates):,} loan covariates")

    logger.info("Building empirical aggregates (transitions, paydown, LGD)...")
    trans, paydown_perf, paydown_mod, lgd_samples, latest = build_aggregates(
        conn, deals, covariates)
    perf_curve, mod_curve = build_paydown_curves(paydown_perf, paydown_mod)
    lgd_lookup = build_lgd_lookup(lgd_samples)
    logger.info(f"  perf paydown bins: {sum(len(v) for v in perf_curve.values()):,}  "
                f"mod paydown bins: {sum(len(v) for v in mod_curve.values()):,}")
    logger.info(f"  LGD cells: {len(lgd_lookup):,}")

    logger.info("Running per-loan forecast...")
    deal_totals = defaultdict(lambda: {"expected_loss": 0.0, "variance": 0.0,
                                       "active_loans": 0, "active_balance": 0.0,
                                       "dq_loss": 0.0, "perf_loss": 0.0,
                                       "dq_balance": 0.0, "perf_balance": 0.0})
    for (deal, asset), loan in latest.items():
        el, var = forecast_loan(loan, trans, perf_curve, mod_curve, lgd_lookup)
        d = deal_totals[deal]
        d["expected_loss"] += el
        d["variance"] += var
        d["active_loans"] += 1
        d["active_balance"] += loan["balance"]
        if loan["state"] == 0:
            d["perf_loss"] += el
            d["perf_balance"] += loan["balance"]
        else:
            d["dq_loss"] += el
            d["dq_balance"] += loan["balance"]

    # Realized: pull from dashboard.db cert lookup
    sys.path.insert(0, "/opt/abs-dashboard")
    from carvana_abs.default_model import _cert_totals_lookup
    by_deal = {}
    for deal in deals:
        cert = _cert_totals_lookup(deal, carvana_db)
        cum_net = cert.get("cum_net_losses") or 0
        d = deal_totals.get(deal, {})
        ev = d.get("expected_loss", 0)
        var = d.get("variance", 0)
        sigma = float(np.sqrt(var)) if var > 0 else 0
        by_deal[deal] = {
            "active_loans": d.get("active_loans", 0),
            "active_balance": round(d.get("active_balance", 0), 2),
            "realized": round(cum_net, 2),
            "dq_pending": round(d.get("dq_loss", 0), 2),
            "performing_future": round(d.get("perf_loss", 0), 2),
            "total_expected": round(cum_net + ev, 2),
            "total_minus_1sd": round(cum_net + max(0, ev - sigma), 2),
            "total_plus_1sd": round(cum_net + ev + sigma, 2),
            "forecast_only": round(ev, 2),
            "forecast_sigma": round(sigma, 2),
        }
        logger.info(f"  {deal}: realized=${cum_net/1e6:.1f}M  forecast=${ev/1e6:.1f}M  "
                    f"σ=${sigma/1e6:.1f}M  total=${(cum_net+ev)/1e6:.1f}M")

    # Reference table: average P(default | state, age, FICO) for sanity check.
    # Compute one-step Default probability from fully-stratified cells, then
    # average across LTV / mod.
    p_def_ref = {}
    for tier in ["Prime", "NonPrime"]:
        rows = []
        for state_idx, state_lbl in enumerate(["Curr", "1pmt", "2pmt", "3pmt", "4pmt", "5+pmt"]):
            for age_b in range(len(AGE_BUCKETS)):
                age_lbl = f"{AGE_BUCKETS[age_b][0]}-{AGE_BUCKETS[age_b][1]}mo"
                for fico_b in range(len(FICO_BUCKETS)):
                    fico_lbl = (f"<{FICO_BUCKETS[fico_b][1]}" if fico_b == 0
                                else f"{FICO_BUCKETS[fico_b][0]}+")
                    row, n = cell_transition_matrix(trans, tier, state_idx, age_b, fico_b, "any", "any")
                    if row is not None and n > 0:
                        rows.append({"state": state_lbl, "age": age_lbl,
                                     "fico": fico_lbl, "n": int(n),
                                     "p_default_1mo": round(float(row[N_STATES]), 6),
                                     "p_payoff_1mo": round(float(row[N_STATES + 1]), 6)})
        p_def_ref[tier] = rows[:200]   # cap to avoid bloating the JSON

    out = {
        "by_deal": by_deal,
        "tier_of_deal": TIER_OF_DEAL,
        "p_default_reference": p_def_ref,
        "lgd_avg_by_tier": {
            tier: round(np.mean([v for k, v in lgd_lookup.items() if k[0] == tier]), 4)
                  if any(k[0] == tier for k in lgd_lookup) else 0.55
            for tier in ["Prime", "NonPrime"]
        },
    }

    # Persist into dashboard.db
    dconn = sqlite3.connect(dashboard_db)
    dconn.execute("CREATE TABLE IF NOT EXISTS model_results (key TEXT PRIMARY KEY, value TEXT)")
    dconn.execute("INSERT OR REPLACE INTO model_results VALUES (?, ?)",
                  ("conditional_markov", json.dumps(out)))
    dconn.commit()
    dconn.close()
    logger.info("Saved 'conditional_markov' to dashboard.db model_results")
    return out


if __name__ == "__main__":
    run()
