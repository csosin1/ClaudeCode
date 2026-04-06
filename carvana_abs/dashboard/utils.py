"""Shared utilities for all dashboard pages."""

import os
import sys
import sqlite3
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from carvana_abs.config import DB_PATH, DEALS

# Use the small dashboard DB (~50MB) if it exists, otherwise fall back to full DB (1.7GB)
_DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")
_ACTIVE_DB = _DASHBOARD_DB if os.path.exists(_DASHBOARD_DB) else DB_PATH


@st.cache_resource
def get_db():
    if not os.path.exists(_ACTIVE_DB):
        return None
    conn = sqlite3.connect(_ACTIVE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # SQLite performance optimizations
    conn.execute("PRAGMA cache_size=10000")       # 10MB in-memory page cache
    conn.execute("PRAGMA temp_store=memory")       # Temp tables in RAM
    conn.execute("PRAGMA mmap_size=268435456")     # Memory-map 256MB of DB file
    conn.execute("PRAGMA journal_mode=WAL")        # Write-ahead logging
    conn.execute("PRAGMA synchronous=NORMAL")      # Faster writes
    # Pre-warm: force SQLite to load index pages
    conn.execute("SELECT COUNT(*) FROM filings").fetchone()
    conn.execute("SELECT COUNT(*) FROM monthly_summary").fetchone()
    return conn


def query_df(sql, params=()):
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query(sql, conn, params=params)


def normalize_date(d):
    if not d:
        return d
    d = str(d).strip()
    for sep in ["-", "/"]:
        parts = d.split(sep)
        if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
            return f"{parts[2]}{sep}{parts[0].zfill(2)}{sep}{parts[1].zfill(2)}"
    return d


def fmt_compact(val, is_pct=False):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    if is_pct:
        return f"{val:.2%}"
    if abs(val) >= 1_000_000_000:
        return f"${val/1e9:.1f}B"
    if abs(val) >= 1_000_000:
        return f"${val/1e6:.1f}M"
    if abs(val) >= 1_000:
        return f"${val/1e3:.0f}K"
    return f"${val:,.0f}"


def get_deal():
    return st.session_state.get("selected_deal", list(DEALS.keys())[0])


def get_orig_bal():
    return st.session_state.get("ORIG_BAL", 405_000_000)


# ── Cached Data Loaders ──

@st.cache_data(ttl=300)
def load_pool(deal):
    df = query_df("SELECT * FROM pool_performance WHERE deal = ? ORDER BY distribution_date", (deal,))
    if not df.empty:
        df["period"] = df["distribution_date"].apply(normalize_date)
        df = df.sort_values("period").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_lp(deal):
    """Load from pre-computed monthly_summary (~50 rows, instant)."""
    df = query_df("SELECT * FROM monthly_summary WHERE deal = ? ORDER BY reporting_period_end", (deal,))
    if df.empty:
        return df
    df["period"] = df["reporting_period_end"].apply(normalize_date)
    df = df.sort_values("period").reset_index(drop=True)
    # Compute cumulative columns
    ORIG_BAL = get_orig_bal()
    df["cum_chargeoffs"] = df["period_chargeoffs"].cumsum()
    df["cum_recoveries"] = df["period_recoveries"].cumsum()
    df["cum_net_losses"] = df["cum_chargeoffs"] - df["cum_recoveries"]
    df["cum_loss_rate"] = df["cum_net_losses"] / ORIG_BAL
    df["dq_rate"] = df["total_dq_balance"] / df["total_balance"]
    df["dq_30_rate"] = df["dq_30_balance"] / df["total_balance"]
    df["dq_60_rate"] = df["dq_60_balance"] / df["total_balance"]
    df["dq_90_rate"] = df["dq_90_balance"] / df["total_balance"]
    df["dq_120_plus_rate"] = df["dq_120_plus_balance"] / df["total_balance"]
    df["net_losses"] = df["period_chargeoffs"] - df["period_recoveries"]
    df["excess_spread"] = df["interest_collected"] - df["est_servicing_fee"] - df["net_losses"]
    df["cum_excess"] = df["excess_spread"].cumsum()
    df["cum_interest"] = df["interest_collected"].cumsum()
    df["cum_principal"] = df["principal_collected"].cumsum()
    df["cum_recovery_rate"] = df["cum_recoveries"] / df["cum_chargeoffs"].replace(0, float("nan"))
    return df


@st.cache_data(ttl=300)
def load_loans(deal):
    df = query_df("SELECT * FROM loans WHERE deal = ?", (deal,))
    if not df.empty and "original_interest_rate" in df.columns:
        df["rate_pct"] = df["original_interest_rate"] * 100
    return df


@st.cache_data(ttl=300)
def load_losses_by_segment(deal, col):
    return query_df(f"""
        SELECT l.{col} as segment, COUNT(*) as loan_count,
               SUM(l.original_loan_amount) as original_balance,
               SUM(COALESCE(s.total_chargeoff, 0)) as total_chargeoffs,
               SUM(COALESCE(s.total_recovery, 0)) as total_recoveries
        FROM loans l
        LEFT JOIN loan_loss_summary s ON l.deal = s.deal AND l.asset_number = s.asset_number
        WHERE l.deal = ? AND l.{col} IS NOT NULL
        GROUP BY l.{col} ORDER BY l.{col}
    """, (deal,))


@st.cache_data(ttl=300)
def load_recovery_data(deal):
    from datetime import datetime
    df = query_df("""
        SELECT s.asset_number, s.chargeoff_period, s.total_chargeoff,
               s.first_recovery_period, s.total_recovery as total_recoveries,
               l.obligor_credit_score, l.original_interest_rate, l.original_loan_amount
        FROM loan_loss_summary s
        LEFT JOIN loans l ON s.deal = l.deal AND s.asset_number = l.asset_number
        WHERE s.deal = ? AND s.total_chargeoff > 0
    """, (deal,))
    if df.empty:
        return df

    def parse_date(d):
        if not d:
            return None
        d = str(d).strip()
        for fmt in ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"]:
            try:
                return datetime.strptime(d, fmt)
            except ValueError:
                continue
        return None

    df["co_dt"] = df["chargeoff_period"].apply(parse_date)
    df["rec_dt"] = df["first_recovery_period"].apply(parse_date)
    df["has_recovery"] = df["total_recoveries"].notna() & (df["total_recoveries"] > 0)
    df["recovery_rate"] = df.apply(
        lambda r: r["total_recoveries"] / r["total_chargeoff"]
        if r["has_recovery"] and r["total_chargeoff"] > 0 else None, axis=1)
    df["months_to_recovery"] = df.apply(
        lambda r: ((r["rec_dt"].year - r["co_dt"].year) * 12 + r["rec_dt"].month - r["co_dt"].month)
        if pd.notna(r["rec_dt"]) and pd.notna(r["co_dt"]) else None, axis=1)
    return df


# Mobile CSS
MOBILE_CSS = """
<style>
@media (max-width: 768px) {
    .block-container { padding: 0.5rem 0.5rem !important; }
    [data-testid="stMetric"] { padding: 0.3rem 0.5rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
    .stRadio > div { flex-wrap: wrap !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1rem !important; }
}
[data-testid="stDataFrame"] { overflow-x: auto !important; }
[data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {
    white-space: nowrap !important; font-size: 0.8rem !important;
}
</style>
"""
