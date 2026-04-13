#!/usr/bin/env python3
"""Loan default prediction model for Carvana ABS.

Trains logistic regression on all deals (prime + non-prime) using pure numpy.
No scikit-learn dependency — implements everything from scratch.

Features: FICO, LTV, PTI, interest rate, loan term, origination vintage, loan amount.
Target: binary default (chargeoff > 0).

Outputs JSON results to deploy/LAST_MODEL_RESULTS.json and stores summary
in a model_results table in dashboard.db for the dashboard to render.

Usage: python carvana_abs/default_model.py
"""
import json
import logging
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _PROJECT_DIR)
try:
    from carvana_abs.config import DB_PATH
except ImportError:
    # Fallback if import fails (e.g. when loaded via importlib)
    DB_PATH = os.path.join(_THIS_DIR, "db", "carvana_abs.db")

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")
OUTPUT_JSON = os.path.join(_PROJECT_DIR, "deploy", "LAST_MODEL_RESULTS.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── Pure-numpy ML utilities ──

def _sigmoid(z):
    z = np.clip(z, -500, 500)
    return 1.0 / (1.0 + np.exp(-z))


def _standardize(X_train, X_test):
    mu = X_train.mean(axis=0)
    std = X_train.std(axis=0)
    std[std == 0] = 1.0
    return (X_train - mu) / std, (X_test - mu) / std, mu, std


def _stratified_split(X, y, test_size=0.2, seed=42):
    """Stratified train/test split."""
    rng = np.random.RandomState(seed)
    idx0 = np.where(y == 0)[0]
    idx1 = np.where(y == 1)[0]
    rng.shuffle(idx0)
    rng.shuffle(idx1)
    n0 = int(len(idx0) * test_size)
    n1 = int(len(idx1) * test_size)
    test_idx = np.concatenate([idx0[:n0], idx1[:n1]])
    train_idx = np.concatenate([idx0[n0:], idx1[n1:]])
    return X[train_idx], X[test_idx], y[train_idx], y[test_idx]


def _logistic_regression(X_train, y_train, lr=0.1, max_iter=1000, lam=0.01):
    """Train logistic regression with L2 regularization via gradient descent."""
    n, d = X_train.shape
    w = np.zeros(d)
    b = 0.0
    for i in range(max_iter):
        z = X_train @ w + b
        p = _sigmoid(z)
        dw = (X_train.T @ (p - y_train)) / n + lam * w
        db = (p - y_train).mean()
        w -= lr * dw
        b -= lr * db
    return w, b


def _predict_proba_lr(X, w, b):
    return _sigmoid(X @ w + b)


def _accuracy(y_true, y_pred):
    return (y_true == y_pred).mean()


def _confusion_matrix(y_true, y_pred):
    tp = ((y_true == 1) & (y_pred == 1)).sum()
    tn = ((y_true == 0) & (y_pred == 0)).sum()
    fp = ((y_true == 0) & (y_pred == 1)).sum()
    fn = ((y_true == 1) & (y_pred == 0)).sum()
    return [[int(tn), int(fp)], [int(fn), int(tp)]]


def _precision_recall_f1(y_true, y_pred):
    tp = ((y_true == 1) & (y_pred == 1)).sum()
    fp = ((y_true == 0) & (y_pred == 1)).sum()
    fn = ((y_true == 1) & (y_pred == 0)).sum()
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


def _roc_curve(y_true, y_scores):
    """Compute ROC curve (fpr, tpr) at multiple thresholds."""
    thresholds = np.linspace(1, 0, 201)
    fpr_list, tpr_list = [], []
    pos = y_true.sum()
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return [0, 1], [0, 1]
    for t in thresholds:
        pred = (y_scores >= t).astype(int)
        tp = ((y_true == 1) & (pred == 1)).sum()
        fp = ((y_true == 0) & (pred == 1)).sum()
        fpr_list.append(fp / neg)
        tpr_list.append(tp / pos)
    return fpr_list, tpr_list


def _auc(fpr, tpr):
    """Compute AUC via trapezoidal rule."""
    fpr = np.array(fpr)
    tpr = np.array(tpr)
    order = np.argsort(fpr)
    x, y = fpr[order], tpr[order]
    return float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2))


def _decision_tree_predict(X, y, X_test, max_depth=6, min_leaf=50, seed=42):
    """Simple decision tree for probability estimation (recursive splitting)."""
    n, d = X.shape

    def _build(indices, depth):
        if depth >= max_depth or len(indices) < min_leaf * 2:
            return float(y[indices].mean()) if len(indices) > 0 else 0.5
        best_gain = -1
        best_feat = 0
        best_thresh = 0
        p = y[indices].mean()
        parent_impurity = p * (1 - p) * len(indices)
        rng = np.random.RandomState(seed + depth)
        # Random subset of features (sqrt(d))
        feat_subset = rng.choice(d, min(max(int(np.sqrt(d)), 2), d), replace=False)
        for f in feat_subset:
            vals = X[indices, f]
            percentiles = np.percentile(vals, [20, 40, 60, 80])
            for thresh in percentiles:
                left_mask = vals <= thresh
                right_mask = ~left_mask
                nl, nr = left_mask.sum(), right_mask.sum()
                if nl < min_leaf or nr < min_leaf:
                    continue
                pl = y[indices[left_mask]].mean()
                pr = y[indices[right_mask]].mean()
                child_impurity = pl * (1 - pl) * nl + pr * (1 - pr) * nr
                gain = parent_impurity - child_impurity
                if gain > best_gain:
                    best_gain = gain
                    best_feat = f
                    best_thresh = thresh
        if best_gain <= 0:
            return float(y[indices].mean()) if len(indices) > 0 else 0.5
        mask = X[indices, best_feat] <= best_thresh
        left = _build(indices[mask], depth + 1)
        right = _build(indices[~mask], depth + 1)
        return (best_feat, best_thresh, left, right)

    tree = _build(np.arange(n), 0)

    def _predict_one(x, node):
        if not isinstance(node, tuple):
            return node
        feat, thresh, left, right = node
        return _predict_one(x, left) if x[feat] <= thresh else _predict_one(x, right)

    return np.array([_predict_one(x, tree) for x in X_test])


def _random_forest_predict(X_train, y_train, X_test, n_trees=50, max_depth=6,
                           min_leaf=50, seed=42):
    """Simple bagged ensemble of decision trees."""
    n = len(X_train)
    rng = np.random.RandomState(seed)
    predictions = np.zeros(len(X_test))
    for i in range(n_trees):
        # Bootstrap sample
        idx = rng.choice(n, n, replace=True)
        preds = _decision_tree_predict(X_train[idx], y_train[idx], X_test,
                                       max_depth=max_depth, min_leaf=min_leaf,
                                       seed=seed + i)
        predictions += preds
    return predictions / n_trees


# ── Data loading & feature engineering ──

def load_data(db_path):
    """Load loans + loss data, create features and target."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT
            l.deal, l.asset_number,
            l.obligor_credit_score AS fico,
            l.original_ltv AS ltv,
            l.payment_to_income_ratio AS pti,
            l.original_interest_rate AS rate,
            l.original_loan_term AS term,
            l.original_loan_amount AS amount,
            l.origination_date,
            l.vehicle_new_used AS new_used,
            CASE WHEN s.total_chargeoff > 0 THEN 1 ELSE 0 END AS defaulted,
            COALESCE(s.total_chargeoff, 0) AS chargeoff_amount,
            COALESCE(s.total_recovery, 0) AS recovery_amount
        FROM loans l
        LEFT JOIN loan_loss_summary s ON l.deal = s.deal AND l.asset_number = s.asset_number
    """, conn)
    conn.close()
    return df


def engineer_features(df):
    """Create model features from raw data."""
    # Parse origination date — try multiple formats via pd.to_datetime (vectorized)
    orig = df["origination_date"].astype(str).str.strip()
    for fmt in ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y"]:
        parsed = pd.to_datetime(orig, format=fmt, errors="coerce")
        mask = df["orig_dt"].isna() if "orig_dt" in df.columns else pd.Series(True, index=df.index)
        if "orig_dt" not in df.columns:
            df["orig_dt"] = parsed
        else:
            df.loc[mask, "orig_dt"] = parsed[mask]

    df["orig_month"] = df["orig_dt"].dt.month
    df["orig_year"] = df["orig_dt"].dt.year

    # Feature columns — only use reliably populated fields (date parsing may fail on real data)
    feature_cols = ["fico", "ltv", "pti", "rate", "term", "amount"]
    return df, feature_cols


# ── Model training ──

def train_models(df, feature_cols):
    """Train logistic regression and random forest, return results dict."""
    # Drop rows with missing features
    model_df = df.dropna(subset=feature_cols + ["defaulted"]).copy()
    logger.info(f"Model dataset: {len(model_df):,} loans ({model_df['defaulted'].sum():,} defaults, "
                f"{model_df['defaulted'].mean():.2%} default rate)")

    if len(model_df) < 100 or model_df["defaulted"].sum() < 10:
        logger.error("Insufficient data for modeling")
        return None

    X = model_df[feature_cols].values.astype(float)
    y = model_df["defaulted"].values.astype(float)

    # Stratified train/test split
    X_train, X_test, y_train, y_test = _stratified_split(X, y, test_size=0.2, seed=42)

    # Standardize
    X_train_s, X_test_s, mu, std = _standardize(X_train, X_test)

    results = {
        "dataset": {
            "total_loans": len(model_df),
            "defaults": int(model_df["defaulted"].sum()),
            "default_rate": round(float(model_df["defaulted"].mean()), 4),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "features": feature_cols,
        },
        "models": {},
    }

    # --- Logistic Regression ---
    logger.info("Training Logistic Regression...")
    w, b = _logistic_regression(X_train_s, y_train, lr=0.5, max_iter=2000, lam=0.01)
    lr_probs = _predict_proba_lr(X_test_s, w, b)
    lr_pred = (lr_probs >= 0.5).astype(int)

    lr_fpr, lr_tpr = _roc_curve(y_test, lr_probs)
    lr_auc = _auc(lr_fpr, lr_tpr)
    lr_cm = _confusion_matrix(y_test, lr_pred)
    lr_prec, lr_rec, lr_f1 = _precision_recall_f1(y_test, lr_pred)

    # Downsample ROC for JSON
    step = max(1, len(lr_fpr) // 100)
    results["models"]["logistic_regression"] = {
        "accuracy": round(float(_accuracy(y_test, lr_pred)), 4),
        "auc_roc": round(lr_auc, 4),
        "precision": round(float(lr_prec), 4),
        "recall": round(float(lr_rec), 4),
        "f1": round(float(lr_f1), 4),
        "confusion_matrix": lr_cm,
        "roc_curve": {
            "fpr": [round(v, 4) for v in lr_fpr[::step]],
            "tpr": [round(v, 4) for v in lr_tpr[::step]],
        },
        "coefficients": {col: round(float(c), 4) for col, c in zip(feature_cols, w)},
    }
    logger.info(f"Logistic Regression: AUC={lr_auc:.4f}")

    # --- Random Forest (pure numpy) ---
    logger.info("Training Random Forest (30 trees)...")
    rf_probs = _random_forest_predict(X_train, y_train, X_test,
                                       n_trees=30, max_depth=6, min_leaf=50, seed=42)
    rf_pred = (rf_probs >= 0.5).astype(int)

    rf_fpr, rf_tpr = _roc_curve(y_test, rf_probs)
    rf_auc = _auc(rf_fpr, rf_tpr)
    rf_cm = _confusion_matrix(y_test, rf_pred)
    rf_prec, rf_rec, rf_f1 = _precision_recall_f1(y_test, rf_pred)

    # Feature importance: use LR coefficient magnitudes as proxy (fast)
    coef_abs = np.abs(w)
    fi_total = coef_abs.sum()
    fi = {col: round(float(coef_abs[i] / fi_total), 4) if fi_total > 0 else 0
          for i, col in enumerate(feature_cols)}

    step = max(1, len(rf_fpr) // 100)
    results["models"]["random_forest"] = {
        "accuracy": round(float(_accuracy(y_test, rf_pred)), 4),
        "auc_roc": round(rf_auc, 4),
        "precision": round(float(rf_prec), 4),
        "recall": round(float(rf_rec), 4),
        "f1": round(float(rf_f1), 4),
        "confusion_matrix": rf_cm,
        "roc_curve": {
            "fpr": [round(v, 4) for v in rf_fpr[::step]],
            "tpr": [round(v, 4) for v in rf_tpr[::step]],
        },
        "feature_importance": fi,
    }
    logger.info(f"Random Forest: AUC={rf_auc:.4f}")

    # --- Segment Analysis (using LR as primary — faster) ---
    logger.info("Computing segment analysis...")
    X_all_s = (model_df[feature_cols].values.astype(float) - mu) / std
    model_df["pred_prob_lr"] = _predict_proba_lr(X_all_s, w, b)

    segments = {}

    # By FICO
    model_df["fico_bucket"] = pd.cut(model_df["fico"],
        bins=[0, 580, 620, 660, 700, 740, 780, 820, 900],
        labels=["<580", "580-619", "620-659", "660-699", "700-739", "740-779", "780-819", "820+"],
        right=False)
    fico_seg = model_df.groupby("fico_bucket", observed=True).agg(
        loans=("defaulted", "count"),
        actual_defaults=("defaulted", "sum"),
        actual_rate=("defaulted", "mean"),
        predicted_rate=("pred_prob_lr", "mean"),
        avg_chargeoff=("chargeoff_amount", "mean"),
        avg_recovery=("recovery_amount", "mean"),
    ).reset_index()
    segments["by_fico"] = {
        "labels": fico_seg["fico_bucket"].tolist(),
        "loans": fico_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in fico_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in fico_seg["predicted_rate"]],
        "avg_chargeoff": [round(v, 2) for v in fico_seg["avg_chargeoff"]],
        "avg_recovery": [round(v, 2) for v in fico_seg["avg_recovery"]],
    }

    # By origination year (vintage)
    vintage_seg = model_df.dropna(subset=["orig_year"]).groupby("orig_year").agg(
        loans=("defaulted", "count"),
        actual_defaults=("defaulted", "sum"),
        actual_rate=("defaulted", "mean"),
        predicted_rate=("pred_prob_lr", "mean"),
    ).reset_index()
    segments["by_vintage"] = {
        "labels": [str(int(v)) for v in vintage_seg["orig_year"]],
        "loans": vintage_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in vintage_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in vintage_seg["predicted_rate"]],
    }

    # By LTV
    model_df["ltv_bucket"] = pd.cut(model_df["ltv"],
        bins=[0, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 2.0, 10.0],
        labels=["<80%", "80-89%", "90-99%", "100-109%", "110-119%", "120-139%", "140-199%", "200%+"],
        right=False)
    ltv_seg = model_df.groupby("ltv_bucket", observed=True).agg(
        loans=("defaulted", "count"),
        actual_rate=("defaulted", "mean"),
        predicted_rate=("pred_prob_lr", "mean"),
    ).reset_index()
    segments["by_ltv"] = {
        "labels": ltv_seg["ltv_bucket"].tolist(),
        "loans": ltv_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in ltv_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in ltv_seg["predicted_rate"]],
    }

    # By interest rate
    model_df["rate_bucket"] = pd.cut(model_df["rate"],
        bins=[0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 1.0],
        labels=["<4%", "4-5.99%", "6-7.99%", "8-9.99%", "10-11.99%", "12-14.99%", "15-19.99%", "20%+"],
        right=False)
    rate_seg = model_df.groupby("rate_bucket", observed=True).agg(
        loans=("defaulted", "count"),
        actual_rate=("defaulted", "mean"),
        predicted_rate=("pred_prob_lr", "mean"),
    ).reset_index()
    segments["by_rate"] = {
        "labels": rate_seg["rate_bucket"].tolist(),
        "loans": rate_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in rate_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in rate_seg["predicted_rate"]],
    }

    # By deal
    deal_seg = model_df.groupby("deal").agg(
        loans=("defaulted", "count"),
        actual_rate=("defaulted", "mean"),
        predicted_rate=("pred_prob_lr", "mean"),
    ).reset_index().sort_values("deal")
    segments["by_deal"] = {
        "labels": deal_seg["deal"].tolist(),
        "loans": deal_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in deal_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in deal_seg["predicted_rate"]],
    }

    # Dollar-weighted lifetime default forecast per deal — used by the loss
    # build-up table on the Default Model tab. Weighting by original loan
    # amount (rather than loan count) matters for loss projection since big
    # loans default at different rates than small ones.
    dollar_df = model_df.copy()
    dollar_df["expected_default_$"] = dollar_df["pred_prob_lr"] * dollar_df["amount"].astype(float)
    dollar_df["actual_default_$"] = dollar_df["defaulted"].astype(float) * dollar_df["amount"].astype(float)
    deal_dollar = dollar_df.groupby("deal").agg(
        loans=("defaulted", "count"),
        total_orig_amount=("amount", "sum"),
        predicted_default_amount=("expected_default_$", "sum"),
        actual_default_amount=("actual_default_$", "sum"),
    ).reset_index().sort_values("deal")
    deal_dollar["predicted_default_rate_dollar"] = (
        deal_dollar["predicted_default_amount"] / deal_dollar["total_orig_amount"])
    segments["lifetime_forecast_by_deal"] = {
        d: {
            "loans": int(r["loans"]),
            "total_orig_amount": round(float(r["total_orig_amount"]), 2),
            "predicted_default_amount": round(float(r["predicted_default_amount"]), 2),
            "actual_default_amount": round(float(r["actual_default_amount"]), 2),
            "predicted_default_rate_dollar": round(float(r["predicted_default_rate_dollar"]), 6),
        }
        for d, r in zip(deal_dollar["deal"], deal_dollar.to_dict("records"))
    }

    # Loss severity for defaulted loans
    defaults_only = model_df[model_df["defaulted"] == 1]
    if len(defaults_only) > 0:
        segments["loss_severity"] = {
            "total_defaulted": len(defaults_only),
            "avg_chargeoff": round(float(defaults_only["chargeoff_amount"].mean()), 2),
            "avg_recovery": round(float(defaults_only["recovery_amount"].mean()), 2),
            "avg_net_loss": round(float((defaults_only["chargeoff_amount"] - defaults_only["recovery_amount"]).mean()), 2),
            "recovery_rate": round(float(defaults_only["recovery_amount"].sum() / defaults_only["chargeoff_amount"].sum()), 4)
                if defaults_only["chargeoff_amount"].sum() > 0 else 0,
            "median_chargeoff": round(float(defaults_only["chargeoff_amount"].median()), 2),
        }

    results["segments"] = segments
    return results


# ── Empirical Markov absorption + per-deal loss-buildup forecast ──

PRIME_DEALS  = ["2020-P1", "2021-P1", "2021-P2", "2022-P1", "2022-P2",
                "2022-P3", "2024-P2", "2024-P3", "2024-P4",
                "2025-P2", "2025-P3", "2025-P4"]
NONPRIME_DEALS = ["2021-N1", "2021-N2", "2021-N3", "2021-N4"]
_SORT_KEY = ("substr(reporting_period_end,7,4)||"
             "substr(reporting_period_end,1,2)||"
             "substr(reporting_period_end,4,2)")


def _build_markov_absorption(conn, deals):
    """Compute the 6-state absorbing Markov chain's lifetime default
    probability per starting state, fit from this tier's loan_performance
    transition history. Returns a list of length 6: P(default | state s).
    """
    qm = ",".join(["?"] * len(deals))
    defaulted = {(d, a) for d, a in conn.execute(
        f"SELECT deal, asset_number FROM loan_loss_summary "
        f"WHERE total_chargeoff > 0 AND deal IN ({qm})", deals)}
    paidoff = set()
    for d, a in conn.execute(
        f"SELECT DISTINCT deal, asset_number FROM loan_performance "
        f"WHERE deal IN ({qm}) AND zero_balance_code IS NOT NULL", deals):
        if (d, a) not in defaulted:
            paidoff.add((d, a))

    cnt = {s: {**{t: 0 for t in range(6)}, "Default": 0, "Payoff": 0} for s in range(6)}
    cur = conn.execute(
        f"""SELECT deal, asset_number, current_delinquency_status,
                   zero_balance_code, charged_off_amount
            FROM loan_performance WHERE deal IN ({qm})
            ORDER BY deal, asset_number, {_SORT_KEY}""", deals)
    prev_key = None; prev_state = None
    for deal, asset, cds, zbc, coa in cur:
        key = (deal, asset)
        if key != prev_key:
            if prev_key is not None and prev_state is not None:
                if prev_key in defaulted: cnt[prev_state]["Default"] += 1
                elif prev_key in paidoff: cnt[prev_state]["Payoff"] += 1
            prev_key = key; prev_state = None
        if (zbc and str(zbc) in ("1", "2", "3", "4")) or (coa is not None and coa > 0):
            continue
        if cds is None: continue
        try: s = min(int(cds), 5)
        except (ValueError, TypeError): continue
        if prev_state is not None: cnt[prev_state][s] += 1
        prev_state = s
    if prev_key is not None and prev_state is not None:
        if prev_key in defaulted: cnt[prev_state]["Default"] += 1
        elif prev_key in paidoff: cnt[prev_state]["Payoff"] += 1

    Q = np.zeros((6, 6)); R = np.zeros((6, 2))
    for i in range(6):
        total = sum(cnt[i].values())
        if total == 0: continue
        for j in range(6): Q[i, j] = cnt[i][j] / total
        R[i, 0] = cnt[i]["Default"] / total
        R[i, 1] = cnt[i]["Payoff"] / total
    B = np.linalg.inv(np.eye(6) - Q) @ R
    return [round(float(B[i, 0]), 6) for i in range(6)]


def _per_deal_loss_buildup(conn, deals, p_default_by_state, db_for_cert):
    """For each deal, compute loss buildup using empirical Markov probabilities.

    Forecast components per deal:
      realized      = cum_net_losses from latest cert (authoritative)
      dq_pending    = sum over loans currently in state ≥ 1 of
                      P(default|state) × ending_balance × severity
      performing    = sum over loans currently in state 0 of
                      P(default|state=0) × ending_balance × severity
      total         = realized + dq_pending + performing

    Severity per deal = 1 − cum_liquidation_proceeds / cum_gross_losses
    from the cert; falls back to 60% (industry baseline) for deals without
    a cum_gross history yet.
    """
    out = {}
    for deal in deals:
        cert = _cert_totals_lookup(deal, db_for_cert)
        cum_gross = cert.get("cum_gross_losses") or 0
        cum_liq = cert.get("cum_liquidation_proceeds") or 0
        cum_net = cert.get("cum_net_losses") or max(0, cum_gross - cum_liq)
        severity = (1 - cum_liq / cum_gross) if cum_gross > 0 else 0.60

        # Active loans = loans whose CHRONOLOGICALLY-LATEST observation has
        # zero_balance_code IS NULL (still on the books, not terminated).
        # Then pull THAT row's status + ending balance.
        rows = conn.execute(f"""
            WITH latest AS (
                SELECT asset_number, MAX({_SORT_KEY}) AS k
                FROM loan_performance WHERE deal=?
                GROUP BY asset_number
            )
            SELECT lp.current_delinquency_status, lp.ending_balance
            FROM loan_performance lp
            INNER JOIN latest ON lp.asset_number = latest.asset_number
              AND {_SORT_KEY} = latest.k
            WHERE lp.deal = ?
              AND lp.zero_balance_code IS NULL
              AND lp.ending_balance > 0
        """, (deal, deal)).fetchall()

        dq_pending = 0.0; performing = 0.0
        for cds, bal in rows:
            try: s = min(int(cds or 0), 5)
            except (ValueError, TypeError): s = 0
            p = p_default_by_state[s]
            loss = p * float(bal) * severity
            if s == 0: performing += loss
            else: dq_pending += loss

        total = cum_net + dq_pending + performing
        out[deal] = {
            "active_loans": len(rows),
            "severity": round(severity, 4),
            "realized": round(cum_net, 2),
            "dq_pending": round(dq_pending, 2),
            "performing_future": round(performing, 2),
            "total_expected": round(total, 2),
        }
    return out


def _cert_totals_lookup(deal, db_path):
    """Parse cum gross/liq/net from this deal's latest cached servicer cert.
    Mirrors generate_dashboard._cert_totals (kept here so default_model has
    no dashboard dependency)."""
    import re
    from urllib.parse import urlparse
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filing_cache")
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT servicer_cert_url FROM filings WHERE deal=? "
        "AND servicer_cert_url IS NOT NULL ORDER BY filing_date DESC LIMIT 1",
        (deal,)).fetchone()
    conn.close()
    if not row: return {}
    p = urlparse(row[0])
    path = os.path.join(cache_dir, p.path.strip("/").replace("/", "_"))
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", errors="replace") as f: txt = f.read()
    except OSError: return {}
    body = re.sub(r"<[^>]+>", " ", re.sub(r"&nbsp;", " ", txt))
    body = re.sub(r"\s+", " ", body)
    def grab(label):
        pat = rf"{re.escape(label)}\s*\(?\s*\d+\s*\)?[^0-9]{{0,30}}([\d,]+(?:\.\d+)?)"
        m = re.search(pat, body)
        return float(m.group(1).replace(",", "")) if m else None
    # Label must run all the way through "Collection Period" so the regex's
    # `\(?\s*\d+\s*\)?` group lines up with the (NN) line marker that
    # immediately precedes the dollar amount.
    return {
        "cum_gross_losses": grab("Gross Charged-Off Receivables losses as of the last day of the current Collection Period"),
        "cum_liquidation_proceeds": grab("Liquidation Proceeds as of the last day of the current Collection Period"),
        "cum_net_losses": grab("Net Charged-Off Receivables losses as of the last day of the current Collection Period"),
    }


def compute_empirical_forecast(db_path):
    """Build the Markov-based per-deal loss buildup. Returns a dict suitable
    to attach under results["segments"]["empirical_loss_buildup"].

    The dashboard.db export drops loan_performance for size; this routine
    needs the full DB. Auto-fallback to /opt/abs-dashboard/carvana_abs/db
    /carvana_abs.db when the passed db_path lacks the loan_performance table.
    """
    full_db = "/opt/abs-dashboard/carvana_abs/db/carvana_abs.db"
    use_db = db_path
    try:
        sqlite3.connect(db_path).execute("SELECT 1 FROM loan_performance LIMIT 1")
    except sqlite3.OperationalError:
        if os.path.exists(full_db):
            use_db = full_db
            logger.info(f"loan_performance not in {db_path}; using full DB at {full_db}")
        else:
            logger.warning("loan_performance table not available; skipping empirical forecast")
            return {}
    conn = sqlite3.connect(use_db)
    logger.info("Building Prime Markov absorption matrix...")
    p_prime = _build_markov_absorption(conn, PRIME_DEALS)
    logger.info(f"  Prime P(default|state): {p_prime}")
    logger.info("Building Non-Prime Markov absorption matrix...")
    p_nonp = _build_markov_absorption(conn, NONPRIME_DEALS)
    logger.info(f"  Non-Prime P(default|state): {p_nonp}")
    logger.info("Per-deal loss buildup...")
    prime_out = _per_deal_loss_buildup(conn, PRIME_DEALS, p_prime, use_db)
    nonp_out  = _per_deal_loss_buildup(conn, NONPRIME_DEALS, p_nonp, use_db)
    conn.close()
    return {
        "markov_absorption": {"prime": p_prime, "nonprime": p_nonp},
        "by_deal": {**prime_out, **nonp_out},
        "tier_of_deal": {**{d: "Prime" for d in PRIME_DEALS},
                         **{d: "Non-Prime" for d in NONPRIME_DEALS}},
    }


def save_results(results, db_path, json_path):
    """Save model results to JSON file and dashboard DB."""
    # JSON output
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to {json_path}")

    # Store in dashboard DB as a single JSON blob for the dashboard to read
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS model_results (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR REPLACE INTO model_results VALUES (?, ?)",
                 ("default_model", json.dumps(results)))
    conn.commit()
    conn.close()
    logger.info(f"Results stored in {db_path}")


def main():
    db = DASHBOARD_DB if os.path.exists(DASHBOARD_DB) else DB_PATH
    if not os.path.exists(db):
        logger.error(f"No database found at {db}")
        return

    logger.info(f"Loading data from {db}...")
    df = load_data(db)
    logger.info(f"Loaded {len(df):,} loans")

    logger.info("Engineering features...")
    df, feature_cols = engineer_features(df)

    logger.info("Training models...")
    results = train_models(df, feature_cols)
    if results is None:
        logger.error("Model training failed")
        return

    logger.info("Computing empirical Markov loss forecast (per-deal build-up)...")
    try:
        results["segments"]["empirical_loss_buildup"] = compute_empirical_forecast(db)
    except Exception as e:
        logger.warning(f"Empirical loss buildup failed: {e}")

    logger.info("Saving results...")
    save_results(results, db, OUTPUT_JSON)

    # Print summary
    for name, metrics in results["models"].items():
        logger.info(f"{name}: accuracy={metrics['accuracy']:.1%} AUC={metrics['auc_roc']:.3f} "
                     f"precision={metrics['precision']:.1%} recall={metrics['recall']:.1%}")

    logger.info("Done!")


if __name__ == "__main__":
    main()
