#!/usr/bin/env python3
"""Loan default prediction model for Carvana ABS.

Trains logistic regression and random forest on all deals (prime + non-prime).
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

try:
    import sklearn
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "deploy", "LAST_MODEL_RESULTS.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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

    # Feature columns
    feature_cols = ["fico", "ltv", "pti", "rate", "term", "amount", "orig_month", "orig_year"]
    return df, feature_cols


def train_models(df, feature_cols):
    """Train logistic regression and random forest, return results dict."""
    from sklearn.model_selection import train_test_split
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, roc_auc_score, precision_score,
                                 recall_score, f1_score, confusion_matrix, roc_curve)
    from sklearn.preprocessing import StandardScaler

    # Drop rows with missing features
    model_df = df.dropna(subset=feature_cols + ["defaulted"]).copy()
    logger.info(f"Model dataset: {len(model_df):,} loans ({model_df['defaulted'].sum():,} defaults, "
                f"{model_df['defaulted'].mean():.2%} default rate)")

    if len(model_df) < 100 or model_df["defaulted"].sum() < 10:
        logger.error("Insufficient data for modeling")
        return None

    X = model_df[feature_cols].values
    y = model_df["defaulted"].values

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)

    # Scale features for logistic regression
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    results = {
        "dataset": {
            "total_loans": len(model_df),
            "defaults": int(model_df["defaulted"].sum()),
            "default_rate": round(model_df["defaulted"].mean(), 4),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "features": feature_cols,
        },
        "models": {},
    }

    # --- Logistic Regression ---
    lr = LogisticRegression(max_iter=1000, random_state=42)
    lr.fit(X_train_scaled, y_train)
    lr_probs = lr.predict_proba(X_test_scaled)[:, 1]
    lr_pred = lr.predict(X_test_scaled)

    lr_fpr, lr_tpr, _ = roc_curve(y_test, lr_probs)
    lr_cm = confusion_matrix(y_test, lr_pred)

    results["models"]["logistic_regression"] = {
        "accuracy": round(accuracy_score(y_test, lr_pred), 4),
        "auc_roc": round(roc_auc_score(y_test, lr_probs), 4),
        "precision": round(precision_score(y_test, lr_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, lr_pred, zero_division=0), 4),
        "f1": round(f1_score(y_test, lr_pred, zero_division=0), 4),
        "confusion_matrix": lr_cm.tolist(),
        "roc_curve": {
            "fpr": [round(v, 4) for v in lr_fpr[::max(1, len(lr_fpr) // 100)]],
            "tpr": [round(v, 4) for v in lr_tpr[::max(1, len(lr_tpr) // 100)]],
        },
        "coefficients": {col: round(coef, 4) for col, coef in zip(feature_cols, lr.coef_[0])},
    }
    logger.info(f"Logistic Regression: AUC={results['models']['logistic_regression']['auc_roc']}")

    # --- Random Forest ---
    rf = RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=50,
                                random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    rf_probs = rf.predict_proba(X_test)[:, 1]
    rf_pred = rf.predict(X_test)

    rf_fpr, rf_tpr, _ = roc_curve(y_test, rf_probs)
    rf_cm = confusion_matrix(y_test, rf_pred)

    results["models"]["random_forest"] = {
        "accuracy": round(accuracy_score(y_test, rf_pred), 4),
        "auc_roc": round(roc_auc_score(y_test, rf_probs), 4),
        "precision": round(precision_score(y_test, rf_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, rf_pred, zero_division=0), 4),
        "f1": round(f1_score(y_test, rf_pred, zero_division=0), 4),
        "confusion_matrix": rf_cm.tolist(),
        "roc_curve": {
            "fpr": [round(v, 4) for v in rf_fpr[::max(1, len(rf_fpr) // 100)]],
            "tpr": [round(v, 4) for v in rf_tpr[::max(1, len(rf_tpr) // 100)]],
        },
        "feature_importance": {col: round(imp, 4) for col, imp in zip(feature_cols, rf.feature_importances_)},
    }
    logger.info(f"Random Forest: AUC={results['models']['random_forest']['auc_roc']}")

    # --- Segment Analysis (using RF as primary model) ---
    # Use full dataset for segment analysis
    X_all_scaled = scaler.transform(model_df[feature_cols].values)
    model_df["pred_prob_lr"] = lr.predict_proba(X_all_scaled)[:, 1]
    model_df["pred_prob_rf"] = rf.predict_proba(model_df[feature_cols].values)[:, 1]

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
        predicted_rate=("pred_prob_rf", "mean"),
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
        predicted_rate=("pred_prob_rf", "mean"),
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
        predicted_rate=("pred_prob_rf", "mean"),
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
        predicted_rate=("pred_prob_rf", "mean"),
    ).reset_index()
    segments["by_rate"] = {
        "labels": rate_seg["rate_bucket"].tolist(),
        "loans": rate_seg["loans"].tolist(),
        "actual_rate": [round(v, 4) for v in rate_seg["actual_rate"]],
        "predicted_rate": [round(v, 4) for v in rate_seg["predicted_rate"]],
    }

    # Loss severity for defaulted loans
    defaults_only = model_df[model_df["defaulted"] == 1]
    if len(defaults_only) > 0:
        segments["loss_severity"] = {
            "total_defaulted": len(defaults_only),
            "avg_chargeoff": round(defaults_only["chargeoff_amount"].mean(), 2),
            "avg_recovery": round(defaults_only["recovery_amount"].mean(), 2),
            "avg_net_loss": round((defaults_only["chargeoff_amount"] - defaults_only["recovery_amount"]).mean(), 2),
            "recovery_rate": round(defaults_only["recovery_amount"].sum() / defaults_only["chargeoff_amount"].sum(), 4)
                if defaults_only["chargeoff_amount"].sum() > 0 else 0,
            "median_chargeoff": round(defaults_only["chargeoff_amount"].median(), 2),
        }

    results["segments"] = segments
    return results


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
    if not HAS_SKLEARN:
        logger.error("scikit-learn is not installed. Run: pip install scikit-learn")
        return

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

    logger.info("Saving results...")
    save_results(results, db, OUTPUT_JSON)

    # Print summary
    for name, metrics in results["models"].items():
        logger.info(f"{name}: accuracy={metrics['accuracy']:.1%} AUC={metrics['auc_roc']:.3f} "
                     f"precision={metrics['precision']:.1%} recall={metrics['recall']:.1%}")

    logger.info("Done!")


if __name__ == "__main__":
    main()
