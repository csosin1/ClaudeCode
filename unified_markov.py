#!/usr/bin/env python3
"""Unified conditional-Markov loss forecast: Carvana Prime + CarMax (prime model)
and Carvana Non-Prime (separate model).

Trains on ALL post-Reg-AB-II deals with loan-level data.  Each (loan, age_month)
transition observation counts equally (no deal weighting).

Streams loan_performance tables to keep peak RSS < 1.5 GB despite ~113M total
rows across both databases.

Outputs:
  - `deal_forecasts` table in each source DB (schema per spec)
  - `model_results` key in each dashboard.db (backward-compat JSON blob)
"""
from __future__ import annotations

import gc
import json
import logging
import math
import os
import resource
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────
BASE = "/opt/abs-dashboard"
CARVANA_DB = os.path.join(BASE, "carvana_abs/db/carvana_abs.db")
CARMAX_DB  = os.path.join(BASE, "carmax_abs/db/carmax_abs.db")
CARVANA_DASHBOARD_DB = os.path.join(BASE, "carvana_abs/db/dashboard.db")
CARMAX_DASHBOARD_DB  = os.path.join(BASE, "carmax_abs/db/dashboard.db")

# ── Cell dimensions ───────────────────────────────────────────────────
STATES = [0, 1, 2, 3, 4, 5]
N_STATES = 6
AGE_BUCKETS  = [(0, 6), (6, 12), (12, 24), (24, 36), (36, 48), (48, 60), (60, 999)]
FICO_BUCKETS = [(0, 620), (620, 660), (660, 700), (700, 740), (740, 999)]
LTV_BUCKETS  = [(0, 0.90), (0.90, 1.00), (1.00, 1.10), (1.10, 1.20), (1.20, 99)]
TERM_BUCKETS = [36, 48, 60, 72, 84]
MIN_CELL_OBS = 30

# ── Date sort key for MM-DD-YYYY ─────────────────────────────────────
SORT_KEY = ("substr(reporting_period_end,7,4)||"
            "substr(reporting_period_end,1,2)||"
            "substr(reporting_period_end,4,2)")


# ── Utility functions ─────────────────────────────────────────────────

def _bucket(value, bins):
    for i, (lo, hi) in enumerate(bins):
        if lo <= value < hi:
            return i
    return len(bins) - 1


def _term_bucket(term):
    if term is None:
        return 60
    for t in TERM_BUCKETS:
        if term <= t:
            return t
    return TERM_BUCKETS[-1]


def _state(cds):
    """Map current_delinquency_status (days delinquent) to payment-period buckets 0..5.

    Both Carvana and CarMax report days delinquent in this field:
      0 days       → state 0 (current)
      1-29 days    → state 1 (1 payment behind)
      30-59 days   → state 2 (2 payments behind)
      60-89 days   → state 3
      90-119 days  → state 4
      120+ days    → state 5
    """
    if cds is None:
        return None
    try:
        days = int(cds)
    except (ValueError, TypeError):
        return None
    if days == 0:
        return 0
    # Convert days to 30-day payment periods, capped at 5
    return min((days - 1) // 30 + 1, 5)


def _modified(mod_indicator):
    if mod_indicator is None:
        return 0
    s = str(mod_indicator).strip().lower()
    return 1 if s in ("1", "y", "yes", "true", "t") else 0


def _parse_date(s):
    """Parse MM/YYYY, MM-DD-YYYY, YYYY-MM-DD date strings."""
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%m/%Y", "%m-%Y", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


# ── Deal classification ──────────────────────────────────────────────

def classify_deals():
    """Return (prime_deals, nonprime_deals) as lists of (db_path, deal, issuer)."""
    prime, nonprime = [], []

    # Carvana
    conn = sqlite3.connect(CARVANA_DB)
    carvana_deals = [r[0] for r in conn.execute(
        "SELECT DISTINCT deal FROM loans ORDER BY deal").fetchall()]
    conn.close()
    for d in carvana_deals:
        if "-N" in d:
            nonprime.append((CARVANA_DB, d, "Carvana"))
        else:
            prime.append((CARVANA_DB, d, "Carvana"))

    # CarMax — all prime
    conn = sqlite3.connect(CARMAX_DB)
    carmax_deals = [r[0] for r in conn.execute(
        "SELECT DISTINCT deal FROM loans ORDER BY deal").fetchall()]
    conn.close()
    for d in carmax_deals:
        prime.append((CARMAX_DB, d, "CarMax"))

    return prime, nonprime


# ── Load loan covariates from a DB ───────────────────────────────────

def load_covariates(db_path, deals):
    """Load (deal, asset) -> covariate dict for given deals."""
    conn = sqlite3.connect(db_path)
    qm = ",".join(["?"] * len(deals))
    out = {}
    for deal, asset, fico, ltv, term, amount, orig_date in conn.execute(
            f"SELECT deal, asset_number, obligor_credit_score, original_ltv, "
            f"original_loan_term, original_loan_amount, origination_date "
            f"FROM loans WHERE deal IN ({qm})", deals):
        if not asset:
            continue
        orig_dt = _parse_date(orig_date)
        f_fico = float(fico) if fico is not None and fico != 0 else None
        f_ltv  = float(ltv) if ltv is not None and ltv != 0 else None
        f_term = int(term) if term is not None else None
        out[(deal, asset)] = {
            "fico": f_fico,
            "ltv": f_ltv,
            "term": f_term,
            "term_bucket": _term_bucket(f_term),
            "orig_amount": float(amount) if amount is not None else None,
            "orig_dt": orig_dt,
            "fico_b": _bucket(f_fico, FICO_BUCKETS) if f_fico else None,
            "ltv_b":  _bucket(f_ltv, LTV_BUCKETS) if f_ltv else None,
        }
    conn.close()
    return out


# ── Streaming aggregation ────────────────────────────────────────────

class TransitionAggregator:
    """Accumulates transition counts, paydown samples, and LGD data.

    Processes one DB at a time in a streaming fashion — only holds per-loan
    last-state tracking in memory (not the full loan_performance table).
    """

    def __init__(self):
        self.trans = defaultdict(lambda: defaultdict(int))  # cell -> {outcome: count}
        self.paydown_perf = defaultdict(lambda: [0.0, 0])   # (term_bucket, age) -> [sum_ratio, n]
        self.paydown_mod  = defaultdict(lambda: [0.0, 0])
        self.lgd_samples  = defaultdict(lambda: [0.0, 0.0, 0])  # (age_b, fico_b, ltv_b) -> [sum_co, sum_rec, n]
        self.total_obs = 0
        self.total_loans = 0

    def ingest_db(self, db_path, deals, covariates):
        """Stream through loan_performance for given deals, accumulating aggregates."""
        conn = sqlite3.connect(db_path)
        deal_list = list(deals)
        if not deal_list:
            conn.close()
            return {}

        qm = ",".join(["?"] * len(deal_list))

        # Pre-load defaulted/paidoff sets
        defaulted = set()
        for deal, asset in conn.execute(
                f"SELECT deal, asset_number FROM loan_loss_summary "
                f"WHERE total_chargeoff > 0 AND deal IN ({qm})", deal_list):
            defaulted.add((deal, asset))

        paidoff = set()
        for deal, asset in conn.execute(
                f"SELECT DISTINCT deal, asset_number FROM loan_performance "
                f"WHERE deal IN ({qm}) AND zero_balance_code IS NOT NULL", deal_list):
            if (deal, asset) not in defaulted:
                paidoff.add((deal, asset))

        logger.info(f"  {os.path.basename(db_path)}: defaulted={len(defaulted):,} paidoff={len(paidoff):,}")

        # Streaming pass — ordered by deal, asset, period
        cur = conn.execute(f"""
            SELECT deal, asset_number, current_delinquency_status,
                   zero_balance_code, charged_off_amount, recoveries,
                   ending_balance, modification_indicator,
                   substr(reporting_period_end,7,4)||'-'||
                   substr(reporting_period_end,1,2)||'-'||
                   substr(reporting_period_end,4,2) AS iso_dt
            FROM loan_performance WHERE deal IN ({qm})
            ORDER BY deal, asset_number, {SORT_KEY}""", deal_list)

        # Per-loan tracking for current snapshot
        latest_state = {}  # (deal, asset) -> snapshot dict
        prev_key = None
        prev_state = None
        prev_age_b = prev_fico_b = prev_ltv_b = prev_mod = None
        rows = 0

        for deal, asset, cds, zbc, coa, rec, end_bal, mod_ind, iso_dt in cur:
            rows += 1
            key = (deal, asset)
            cov = covariates.get(key)
            if not cov or cov.get("orig_dt") is None:
                if key != prev_key:
                    prev_key = key
                    prev_state = None
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
            fico_b = cov["fico_b"]
            ltv_b  = cov["ltv_b"]
            is_modified = _modified(mod_ind)

            # Loan crossover: flush previous terminal
            if key != prev_key:
                if prev_key is not None and prev_state is not None:
                    t = "Default" if prev_key in defaulted else (
                        "Payoff" if prev_key in paidoff else None)
                    if t:
                        pcov = covariates.get(prev_key)
                        if pcov:
                            pcell = self._cell_key(prev_state, prev_age_b,
                                                   prev_fico_b, prev_ltv_b, prev_mod)
                            self.trans[pcell][t] += 1
                            self.total_obs += 1
                prev_key = key
                prev_state = None

            # Terminal row — record LGD, don't count as transition
            is_terminal = (zbc is not None and str(zbc) in ("1", "2", "3", "4")) or \
                          (coa is not None and coa > 0)
            if is_terminal:
                if key in defaulted and coa is not None and coa > 0:
                    lgd_key = (age_b,
                               fico_b if fico_b is not None else 2,
                               ltv_b if ltv_b is not None else 2)
                    self.lgd_samples[lgd_key][0] += float(coa)
                    self.lgd_samples[lgd_key][1] += float(rec or 0)
                    self.lgd_samples[lgd_key][2] += 1
                continue

            cur_state = _state(cds)
            if cur_state is None:
                continue

            # Paydown sample
            if cov["orig_amount"] and end_bal is not None and float(end_bal) > 0:
                ratio = float(end_bal) / cov["orig_amount"]
                if 0 < ratio < 1.5:
                    pkey = (cov["term_bucket"], age_months)
                    if cur_state == 0 and not is_modified:
                        self.paydown_perf[pkey][0] += ratio
                        self.paydown_perf[pkey][1] += 1
                    if is_modified:
                        self.paydown_mod[pkey][0] += ratio
                        self.paydown_mod[pkey][1] += 1

            # Transition from prev -> cur
            if prev_state is not None:
                pcell = self._cell_key(prev_state, prev_age_b,
                                       prev_fico_b, prev_ltv_b, prev_mod)
                self.trans[pcell][cur_state] += 1
                self.total_obs += 1

            # Update snapshot
            latest_state[key] = {
                "state": cur_state,
                "balance": float(end_bal) if end_bal is not None else 0.0,
                "age_months": age_months,
                "modified": is_modified,
                "fico_b": fico_b if fico_b is not None else 2,
                "ltv_b": ltv_b if ltv_b is not None else 2,
                "term_bucket": cov["term_bucket"],
                "orig_amount": cov["orig_amount"],
                "term": cov["term"],
                "deal": deal,
            }
            prev_state = cur_state
            prev_age_b = age_b
            prev_fico_b = fico_b if fico_b is not None else 2
            prev_ltv_b  = ltv_b if ltv_b is not None else 2
            prev_mod = is_modified

        # Final loan flush
        if prev_key is not None and prev_state is not None:
            t = "Default" if prev_key in defaulted else (
                "Payoff" if prev_key in paidoff else None)
            if t:
                pcov = covariates.get(prev_key)
                if pcov:
                    pcell = self._cell_key(prev_state, prev_age_b,
                                           prev_fico_b, prev_ltv_b, prev_mod)
                    self.trans[pcell][t] += 1
                    self.total_obs += 1

        # Tag terminal status
        for key, snap in latest_state.items():
            if key in defaulted:
                snap["status"] = "defaulted"
            elif key in paidoff:
                snap["status"] = "paidoff"
            else:
                snap["status"] = "active"

        conn.close()
        self.total_loans += len(latest_state)
        n_active = sum(1 for s in latest_state.values() if s["status"] == "active")
        logger.info(f"  {os.path.basename(db_path)}: {rows:,} perf rows, "
                    f"{len(latest_state):,} loans tracked "
                    f"(active={n_active:,}), RSS={_rss_mb():.0f} MB")
        return latest_state

    @staticmethod
    def _cell_key(state, age_b, fico_b, ltv_b, mod):
        """Cell key: (state, age_b, fico_b, ltv_b, mod).
        No tier dimension — model is trained per-tier externally.
        None covariates mapped to middle bucket (2) for fallback."""
        return (state,
                age_b,
                fico_b if fico_b is not None else 2,
                ltv_b if ltv_b is not None else 2,
                mod)


# ── Transition matrix lookup with fallback ladder ────────────────────

class MarkovModel:
    """Holds transition aggregates and provides cell lookups with fallback."""

    def __init__(self, trans, lgd_samples, paydown_perf, paydown_mod):
        self.trans = trans
        self.lgd_lookup = self._build_lgd(lgd_samples)
        self.perf_curve, self.mod_curve = self._build_paydown(paydown_perf, paydown_mod)
        self._agg_cache = {}
        self._lgd_agg_cache = {}
        # Stats
        self.n_cells = len(trans)
        n_with_30 = sum(1 for cell, d in trans.items()
                        if sum(d.values()) >= MIN_CELL_OBS)
        self.fill_rate = n_with_30 / max(len(trans), 1)

    def cell_transition(self, state, age_b, fico_b, ltv_b, mod):
        """Return (probability_row, obs_count) with fallback ladder."""
        ladder = [
            (state, age_b, fico_b, ltv_b, mod),
            (state, age_b, fico_b, ltv_b, 0),       # drop mod
            (state, age_b, fico_b, "any", mod),     # drop LTV
            (state, age_b, fico_b, "any", 0),
            (state, age_b, "any", "any", mod),      # drop FICO+LTV
            (state, age_b, "any", "any", 0),
            (state, "any", "any", "any", 0),        # state only (last resort)
        ]
        for cell in ladder:
            if "any" not in cell:
                row, n = self._make(cell)
                if row is not None:
                    return row, n
            else:
                cached = self._agg_cache.get(cell)
                if cached is not None:
                    if cached[0] is not None:
                        return cached
                    continue
                # Aggregate across wildcard dimensions
                agg = defaultdict(int)
                state_, age_b_, fico_b_, ltv_b_, mod_ = cell
                for k, d in self.trans.items():
                    ks, kab, kfb, klb, km = k
                    if ks != state_:
                        continue
                    if age_b_ != "any" and kab != age_b_:
                        continue
                    if fico_b_ != "any" and kfb != fico_b_:
                        continue
                    if ltv_b_ != "any" and klb != ltv_b_:
                        continue
                    if mod_ != "any" and km != mod_:
                        continue
                    for outk, v in d.items():
                        agg[outk] += v
                total = sum(agg.values())
                if total >= MIN_CELL_OBS:
                    row = np.zeros(N_STATES + 2)
                    for k, v in agg.items():
                        if isinstance(k, int):
                            row[k] = v
                        elif k == "Default":
                            row[N_STATES] = v
                        elif k == "Payoff":
                            row[N_STATES + 1] = v
                    row = row / total
                    self._agg_cache[cell] = (row, total)
                    return row, total
                self._agg_cache[cell] = (None, total)
        return None, 0

    def _make(self, cell):
        d = self.trans.get(cell)
        if not d:
            return None, 0
        total = sum(d.values())
        if total < MIN_CELL_OBS:
            return None, total
        row = np.zeros(N_STATES + 2)
        for k, v in d.items():
            if isinstance(k, int):
                row[k] = v
            elif k == "Default":
                row[N_STATES] = v
            elif k == "Payoff":
                row[N_STATES + 1] = v
        return row / total, total

    @staticmethod
    def _build_lgd(lgd_samples):
        out = {}
        for k, (sco, srec, n) in lgd_samples.items():
            if n < 5 or sco <= 0:
                continue
            out[k] = max(0.0, min(1.0, 1.0 - srec / sco))
        return out

    def lookup_lgd(self, age_b, fico_b, ltv_b):
        for k in [
            (age_b, fico_b, ltv_b),
            (age_b, fico_b, "any"),
            (age_b, "any", "any"),
            ("any", "any", "any"),
        ]:
            if "any" not in k:
                v = self.lgd_lookup.get(k)
                if v is not None:
                    return v
            else:
                if k in self._lgd_agg_cache:
                    return self._lgd_agg_cache[k]
                age_b_, fico_b_, ltv_b_ = k
                vals = []
                for kk, vv in self.lgd_lookup.items():
                    ka, kf, kl = kk
                    if age_b_ != "any" and ka != age_b_:
                        continue
                    if fico_b_ != "any" and kf != fico_b_:
                        continue
                    if ltv_b_ != "any" and kl != ltv_b_:
                        continue
                    vals.append(vv)
                if vals:
                    avg = sum(vals) / len(vals)
                    self._lgd_agg_cache[k] = avg
                    return avg
        return 0.55  # last resort

    @staticmethod
    def _build_paydown(perf, mod):
        def _curve(samples):
            out = defaultdict(list)
            for (tb, age), (s, n) in samples.items():
                if n < 5:
                    continue
                out[tb].append((age, s / n))
            for k in out:
                out[k].sort()
            return dict(out)
        return _curve(perf), _curve(mod)

    def lookup_paydown(self, term_bucket, age, is_modified=False):
        curve = self.mod_curve if is_modified else self.perf_curve
        pts = curve.get(term_bucket)
        if not pts:
            for tb in TERM_BUCKETS:
                if tb in curve:
                    pts = curve[tb]
                    break
        if not pts:
            return 1.0
        if age <= pts[0][0]:
            return pts[0][1]
        if age >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            a1, r1 = pts[i]
            a2, r2 = pts[i + 1]
            if a1 <= age <= a2:
                if a2 == a1:
                    return r1
                return r1 + (r2 - r1) * (age - a1) / (a2 - a1)
        return pts[-1][1]


# ── Per-loan forecast engine ─────────────────────────────────────────

def forecast_loan(model, loan, start_state=None, start_age=None, end_age=None):
    """Forward-simulate a single loan through the Markov chain.

    Two modes:
      - At-issuance: start_state=0, start_age=0, end_age=term
      - In-progress: start from current state/age, run to term
      - Lookback:    start_state=0, start_age=0, end_age=current_age
    """
    state = loan["state"] if start_state is None else start_state
    age   = loan["age_months"] if start_age is None else start_age
    term  = loan["term"] or 60
    final_age = term if end_age is None else end_age
    months_remaining = max(0, final_age - age)
    fico_b = loan["fico_b"]
    ltv_b  = loan["ltv_b"]
    mod    = loan.get("modified", 0)
    orig   = loan["orig_amount"] or loan.get("balance", 0) or 10000
    tb     = loan["term_bucket"]

    sv = np.zeros(N_STATES + 2)
    sv[state] = 1.0

    expected_loss = 0.0
    cur_age = age
    for step in range(months_remaining):
        cur_age += 1
        age_b = _bucket(cur_age, AGE_BUCKETS)
        Q = np.zeros((N_STATES + 2, N_STATES + 2))
        Q[N_STATES, N_STATES] = 1.0      # Default absorbing
        Q[N_STATES + 1, N_STATES + 1] = 1.0  # Payoff absorbing
        for s in STATES:
            row, n = model.cell_transition(s, age_b, fico_b, ltv_b, mod)
            if row is None:
                Q[s, s] = 1.0
            else:
                Q[s, :] = row
        new_sv = sv @ Q
        new_def_mass = new_sv[N_STATES] - sv[N_STATES]
        if new_def_mass > 0:
            ratio = model.lookup_paydown(tb, cur_age, is_modified=bool(mod))
            balance_at_default = orig * ratio
            lgd = model.lookup_lgd(age_b, fico_b, ltv_b)
            expected_loss += new_def_mass * balance_at_default * lgd
        sv = new_sv

    return expected_loss


# ── Bayesian calibration ─────────────────────────────────────────────

def bayesian_calibration(realized_cnl, lookback_predicted, sigma_prior=0.30):
    """Log-normal conjugate calibration. Returns (cal_factor, cal_lo, cal_hi)."""
    if lookback_predicted <= 0 or realized_cnl <= 0:
        return 1.0, 1.0, 1.0
    sigma_obs = max(0.05, 1.0 / math.sqrt(max(realized_cnl, 1e3) / 1e6))
    inv_var_prior = 1.0 / (sigma_prior ** 2)
    inv_var_obs   = 1.0 / (sigma_obs ** 2)
    log_r = math.log(realized_cnl / lookback_predicted)
    mu_post = (0.0 * inv_var_prior + log_r * inv_var_obs) / (inv_var_prior + inv_var_obs)
    sigma_post = math.sqrt(1.0 / (inv_var_prior + inv_var_obs))
    cal = math.exp(mu_post)
    return cal, math.exp(mu_post - sigma_post), math.exp(mu_post + sigma_post)


# ── Realized losses from pool_performance ────────────────────────────

def get_realized_losses(db_path, deals):
    """Pull latest cumulative net/gross losses and original pool balance per deal."""
    conn = sqlite3.connect(db_path)
    out = {}
    for deal in deals:
        row = conn.execute(
            "SELECT cumulative_net_losses, cumulative_gross_losses, "
            "beginning_pool_balance FROM pool_performance "
            "WHERE deal=? ORDER BY "
            "substr(distribution_date,length(distribution_date)-3,4)||"
            "CASE substr(distribution_date,1,instr(distribution_date,'/')-1) "
            "  WHEN '1' THEN '01' WHEN '2' THEN '02' WHEN '3' THEN '03' "
            "  WHEN '4' THEN '04' WHEN '5' THEN '05' WHEN '6' THEN '06' "
            "  WHEN '7' THEN '07' WHEN '8' THEN '08' WHEN '9' THEN '09' "
            "  ELSE substr(distribution_date,1,instr(distribution_date,'/')-1) END "
            "DESC LIMIT 1", (deal,)).fetchone()
        if row:
            out[deal] = {
                "cum_net":   float(row[0] or 0),
                "cum_gross": float(row[1] or 0),
            }
        # Original pool balance = max(beginning_pool_balance)
        row2 = conn.execute(
            "SELECT MAX(beginning_pool_balance) FROM pool_performance WHERE deal=?",
            (deal,)).fetchone()
        if row2 and row2[0]:
            out.setdefault(deal, {})["orig_bal"] = float(row2[0])
        else:
            out.setdefault(deal, {})["orig_bal"] = 0
    conn.close()
    return out


# ── At-issuance forecast ─────────────────────────────────────────────

def at_issuance_forecast(model, db_path, deal):
    """Load a deal's at-origination loan attributes and run Markov forward
    from age=0, state=current to produce expected lifetime CNL %."""
    conn = sqlite3.connect(db_path)
    loans = conn.execute(
        "SELECT asset_number, obligor_credit_score, original_ltv, "
        "original_loan_term, original_loan_amount "
        "FROM loans WHERE deal=?", (deal,)).fetchall()
    conn.close()

    total_loss = 0.0
    total_bal = 0.0
    for asset, fico, ltv, term, amount in loans:
        if not amount or amount <= 0:
            continue
        f_fico = float(fico) if fico and fico != 0 else None
        f_ltv  = float(ltv) if ltv and ltv != 0 else None
        f_term = int(term) if term else 60
        loan = {
            "state": 0,
            "age_months": 0,
            "fico_b": _bucket(f_fico, FICO_BUCKETS) if f_fico else 2,
            "ltv_b":  _bucket(f_ltv, LTV_BUCKETS) if f_ltv else 2,
            "modified": 0,
            "orig_amount": float(amount),
            "term": f_term,
            "term_bucket": _term_bucket(f_term),
            "balance": float(amount),
        }
        el = forecast_loan(model, loan, start_state=0, start_age=0, end_age=f_term)
        total_loss += el
        total_bal += float(amount)

    return (total_loss / total_bal * 100) if total_bal > 0 else 0.0, total_loss, total_bal


# ── In-progress forecast ─────────────────────────────────────────────

def in_progress_forecast(model, latest_state, deal):
    """For active loans in a deal: run Markov from current state to term.
    Also compute lookback (model-predicted loss from age 0 to now) for calibration."""
    deal_loans = {k: v for k, v in latest_state.items() if k[0] == deal}
    if not deal_loans:
        return 0.0, 0.0, 0, 0.0, 0

    forward_loss = 0.0
    lookback_loss = 0.0
    active_count = 0
    active_balance = 0.0
    total_loans = len(deal_loans)

    for (d, asset), loan in deal_loans.items():
        # Lookback for ALL loans (active + terminated)
        lb = forecast_loan(model, loan, start_state=0, start_age=0,
                           end_age=loan["age_months"])
        lookback_loss += lb

        # Forward only for active
        if loan.get("status") == "active":
            fl = forecast_loan(model, loan)
            forward_loss += fl
            active_count += 1
            active_balance += loan["balance"]

    return forward_loss, lookback_loss, active_count, active_balance, total_loans


# ── Main orchestrator ────────────────────────────────────────────────

def run():
    logger.info("=" * 70)
    logger.info("Unified Markov Model — Carvana Prime + CarMax (prime) / Carvana Non-Prime")
    logger.info("=" * 70)

    prime_deals, nonprime_deals = classify_deals()
    logger.info(f"Prime deals: {len(prime_deals)} (Carvana: "
                f"{sum(1 for d in prime_deals if d[2]=='Carvana')}, "
                f"CarMax: {sum(1 for d in prime_deals if d[2]=='CarMax')})")
    logger.info(f"Non-prime deals: {len(nonprime_deals)}")

    results = {}  # deal -> forecast dict

    for model_type, deal_list in [("prime", prime_deals), ("nonprime", nonprime_deals)]:
        if not deal_list:
            continue
        logger.info(f"\n{'='*60}")
        logger.info(f"Training {model_type.upper()} model ({len(deal_list)} deals)")
        logger.info(f"{'='*60}")

        agg = TransitionAggregator()
        all_latest = {}  # (deal, asset) -> snapshot

        # Group deals by DB to minimize connections
        by_db = defaultdict(list)
        for db_path, deal, issuer in deal_list:
            by_db[db_path].append(deal)

        for db_path, deals in by_db.items():
            # Process in chunks of 5 deals to cap covariate memory.
            # Loading all 3.1M CarMax loans at once OOM'd the 4GB droplet.
            DEAL_CHUNK = 5
            for ci in range(0, len(deals), DEAL_CHUNK):
                chunk = deals[ci:ci + DEAL_CHUNK]
                logger.info(f"Loading covariates from {os.path.basename(db_path)} "
                            f"chunk {ci // DEAL_CHUNK + 1}/{(len(deals) + DEAL_CHUNK - 1) // DEAL_CHUNK} "
                            f"({len(chunk)} deals)...")
                covariates = load_covariates(db_path, chunk)
                logger.info(f"  {len(covariates):,} loan covariates loaded, RSS={_rss_mb():.0f} MB")

                logger.info(f"Streaming transitions...")
                latest = agg.ingest_db(db_path, chunk, covariates)
                all_latest.update(latest)

                del covariates
                gc.collect()

        logger.info(f"\n{model_type.upper()} aggregation complete:")
        logger.info(f"  Total transition observations: {agg.total_obs:,}")
        logger.info(f"  Total loans: {agg.total_loans:,}")
        logger.info(f"  Transition cells: {len(agg.trans):,}")
        logger.info(f"  Paydown cells (perf): {len(agg.paydown_perf):,}")
        logger.info(f"  LGD cells: {len(agg.lgd_samples):,}")
        logger.info(f"  RSS: {_rss_mb():.0f} MB")

        # Build model
        model = MarkovModel(agg.trans, agg.lgd_samples,
                            agg.paydown_perf, agg.paydown_mod)
        logger.info(f"  Model cells: {model.n_cells:,}, "
                    f"fill rate (≥30 obs): {model.fill_rate:.1%}")

        # Free aggregator
        del agg
        gc.collect()

        # ── Per-deal forecasts ────────────────────────────────────────
        logger.info(f"\nRunning per-deal forecasts for {model_type}...")

        for db_path, deal, issuer in deal_list:
            # At-issuance forecast
            ai_cnl_pct, ai_loss, ai_bal = at_issuance_forecast(model, db_path, deal)

            # In-progress forecast
            fwd_loss, lb_loss, n_active, active_bal, n_total = \
                in_progress_forecast(model, all_latest, deal)

            # Realized losses
            realized = get_realized_losses(db_path, [deal])
            r = realized.get(deal, {})
            cum_net = r.get("cum_net", 0)
            cum_gross = r.get("cum_gross", 0)
            orig_bal = r.get("orig_bal", 0) or ai_bal

            # Bayesian calibration
            cal, cal_lo, cal_hi = bayesian_calibration(cum_net, lb_loss)

            # Calibrated forward
            fwd_calibrated = fwd_loss * cal
            current_projected_cnl = cum_net + fwd_calibrated
            current_projected_pct = (current_projected_cnl / orig_bal * 100) if orig_bal > 0 else 0
            realized_pct = (cum_net / orig_bal * 100) if orig_bal > 0 else 0

            # Pct complete (fraction of pool that has terminated)
            pct_complete = 1.0 - (n_active / n_total) if n_total > 0 else 0

            # Monthly projection for charts (simplified — just the totals)
            forecast_detail = {
                "at_issuance_cnl_pct": round(ai_cnl_pct, 4),
                "orig_bal": round(orig_bal, 2),
                "realized_net": round(cum_net, 2),
                "realized_gross": round(cum_gross, 2),
                "forward_uncalibrated": round(fwd_loss, 2),
                "forward_calibrated": round(fwd_calibrated, 2),
                "lookback_predicted": round(lb_loss, 2),
                "active_loans": n_active,
                "active_balance": round(active_bal, 2),
                "total_loans": n_total,
                "issuer": issuer,
            }

            results[deal] = {
                "db_path": db_path,
                "model_type": model_type,
                "issuer": issuer,
                "at_issuance_cnl_pct": round(ai_cnl_pct, 4),
                "current_projected_cnl_pct": round(current_projected_pct, 4),
                "realized_cnl_pct": round(realized_pct, 4),
                "cal_factor": round(cal, 4),
                "cal_lo": round(cal_lo, 4),
                "cal_hi": round(cal_hi, 4),
                "pct_complete": round(pct_complete, 4),
                "forecast_json": json.dumps(forecast_detail),
                # Extra fields for model_results compat
                "orig_bal": orig_bal,
                "active_loans": n_active,
                "active_balance": round(active_bal, 2),
                "n_loans_total": n_total,
                "realized": round(cum_net, 2),
                "realized_gross": round(cum_gross, 2),
                "forecast_only": round(fwd_calibrated, 2),
                "forecast_lo": round(fwd_loss * cal_lo, 2),
                "forecast_hi": round(fwd_loss * cal_hi, 2),
                "total_expected": round(current_projected_cnl, 2),
                "lookback_predicted_loss": round(lb_loss, 2),
                "calibration_factor": round(cal, 4),
                "calibration_lo": round(cal_lo, 4),
                "calibration_hi": round(cal_hi, 4),
            }

            logger.info(f"  {deal:10s} ({issuer:7s}): at-issuance={ai_cnl_pct:.2f}%  "
                        f"projected={current_projected_pct:.2f}%  "
                        f"realized={realized_pct:.2f}%  cal={cal:.2f}x  "
                        f"complete={pct_complete:.0%}")

        # Free latest state for this model
        del all_latest
        gc.collect()

    # ── Persist results ───────────────────────────────────────────────
    logger.info(f"\nPersisting results... RSS={_rss_mb():.0f} MB")
    _persist_results(results)

    logger.info(f"\nDone. Peak RSS: {_rss_mb():.0f} MB")
    return results


def _persist_results(results):
    """Write deal_forecasts table to each source DB and model_results to dashboard DBs."""

    # Group by source DB
    by_source_db = defaultdict(dict)
    for deal, r in results.items():
        by_source_db[r["db_path"]][deal] = r

    for db_path, deal_results in by_source_db.items():
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS deal_forecasts (
            deal TEXT PRIMARY KEY,
            model_type TEXT,
            at_issuance_cnl_pct REAL,
            current_projected_cnl_pct REAL,
            realized_cnl_pct REAL,
            cal_factor REAL,
            cal_lo REAL,
            cal_hi REAL,
            pct_complete REAL,
            forecast_json TEXT
        )""")
        for deal, r in deal_results.items():
            conn.execute(
                "INSERT OR REPLACE INTO deal_forecasts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (deal, r["model_type"], r["at_issuance_cnl_pct"],
                 r["current_projected_cnl_pct"], r["realized_cnl_pct"],
                 r["cal_factor"], r["cal_lo"], r["cal_hi"],
                 r["pct_complete"], r["forecast_json"]))
        conn.commit()
        conn.close()
        logger.info(f"  Wrote {len(deal_results)} rows to deal_forecasts in {os.path.basename(db_path)}")

    # Write model_results to each dashboard DB
    for dashboard_db, source_db, label in [
        (CARVANA_DASHBOARD_DB, CARVANA_DB, "Carvana"),
        (CARMAX_DASHBOARD_DB, CARMAX_DB, "CarMax"),
    ]:
        if not os.path.exists(dashboard_db):
            logger.warning(f"  Dashboard DB not found: {dashboard_db}")
            continue
        # Filter to deals from this source
        by_deal = {}
        tier_of_deal = {}
        for deal, r in results.items():
            if r["db_path"] == source_db:
                by_deal[deal] = {k: v for k, v in r.items()
                                 if k not in ("db_path", "forecast_json")}
                tier_of_deal[deal] = r["model_type"].capitalize()

        if not by_deal:
            continue

        out = {
            "by_deal": by_deal,
            "tier_of_deal": tier_of_deal,
            "model": "unified_markov",
        }
        dconn = sqlite3.connect(dashboard_db)
        dconn.execute("CREATE TABLE IF NOT EXISTS model_results "
                      "(key TEXT PRIMARY KEY, value TEXT)")
        dconn.execute("INSERT OR REPLACE INTO model_results VALUES (?, ?)",
                      ("conditional_markov", json.dumps(out)))
        dconn.commit()
        dconn.close()
        logger.info(f"  Wrote model_results to {os.path.basename(dashboard_db)} "
                    f"({len(by_deal)} deals)")


if __name__ == "__main__":
    run()
