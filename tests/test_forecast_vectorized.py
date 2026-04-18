"""Parity test: vectorized forecast_loan vs legacy implementation.

Builds a synthetic MarkovModel with hand-crafted transition counts covering
all (state, age_b, fico_b, ltv_b, mod) cells we need, then forecasts 10 loans
with varied covariates two ways and asserts per-loan agreement.

Run from repo root:
    python -m pytest tests/test_forecast_vectorized.py -v
or:
    python tests/test_forecast_vectorized.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from unified_markov import (
    AGE_BUCKETS,
    FICO_BUCKETS,
    LTV_BUCKETS,
    MIN_CELL_OBS,
    N_STATES,
    STATES,
    MarkovModel,
    _forecast_loan_legacy,
    forecast_loan,
)


def _build_synthetic_model(seed: int = 42) -> MarkovModel:
    """Create a MarkovModel with transitions for every (state, age_b, fico_b,
    ltv_b, mod) combo — well above MIN_CELL_OBS so no fallback is hit.

    Transition probabilities are generated from a Dirichlet-ish random split
    with a tilt toward staying/advancing states, plus small Default/Payoff
    tails so cumulative loss is non-zero.
    """
    rng = np.random.default_rng(seed)
    trans = defaultdict(lambda: defaultdict(int))

    n_age_b = len(AGE_BUCKETS)
    n_fico_b = len(FICO_BUCKETS)
    n_ltv_b = len(LTV_BUCKETS)

    for s in STATES:
        for ab in range(n_age_b):
            for fb in range(n_fico_b):
                for lb in range(n_ltv_b):
                    for m in (0, 1):
                        # Generate counts for outcomes: states 0..5, Default, Payoff
                        alpha = np.ones(N_STATES + 2) * 0.3
                        alpha[s] = 4.0  # bias toward staying
                        if s + 1 < N_STATES:
                            alpha[s + 1] = 1.2
                        if s > 0:
                            alpha[s - 1] = 0.8
                        alpha[N_STATES] = 0.15 + 0.1 * s  # default climbs w/ delinq
                        alpha[N_STATES + 1] = 0.8 if s == 0 else 0.05
                        probs = rng.dirichlet(alpha)
                        counts = np.round(probs * 500).astype(int)
                        counts[counts < 0] = 0
                        # Ensure total >= MIN_CELL_OBS
                        if counts.sum() < MIN_CELL_OBS:
                            counts[s] += MIN_CELL_OBS
                        cell = (s, ab, fb, lb, m)
                        for i in range(N_STATES):
                            if counts[i]:
                                trans[cell][i] = int(counts[i])
                        if counts[N_STATES]:
                            trans[cell]["Default"] = int(counts[N_STATES])
                        if counts[N_STATES + 1]:
                            trans[cell]["Payoff"] = int(counts[N_STATES + 1])

    # LGD samples — (age_b, fico_b, ltv_b) → (sum_co, sum_rec, n)
    lgd_samples = {}
    for ab in range(n_age_b):
        for fb in range(n_fico_b):
            for lb in range(n_ltv_b):
                lgd = 0.45 + 0.05 * (lb - 2) + 0.02 * (2 - fb)
                lgd = max(0.1, min(0.9, lgd))
                # sum_co = 1_000_000, recoveries = (1 - lgd) * 1_000_000
                lgd_samples[(ab, fb, lb)] = [1_000_000.0,
                                             (1.0 - lgd) * 1_000_000.0,
                                             50]

    # Paydown curves — one sample per (term_bucket, age)
    paydown_perf = {}
    paydown_mod = {}
    from unified_markov import TERM_BUCKETS
    for tb in TERM_BUCKETS:
        for age in range(0, tb + 1):
            ratio = max(0.0, 1.0 - age / tb)
            paydown_perf[(tb, age)] = [ratio * 10, 10]
            paydown_mod[(tb, age)]  = [ratio * 1.05 * 10, 10]

    return MarkovModel(dict(trans), lgd_samples, paydown_perf, paydown_mod)


def _sample_loans():
    """10 loans with varied covariates spanning the bucket grid."""
    loans = [
        # at-issuance-style (age=0, state=0)
        {"state": 0, "age_months": 0, "fico_b": 0, "ltv_b": 0, "modified": 0,
         "orig_amount": 25000.0, "term": 60, "term_bucket": 60, "balance": 25000.0},
        {"state": 0, "age_months": 0, "fico_b": 4, "ltv_b": 4, "modified": 0,
         "orig_amount": 40000.0, "term": 72, "term_bucket": 72, "balance": 40000.0},
        {"state": 0, "age_months": 0, "fico_b": 2, "ltv_b": 2, "modified": 0,
         "orig_amount": 18000.0, "term": 48, "term_bucket": 48, "balance": 18000.0},
        # in-progress, various states and ages
        {"state": 0, "age_months": 12, "fico_b": 3, "ltv_b": 1, "modified": 0,
         "orig_amount": 30000.0, "term": 60, "term_bucket": 60, "balance": 22000.0},
        {"state": 1, "age_months": 18, "fico_b": 1, "ltv_b": 3, "modified": 0,
         "orig_amount": 28000.0, "term": 72, "term_bucket": 72, "balance": 20000.0},
        {"state": 2, "age_months": 24, "fico_b": 2, "ltv_b": 2, "modified": 1,
         "orig_amount": 22000.0, "term": 60, "term_bucket": 60, "balance": 14000.0},
        {"state": 3, "age_months": 30, "fico_b": 0, "ltv_b": 4, "modified": 1,
         "orig_amount": 20000.0, "term": 60, "term_bucket": 60, "balance": 10000.0},
        {"state": 0, "age_months": 36, "fico_b": 4, "ltv_b": 0, "modified": 0,
         "orig_amount": 35000.0, "term": 72, "term_bucket": 72, "balance": 15000.0},
        # lookback-like (end_age < term)
        {"state": 0, "age_months": 6, "fico_b": 2, "ltv_b": 2, "modified": 0,
         "orig_amount": 27000.0, "term": 60, "term_bucket": 60, "balance": 25000.0},
        # long term, deep age
        {"state": 0, "age_months": 40, "fico_b": 3, "ltv_b": 2, "modified": 0,
         "orig_amount": 45000.0, "term": 84, "term_bucket": 84, "balance": 24000.0},
    ]
    return loans


def test_vectorized_matches_legacy():
    model = _build_synthetic_model()
    loans = _sample_loans()

    diffs = []
    agg_legacy = 0.0
    agg_vec = 0.0
    for i, loan in enumerate(loans):
        legacy = _forecast_loan_legacy(model, loan)
        vec = forecast_loan(model, loan)
        diffs.append(abs(legacy - vec))
        agg_legacy += legacy
        agg_vec += vec
        assert abs(legacy - vec) < 1e-6, (
            f"loan {i}: legacy={legacy:.10f} vec={vec:.10f} "
            f"diff={abs(legacy - vec):.2e}"
        )

    assert abs(agg_legacy - agg_vec) < 1e-6, (
        f"aggregate mismatch: legacy={agg_legacy} vec={agg_vec}"
    )
    print(f"OK — 10 loans, max per-loan diff = {max(diffs):.2e}, "
          f"aggregate legacy={agg_legacy:.4f} vec={agg_vec:.4f}")


def test_lookback_and_at_issuance_modes():
    """Exercise the explicit start_state/start_age/end_age parameters."""
    model = _build_synthetic_model()
    loan = {
        "state": 2, "age_months": 15, "fico_b": 2, "ltv_b": 2, "modified": 0,
        "orig_amount": 25000.0, "term": 60, "term_bucket": 60, "balance": 18000.0,
    }
    # at-issuance mode
    a_leg = _forecast_loan_legacy(model, loan, start_state=0, start_age=0,
                                   end_age=60)
    a_vec = forecast_loan(model, loan, start_state=0, start_age=0, end_age=60)
    assert abs(a_leg - a_vec) < 1e-6

    # lookback mode
    l_leg = _forecast_loan_legacy(model, loan, start_state=0, start_age=0,
                                   end_age=loan["age_months"])
    l_vec = forecast_loan(model, loan, start_state=0, start_age=0,
                          end_age=loan["age_months"])
    assert abs(l_leg - l_vec) < 1e-6

    # zero-length horizon
    z_leg = _forecast_loan_legacy(model, loan, start_state=0, start_age=60,
                                   end_age=60)
    z_vec = forecast_loan(model, loan, start_state=0, start_age=60, end_age=60)
    assert z_leg == 0.0
    assert z_vec == 0.0


if __name__ == "__main__":
    test_vectorized_matches_legacy()
    test_lookback_and_at_issuance_modes()
    print("all parity tests passed")
