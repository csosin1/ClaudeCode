"""Streamlit dashboard for Carvana Auto Receivables Trust ABS deals."""

import os
import sys
import sqlite3

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH, DEALS

st.set_page_config(page_title="Carvana ABS Dashboard", page_icon="\U0001F4CA", layout="wide")

# ── Mobile-Friendly CSS ──
st.markdown("""
<style>
/* Reduce padding on mobile */
@media (max-width: 768px) {
    .block-container { padding: 0.5rem 0.5rem !important; }
    /* Make metric cards more compact */
    [data-testid="stMetric"] {
        padding: 0.3rem 0.5rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.1rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
    }
    /* Tab labels smaller on mobile */
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 0.7rem !important;
        padding: 0.3rem 0.4rem !important;
    }
    /* Radio buttons wrap better */
    .stRadio > div { flex-wrap: wrap !important; }
    /* Subheaders smaller */
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1rem !important; }
}
/* Tables: horizontal scroll on all screens, compact text */
[data-testid="stDataFrame"] {
    overflow-x: auto !important;
}
[data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {
    white-space: nowrap !important;
    font-size: 0.8rem !important;
}
/* Charts: reduce plotly margins */
.js-plotly-plot .plotly .main-svg {
    overflow: visible !important;
}
/* Make sidebar toggle easier to tap on mobile */
@media (max-width: 768px) {
    [data-testid="collapsedControl"] {
        min-width: 2.5rem !important;
        min-height: 2.5rem !important;
    }
}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(sql, params=()):
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query(sql, conn, params=params)


def fmt_compact(val, is_pct=False):
    """Format numbers compactly for mobile: $18.1M, $405K, 12.3%, etc."""
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


def normalize_date(d):
    if not d:
        return d
    d = str(d).strip()
    for sep in ["-", "/"]:
        parts = d.split(sep)
        if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
            return f"{parts[2]}{sep}{parts[0].zfill(2)}{sep}{parts[1].zfill(2)}"
    return d


st.title("Carvana Auto Receivables Trust")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")

conn = get_db()
if conn is None:
    st.error(f"Database not found at `{DB_PATH}`.")
    st.stop()

available_deals = query_df("SELECT DISTINCT deal FROM filings ORDER BY deal")
deal_list = available_deals["deal"].tolist() if not available_deals.empty else list(DEALS.keys())

with st.sidebar:
    st.header("Deal Selection")
    selected_deal = st.selectbox("Deal", deal_list, index=0)
    deal_cfg = DEALS.get(selected_deal, {})
    if deal_cfg:
        st.caption(deal_cfg.get("entity_name", ""))
    st.markdown("---")
    lc = query_df("SELECT COUNT(*) as n FROM loans WHERE deal = ?", (selected_deal,))
    pp = query_df("SELECT COUNT(*) as n FROM pool_performance WHERE deal = ?", (selected_deal,))
    if not lc.empty:
        st.metric("Unique Loans", f"{int(lc.iloc[0]['n']):,}")
    if not pp.empty:
        st.metric("Pool Data Points", int(pp.iloc[0]["n"]))
    ms = query_df("SELECT COUNT(*) as n FROM monthly_summary WHERE deal = ?", (selected_deal,))
    if not ms.empty and ms.iloc[0]["n"] > 0:
        st.metric("Perf Periods", int(ms.iloc[0]["n"]))
    st.markdown("---")

    # Data coverage across all deals
    with st.expander("All Deals Data Coverage"):
        cov = query_df("""
            SELECT deal,
                   (SELECT COUNT(*) FROM loans WHERE loans.deal = f.deal) as loans,
                   (SELECT COUNT(*) FROM pool_performance WHERE pool_performance.deal = f.deal) as pool,
                   (SELECT COUNT(*) FROM monthly_summary WHERE monthly_summary.deal = f.deal) as periods
            FROM (SELECT DISTINCT deal FROM filings) f
            ORDER BY deal
        """)
        if not cov.empty:
            st.dataframe(cov, use_container_width=True, hide_index=True)
    st.caption("Data sourced from SEC EDGAR")

# Get original pool balance — from config, or auto-detect from first pool_performance record
_configured_bal = deal_cfg.get("original_pool_balance")
if _configured_bal:
    ORIG_BAL = _configured_bal
else:
    # Auto-detect from pool_performance or loan data
    _first_pool = query_df(
        "SELECT beginning_pool_balance FROM pool_performance WHERE deal = ? ORDER BY distribution_date LIMIT 1",
        (selected_deal,))
    if not _first_pool.empty and _first_pool.iloc[0]["beginning_pool_balance"]:
        ORIG_BAL = _first_pool.iloc[0]["beginning_pool_balance"]
    else:
        _total = query_df("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal = ?", (selected_deal,))
        ORIG_BAL = _total.iloc[0]["s"] if not _total.empty and _total.iloc[0]["s"] else 405_000_000


# ── Data Loading ──────────────────────────────────────────

@st.cache_data(ttl=300)
def load_pool(deal):
    df = query_df("SELECT * FROM pool_performance WHERE deal = ? ORDER BY distribution_date", (deal,))
    if not df.empty:
        df["period"] = df["distribution_date"].apply(normalize_date)
        df = df.sort_values("period").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_loan_perf_agg(deal):
    """Load from pre-computed monthly_summary table (instant, ~50 rows)."""
    df = query_df("""
        SELECT * FROM monthly_summary WHERE deal = ? ORDER BY reporting_period_end
    """, (deal,))
    if df.empty:
        return df
    df["period"] = df["reporting_period_end"].apply(normalize_date)
    df = df.sort_values("period").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_loans(deal):
    df = query_df("SELECT * FROM loans WHERE deal = ?", (deal,))
    if not df.empty and "original_interest_rate" in df.columns:
        df["rate_pct"] = df["original_interest_rate"] * 100
    return df


@st.cache_data(ttl=300)
def load_losses_by_segment(deal, col):
    """Load losses by segment using pre-computed loan_loss_summary (instant)."""
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
    """Per-loan recovery analysis from pre-computed loan_loss_summary (instant)."""
    df = query_df("""
        SELECT
            s.asset_number,
            s.chargeoff_period,
            s.total_chargeoff,
            s.first_recovery_period,
            s.total_recovery as total_recoveries,
            l.obligor_credit_score,
            l.original_interest_rate,
            l.original_loan_amount
        FROM loan_loss_summary s
        LEFT JOIN loans l ON s.deal = l.deal AND s.asset_number = l.asset_number
        WHERE s.deal = ? AND s.total_chargeoff > 0
    """, (deal,))

    if df.empty:
        return df

    # Normalize dates and compute months between chargeoff and first recovery
    from datetime import datetime

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


pool_df = load_pool(selected_deal)
lp = load_loan_perf_agg(selected_deal)
loans_df = load_loans(selected_deal)

# Compute cumulative columns
if not lp.empty:
    lp["cum_chargeoffs"] = lp["period_chargeoffs"].cumsum()
    lp["cum_recoveries"] = lp["period_recoveries"].cumsum()
    lp["cum_net_losses"] = lp["cum_chargeoffs"] - lp["cum_recoveries"]
    lp["cum_loss_rate"] = lp["cum_net_losses"] / ORIG_BAL
    lp["dq_rate"] = lp["total_dq_balance"] / lp["total_balance"]
    lp["dq_30_rate"] = lp["dq_30_balance"] / lp["total_balance"]
    lp["dq_60_rate"] = lp["dq_60_balance"] / lp["total_balance"]
    lp["dq_90_rate"] = lp["dq_90_balance"] / lp["total_balance"]
    lp["dq_120_plus_rate"] = lp["dq_120_plus_balance"] / lp["total_balance"]
    lp["net_losses"] = lp["period_chargeoffs"] - lp["period_recoveries"]
    lp["excess_spread"] = lp["interest_collected"] + lp["period_recoveries"] - lp["est_servicing_fee"] - lp["net_losses"]
    lp["cum_excess"] = lp["excess_spread"].cumsum()
    lp["cum_interest"] = lp["interest_collected"].cumsum()
    lp["cum_principal"] = lp["principal_collected"].cumsum()
    lp["cum_recovery_rate"] = lp["cum_recoveries"] / lp["cum_chargeoffs"].replace(0, float("nan"))


# ── Tabs ──────────────────────────────────────────────────

tab_pool, tab_dq, tab_losses, tab_wf, tab_bs, tab_rec, tab_loans, tab_fields = st.tabs([
    "Pool Summary", "Delinquencies", "Losses", "Cash Waterfall",
    "Trust Balance Sheet", "Recovery Analysis", "Loan Explorer", "Data Fields"
])

# ═══════════════════════════════════════════════════════════
# TAB 1: POOL SUMMARY
# ═══════════════════════════════════════════════════════════
with tab_pool:
    # Use pool_performance (servicer cert) as primary source — no sawtooth
    has_pool = not pool_df.empty and "ending_pool_balance" in pool_df.columns and pool_df["ending_pool_balance"].notna().any()

    if not has_pool and lp.empty:
        st.info("No data yet.")
    else:
        if has_pool:
            latest_pool = pool_df.iloc[-1]
            cur_bal = latest_pool["ending_pool_balance"]
            cur_count = int(latest_pool["ending_pool_count"]) if pd.notna(latest_pool.get("ending_pool_count")) else None
        else:
            latest_pool = lp.iloc[-1]
            cur_bal = latest_pool["total_balance"]
            cur_count = int(latest_pool["active_loans"])

        # 2x2 grid works better on mobile than 4-across
        r1c1, r1c2 = st.columns(2)
        r1c1.metric("Original Balance", fmt_compact(ORIG_BAL))
        r1c2.metric("Current Balance", fmt_compact(cur_bal))
        r2c1, r2c2 = st.columns(2)
        r2c1.metric("Pool Factor", f"{cur_bal/ORIG_BAL:.2%}")
        if cur_count:
            r2c2.metric("Active Loans", f"{cur_count:,}")

        # Pool balance chart — use servicer cert data (smooth, authoritative)
        if has_pool:
            fig = px.area(pool_df, x="period", y="ending_pool_balance", title="Remaining Pool Balance",
                          labels={"period": "Distribution Date", "ending_pool_balance": "Balance ($)"})
        else:
            fig = px.area(lp, x="period", y="total_balance", title="Remaining Pool Balance",
                          labels={"period": "Period", "total_balance": "Balance ($)"})
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Loan count chart
        if has_pool and "ending_pool_count" in pool_df.columns:
            fig2 = px.line(pool_df.dropna(subset=["ending_pool_count"]), x="period", y="ending_pool_count",
                           title="Active Loan Count",
                           labels={"period": "Distribution Date", "ending_pool_count": "Loans"})
        elif not lp.empty:
            fig2 = px.line(lp, x="period", y="active_loans", title="Active Loan Count",
                           labels={"period": "Period", "active_loans": "Loans"})
        else:
            fig2 = None
        if fig2:
            fig2.update_layout(hovermode="x unified")
            st.plotly_chart(fig2, use_container_width=True)

        # WAC and WAM from pool_performance
        if has_pool:
            wac_data = pool_df[["period", "weighted_avg_apr"]].dropna()
            wam_data = pool_df[["period", "weighted_avg_remaining_term"]].dropna()
            if not wac_data.empty or not wam_data.empty:
                st.subheader("Pool Statistics")
                sc1, sc2 = st.columns(2)
                if not wac_data.empty:
                    with sc1:
                        fig_wac = px.line(wac_data, x="period", y="weighted_avg_apr", title="Weighted Average Coupon (WAC)")
                        fig_wac.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                        st.plotly_chart(fig_wac, use_container_width=True)
                if not wam_data.empty:
                    with sc2:
                        fig_wam = px.line(wam_data, x="period", y="weighted_avg_remaining_term",
                                          title="Weighted Average Remaining Term (months)")
                        fig_wam.update_layout(hovermode="x unified")
                        st.plotly_chart(fig_wam, use_container_width=True)

        # Note balances from pool_performance
        if has_pool:
            note_cols = ["note_balance_a1", "note_balance_a2", "note_balance_a3",
                         "note_balance_a4", "note_balance_b", "note_balance_c",
                         "note_balance_d", "note_balance_n"]
            avail = [c for c in note_cols if c in pool_df.columns and pool_df[c].notna().any()]
            if avail:
                st.subheader("Note Balances by Class")
                nm = pool_df[["period"] + avail].melt(id_vars=["period"], var_name="Class", value_name="Balance")
                nm["Class"] = nm["Class"].str.replace("note_balance_", "").str.upper()
                fig3 = px.area(nm, x="period", y="Balance", color="Class", title="Note Balances Over Time")
                fig3.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
                st.plotly_chart(fig3, use_container_width=True)

        # OC and Reserve from pool_performance
        if has_pool:
            oc_data = pool_df[["period", "overcollateralization_amount", "reserve_account_balance"]].dropna(how="all",
                subset=["overcollateralization_amount", "reserve_account_balance"])
            if not oc_data.empty:
                st.subheader("Credit Enhancement")
                fig_oc = go.Figure()
                if oc_data["overcollateralization_amount"].notna().any():
                    fig_oc.add_trace(go.Scatter(x=oc_data["period"], y=oc_data["overcollateralization_amount"],
                                                name="Overcollateralization", mode="lines"))
                if oc_data["reserve_account_balance"].notna().any():
                    fig_oc.add_trace(go.Scatter(x=oc_data["period"], y=oc_data["reserve_account_balance"],
                                                name="Reserve Account", mode="lines"))
                fig_oc.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified",
                                     title="Overcollateralization & Reserve Account")
                st.plotly_chart(fig_oc, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 2: DELINQUENCIES
# ═══════════════════════════════════════════════════════════
with tab_dq:
    if lp.empty:
        st.info("No data yet.")
    else:
        st.subheader("Delinquency Rates (% of Outstanding Balance)")
        view = st.radio("Show:", ["All (30+)", "30 Days", "60 Days", "90 Days", "120+ Days", "60+ Days"], horizontal=True)

        if view == "All (30+)":
            cols_map = {"dq_30_rate": "30d", "dq_60_rate": "60d", "dq_90_rate": "90d", "dq_120_plus_rate": "120+d"}
            m = lp[["period"] + list(cols_map.keys())].melt(id_vars=["period"], var_name="Bucket", value_name="Rate")
            m["Bucket"] = m["Bucket"].map(cols_map)
            fig = px.area(m, x="period", y="Rate", color="Bucket", title="Delinquency Rate by Bucket",
                          color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"])
        elif view == "60+ Days":
            t = lp.copy()
            t["r"] = (t["dq_60_balance"] + t["dq_90_balance"] + t["dq_120_plus_balance"]) / t["total_balance"]
            fig = px.line(t, x="period", y="r", title="60+ Day Delinquency Rate")
            fig.update_traces(line_color="#FF5722")
        else:
            cm = {"30 Days": "dq_30_rate", "60 Days": "dq_60_rate", "90 Days": "dq_90_rate", "120+ Days": "dq_120_plus_rate"}
            fig = px.line(lp, x="period", y=cm[view], title=f"{view} Delinquency Rate")
            fig.update_traces(line_color="#FF9800")
        fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Delinquency trigger from pool_performance
        if not pool_df.empty and "delinquency_trigger_level" in pool_df.columns:
            trig = pool_df[["period", "delinquency_trigger_level", "delinquency_trigger_actual"]].dropna()
            if not trig.empty:
                st.subheader("60+ Day Delinquency vs Trigger Level")
                fig_t = go.Figure()
                fig_t.add_trace(go.Scatter(x=trig["period"], y=trig["delinquency_trigger_level"],
                                           name="Trigger Level", line=dict(dash="dash", color="red")))
                fig_t.add_trace(go.Scatter(x=trig["period"], y=trig["delinquency_trigger_actual"],
                                           name="Actual 60+ DQ %", line=dict(color="blue")))
                fig_t.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                st.plotly_chart(fig_t, use_container_width=True)

        last = lp.iloc[-1]
        st.dataframe(pd.DataFrame({
            "Bucket": ["30d", "60d", "90d", "120+d", "Total"],
            "Count": [int(last["dq_30_count"]), int(last["dq_60_count"]), int(last["dq_90_count"]),
                      int(last["dq_120_plus_count"]), int(last["total_dq_count"])],
            "Balance": [f"${last['dq_30_balance']:,.0f}", f"${last['dq_60_balance']:,.0f}",
                        f"${last['dq_90_balance']:,.0f}", f"${last['dq_120_plus_balance']:,.0f}",
                        f"${last['total_dq_balance']:,.0f}"],
            "% Pool": [f"{last['dq_30_rate']:.2%}", f"{last['dq_60_rate']:.2%}",
                       f"{last['dq_90_rate']:.2%}", f"{last['dq_120_plus_rate']:.2%}",
                       f"{last['dq_rate']:.2%}"],
        }), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════
# TAB 3: LOSSES
# ═══════════════════════════════════════════════════════════
with tab_losses:
    if lp.empty:
        st.info("No data yet.")
    else:
        last = lp.iloc[-1]
        la1, la2 = st.columns(2)
        la1.metric("Cum Net Losses", fmt_compact(last['cum_net_losses']))
        la2.metric("Loss Rate", f"{last['cum_loss_rate']:.2%}")
        lb1, lb2 = st.columns(2)
        lb1.metric("Cum Gross Losses", fmt_compact(last['cum_chargeoffs']))
        lb2.metric("Through", last["period"])

        fig = px.area(lp, x="period", y="cum_loss_rate",
                      title=f"Cumulative Net Loss Rate (% of ${ORIG_BAL/1e6:.0f}M)")
        fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
        st.plotly_chart(fig, use_container_width=True)

        # Gross losses vs recoveries
        st.subheader("Cumulative Gross Losses vs Recoveries")
        fig_gr = go.Figure()
        fig_gr.add_trace(go.Scatter(x=lp["period"], y=lp["cum_chargeoffs"], name="Gross Chargeoffs", line=dict(color="#D32F2F")))
        fig_gr.add_trace(go.Scatter(x=lp["period"], y=lp["cum_recoveries"], name="Recoveries", line=dict(color="#4CAF50")))
        fig_gr.add_trace(go.Scatter(x=lp["period"], y=lp["cum_net_losses"], name="Net Losses", line=dict(color="#FF9800", dash="dash")))
        fig_gr.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig_gr, use_container_width=True)

        # Recovery rate
        st.subheader("Cumulative Recovery Rate (Recoveries / Gross Chargeoffs)")
        fig_rr = px.line(lp.dropna(subset=["cum_recovery_rate"]), x="period", y="cum_recovery_rate",
                         title="Cumulative Recovery Rate")
        fig_rr.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
        fig_rr.update_traces(line_color="#4CAF50")
        st.plotly_chart(fig_rr, use_container_width=True)

        # Monthly chargeoffs vs recoveries
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=lp["period"], y=lp["period_chargeoffs"], name="Chargeoffs", marker_color="#D32F2F"))
        fig2.add_trace(go.Bar(x=lp["period"], y=lp["period_recoveries"], name="Recoveries", marker_color="#4CAF50"))
        fig2.update_layout(title="Monthly Chargeoffs vs Recoveries", barmode="group",
                           yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

        # Loss by credit score
        st.subheader("Losses by Credit Score")
        lbs = load_losses_by_segment(selected_deal, "obligor_credit_score")
        if not lbs.empty:
            lbs["s"] = pd.to_numeric(lbs["segment"], errors="coerce")
            lbs = lbs.dropna(subset=["s"])
            lbs["bucket"] = pd.cut(lbs["s"], bins=[0,580,620,660,700,740,780,820,900],
                                   labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
            b = lbs.groupby("bucket", observed=True).agg({"loan_count":"sum","original_balance":"sum","total_chargeoffs":"sum","total_recoveries":"sum"}).reset_index()
            b["net"] = b["total_chargeoffs"] - b["total_recoveries"]
            b["rate"] = b["net"] / b["original_balance"]
            d = b[["bucket","loan_count","original_balance","net","rate"]].copy()
            d.columns = ["Score","Loans","Orig Balance","Net Losses","Loss Rate"]
            d["Orig Balance"] = d["Orig Balance"].apply(lambda x: f"${x:,.0f}")
            d["Net Losses"] = d["Net Losses"].apply(lambda x: f"${x:,.0f}")
            d["Loss Rate"] = d["Loss Rate"].apply(lambda x: f"{x:.2%}")
            d["Loans"] = d["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(d, use_container_width=True, hide_index=True)

        # Loss by rate
        st.subheader("Losses by Interest Rate")
        lbr = load_losses_by_segment(selected_deal, "original_interest_rate")
        if not lbr.empty:
            lbr["r"] = pd.to_numeric(lbr["segment"], errors="coerce")
            lbr = lbr.dropna(subset=["r"])
            lbr["bucket"] = pd.cut(lbr["r"], bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                                   labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
            b = lbr.groupby("bucket", observed=True).agg({"loan_count":"sum","original_balance":"sum","total_chargeoffs":"sum","total_recoveries":"sum"}).reset_index()
            b["net"] = b["total_chargeoffs"] - b["total_recoveries"]
            b["rate"] = b["net"] / b["original_balance"]
            d = b[["bucket","loan_count","original_balance","net","rate"]].copy()
            d.columns = ["Rate","Loans","Orig Balance","Net Losses","Loss Rate"]
            d["Orig Balance"] = d["Orig Balance"].apply(lambda x: f"${x:,.0f}")
            d["Net Losses"] = d["Net Losses"].apply(lambda x: f"${x:,.0f}")
            d["Loss Rate"] = d["Loss Rate"].apply(lambda x: f"{x:.2%}")
            d["Loans"] = d["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(d, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════
# TAB 4: CASH WATERFALL
# ═══════════════════════════════════════════════════════════
with tab_wf:
    if lp.empty:
        st.info("No data yet.")
    else:
        st.subheader("Monthly Cash Flows")

        wf = lp[["period", "interest_collected", "principal_collected", "period_recoveries",
                  "est_servicing_fee", "period_chargeoffs", "net_losses", "excess_spread"]].copy()
        wf.columns = ["Period", "Interest", "Principal", "Recoveries", "Servicing Fee",
                       "Chargeoffs", "Net Losses", "Excess Spread"]

        # Sum row
        sums = wf.select_dtypes(include="number").sum()
        sum_row = pd.DataFrame([["TOTAL"] + sums.tolist()], columns=wf.columns)
        wf_display = pd.concat([wf, sum_row], ignore_index=True)

        # Dollar table — compact format for mobile readability
        st.markdown("### Dollar Amounts")
        fmt_d = wf_display.copy()
        for c in fmt_d.columns[1:]:
            fmt_d[c] = fmt_d[c].apply(lambda x: fmt_compact(x) if pd.notna(x) else "")
        st.dataframe(fmt_d, use_container_width=True, hide_index=True, height=400)

        # Normalized table
        st.markdown(f"### Normalized (% of {fmt_compact(ORIG_BAL)} Original Balance)")
        norm = wf_display.copy()
        for c in norm.columns[1:]:
            norm[c] = wf_display[c].apply(lambda x: f"{x/ORIG_BAL:.4%}" if pd.notna(x) else "")
        st.dataframe(norm, use_container_width=True, hide_index=True, height=400)

        # Cumulative excess spread chart
        st.subheader("Cumulative Excess Spread (Cash to Residual)")
        fig = px.area(lp, x="period", y="cum_excess", title="Cumulative Excess Spread")
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        fig.update_traces(line_color="#388E3C", fillcolor="rgba(56,142,60,0.2)")
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 5: TRUST BALANCE SHEET
# ═══════════════════════════════════════════════════════════
with tab_bs:
    if pool_df.empty and lp.empty:
        st.info("No data yet.")
    else:
        st.subheader("Trust Balance Sheet Over Time")

        # Assets from loan_performance
        assets = lp[["period", "total_balance", "dq_30_balance", "dq_60_balance",
                      "dq_90_balance", "dq_120_plus_balance", "active_loans",
                      "cum_chargeoffs", "cum_recoveries", "cum_net_losses"]].copy()
        assets["performing"] = (assets["total_balance"] - assets["dq_30_balance"]
                                - assets["dq_60_balance"] - assets["dq_90_balance"]
                                - assets["dq_120_plus_balance"])

        # Liabilities from pool_performance (note balances, OC, reserves)
        if not pool_df.empty:
            liab_cols = ["period", "note_balance_a1", "note_balance_a2", "note_balance_a3",
                         "note_balance_a4", "note_balance_b", "note_balance_c",
                         "note_balance_d", "note_balance_n",
                         "overcollateralization_amount", "reserve_account_balance"]
            liab = pool_df[[c for c in liab_cols if c in pool_df.columns]].copy()
            rated_notes = ["note_balance_a1", "note_balance_a2", "note_balance_a3",
                           "note_balance_a4", "note_balance_b", "note_balance_c", "note_balance_d"]
            avail_notes = [c for c in rated_notes if c in liab.columns]
            liab["total_rated_debt"] = liab[avail_notes].fillna(0).sum(axis=1)
            if "note_balance_n" in liab.columns:
                liab["total_all_debt"] = liab["total_rated_debt"] + liab["note_balance_n"].fillna(0)
            else:
                liab["total_all_debt"] = liab["total_rated_debt"]
            merged = assets.merge(liab, on="period", how="left")
        else:
            merged = assets.copy()

        # ── Asset side table ──
        st.markdown("### Assets (Loan Pool by Status) — Dollar Amounts")
        asset_display = merged[["period", "performing", "dq_30_balance", "dq_60_balance",
                                "dq_90_balance", "dq_120_plus_balance", "total_balance",
                                "cum_chargeoffs", "cum_recoveries", "cum_net_losses"]].copy()
        asset_display.columns = ["Period", "Performing", "30d DQ", "60d DQ", "90d DQ",
                                  "120+ DQ", "Total Pool", "Cum Gross Losses", "Cum Recoveries", "Cum Net Losses"]
        a_fmt = asset_display.copy()
        for c in a_fmt.columns[1:]:
            a_fmt[c] = a_fmt[c].apply(lambda x: fmt_compact(x) if pd.notna(x) and x != 0 else "-")
        st.dataframe(a_fmt, use_container_width=True, hide_index=True, height=400)

        # Normalized assets
        st.markdown(f"### Assets — Normalized (% of ${ORIG_BAL/1e6:.0f}M)")
        a_norm = asset_display.copy()
        for c in a_norm.columns[1:]:
            a_norm[c] = asset_display[c].apply(lambda x: f"{x/ORIG_BAL:.2%}" if pd.notna(x) else "-")
        st.dataframe(a_norm, use_container_width=True, hide_index=True, height=400)

        # ── Liability side table ──
        if "total_rated_debt" in merged.columns:
            st.markdown("### Liabilities & Equity — Dollar Amounts")
            liab_display_cols = ["period"]
            liab_names = ["Period"]
            for nc in ["note_balance_a1", "note_balance_a2", "note_balance_a3", "note_balance_a4",
                        "note_balance_b", "note_balance_c", "note_balance_d"]:
                if nc in merged.columns:
                    liab_display_cols.append(nc)
                    liab_names.append(nc.replace("note_balance_", "").upper())
            liab_display_cols += ["total_rated_debt"]
            liab_names += ["Total Rated Debt"]
            if "note_balance_n" in merged.columns:
                liab_display_cols += ["note_balance_n"]
                liab_names += ["Class N"]
            liab_display_cols += ["total_all_debt"]
            liab_names += ["Total All Debt"]
            if "overcollateralization_amount" in merged.columns:
                liab_display_cols += ["overcollateralization_amount"]
                liab_names += ["OC"]
            if "reserve_account_balance" in merged.columns:
                liab_display_cols += ["reserve_account_balance"]
                liab_names += ["Reserve"]

            liab_df = merged[liab_display_cols].copy()
            liab_df.columns = liab_names
            l_fmt = liab_df.copy()
            for c in l_fmt.columns[1:]:
                l_fmt[c] = l_fmt[c].apply(lambda x: fmt_compact(x) if pd.notna(x) and x != 0 else "-")
            st.dataframe(l_fmt, use_container_width=True, hide_index=True, height=400)

            # Normalized liabilities
            st.markdown(f"### Liabilities & Equity — Normalized (% of ${ORIG_BAL/1e6:.0f}M)")
            l_norm = liab_df.copy()
            for c in l_norm.columns[1:]:
                l_norm[c] = liab_df[c].apply(lambda x: f"{x/ORIG_BAL:.2%}" if pd.notna(x) else "-")
            st.dataframe(l_norm, use_container_width=True, hide_index=True, height=400)


# ═══════════════════════════════════════════════════════════
# TAB 6: RECOVERY ANALYSIS
# ═══════════════════════════════════════════════════════════
with tab_rec:
    rec_df = load_recovery_data(selected_deal)
    if rec_df.empty:
        st.info("No chargeoff data found.")
    else:
        st.subheader("Recovery Analysis (Per-Loan)")

        total_co = len(rec_df)
        with_rec = rec_df["has_recovery"].sum()
        no_rec = total_co - with_rec
        avg_rate = rec_df.loc[rec_df["has_recovery"], "recovery_rate"].mean()
        median_months = rec_df.loc[rec_df["has_recovery"], "months_to_recovery"].median()
        total_co_amt = rec_df["total_chargeoff"].sum()
        total_rec_amt = rec_df.loc[rec_df["has_recovery"], "total_recoveries"].sum()

        r1a, r1b = st.columns(2)
        r1a.metric("Charged-Off Loans", f"{total_co:,}")
        r1b.metric("With Recovery", f"{int(with_rec):,} ({with_rec/total_co:.0%})")
        r2a, r2b = st.columns(2)
        r2a.metric("Avg Recovery Rate", f"{avg_rate:.1%}" if pd.notna(avg_rate) else "N/A")
        r2b.metric("Median Months", f"{median_months:.0f}" if pd.notna(median_months) else "N/A")
        r3a, r3b = st.columns(2)
        r3a.metric("Total Chargeoffs", fmt_compact(total_co_amt))
        r3b.metric("Total Recovered", f"{fmt_compact(total_rec_amt)} ({total_rec_amt/total_co_amt:.1%})")

        # Months to first recovery histogram
        rec_with = rec_df[rec_df["has_recovery"] & rec_df["months_to_recovery"].notna()].copy()
        if not rec_with.empty:
            st.subheader("Time from Chargeoff to First Recovery")
            fig = px.histogram(rec_with, x="months_to_recovery", nbins=30,
                               title="Months from Chargeoff to First Recovery",
                               labels={"months_to_recovery": "Months"},
                               color_discrete_sequence=["#1976D2"])
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

            # Summary stats
            stats = rec_with["months_to_recovery"].describe()
            st.dataframe(pd.DataFrame({
                "Statistic": ["Count", "Mean", "Median", "Min", "Max", "Std Dev"],
                "Months": [f"{stats['count']:.0f}", f"{stats['mean']:.1f}", f"{stats['50%']:.1f}",
                           f"{stats['min']:.0f}", f"{stats['max']:.0f}", f"{stats['std']:.1f}"],
            }), use_container_width=True, hide_index=True)

        # Recovery rate distribution
        rec_rates = rec_df[rec_df["has_recovery"]]["recovery_rate"].dropna()
        if not rec_rates.empty:
            st.subheader("Recovery Rate Distribution (per loan)")
            # Cap at 100% for display
            fig2 = px.histogram(rec_rates.clip(upper=1.5), nbins=40,
                                title="Recovery Rate per Charged-Off Loan (recoveries / chargeoff amount)",
                                labels={"value": "Recovery Rate"},
                                color_discrete_sequence=["#4CAF50"])
            fig2.update_layout(xaxis_tickformat=".0%", showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        # Recovery rate by credit score bucket
        st.subheader("Recovery Rate by Credit Score")
        rec_scored = rec_df[rec_df["obligor_credit_score"].notna()].copy()
        if not rec_scored.empty:
            rec_scored["score_bucket"] = pd.cut(
                rec_scored["obligor_credit_score"],
                bins=[0, 580, 620, 660, 700, 740, 780, 820, 900],
                labels=["<580", "580-619", "620-659", "660-699", "700-739", "740-779", "780-819", "820+"],
                right=False)
            by_score = rec_scored.groupby("score_bucket", observed=True).agg(
                chargeoff_count=("asset_number", "count"),
                with_recovery=("has_recovery", "sum"),
                total_chargeoff=("total_chargeoff", "sum"),
                total_recovered=("total_recoveries", lambda x: x.dropna().sum()),
            ).reset_index()
            by_score["recovery_rate"] = by_score["total_recovered"] / by_score["total_chargeoff"]
            by_score["pct_with_recovery"] = by_score["with_recovery"] / by_score["chargeoff_count"]

            d = by_score.copy()
            d.columns = ["Score", "Chargeoffs", "With Recovery", "Total Chargeoff", "Total Recovered", "Recovery Rate", "% With Recovery"]
            d["Total Chargeoff"] = d["Total Chargeoff"].apply(lambda x: fmt_compact(x))
            d["Total Recovered"] = d["Total Recovered"].apply(lambda x: fmt_compact(x))
            d["Recovery Rate"] = d["Recovery Rate"].apply(lambda x: f"{x:.1%}")
            d["% With Recovery"] = d["% With Recovery"].apply(lambda x: f"{x:.0%}")
            d["Chargeoffs"] = d["Chargeoffs"].apply(lambda x: f"{x:,}")
            d["With Recovery"] = d["With Recovery"].apply(lambda x: f"{int(x):,}")
            st.dataframe(d, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════
# TAB 7: LOAN EXPLORER
# ═══════════════════════════════════════════════════════════
with tab_loans:
    if loans_df.empty:
        st.info("No data yet.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            s = loans_df["obligor_credit_score"].dropna()
            if not s.empty:
                fig = px.histogram(s, nbins=30, title="Credit Score Distribution", color_discrete_sequence=["#1976D2"])
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            a = loans_df["original_loan_amount"].dropna()
            if not a.empty:
                fig = px.histogram(a, nbins=30, title="Loan Amount Distribution", color_discrete_sequence=["#388E3C"])
                fig.update_layout(xaxis_tickformat="$,.0f", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        c3, c4 = st.columns(2)
        with c3:
            m = loans_df["vehicle_manufacturer"].dropna().value_counts().head(15)
            if not m.empty:
                fig = px.bar(x=m.values, y=m.index, orientation="h", title="Top 15 Manufacturers",
                             color_discrete_sequence=["#FF9800"])
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
        with c4:
            s = loans_df["obligor_geographic_location"].dropna().value_counts().head(15)
            if not s.empty:
                fig = px.bar(x=s.values, y=s.index, orientation="h", title="Top 15 States",
                             color_discrete_sequence=["#7B1FA2"])
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        if "rate_pct" in loans_df.columns:
            rs = loans_df[["rate_pct", "obligor_credit_score"]].dropna()
            if len(rs) > 0:
                st.subheader("Interest Rate vs Credit Score")
                sample = rs.sample(min(5000, len(rs)), random_state=42)
                fig = px.scatter(sample, x="obligor_credit_score", y="rate_pct",
                                 labels={"obligor_credit_score": "Credit Score", "rate_pct": "Rate (%)"},
                                 opacity=0.3)
                fig.update_layout(yaxis_ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Portfolio Statistics")
        sd = {}
        if "original_loan_amount" in loans_df.columns: sd["Amount ($)"] = loans_df["original_loan_amount"].describe()
        if "rate_pct" in loans_df.columns: sd["Rate (%)"] = loans_df["rate_pct"].describe()
        if "original_loan_term" in loans_df.columns: sd["Term (mo)"] = loans_df["original_loan_term"].describe()
        if "obligor_credit_score" in loans_df.columns: sd["FICO"] = loans_df["obligor_credit_score"].describe()
        if sd:
            st.dataframe(pd.DataFrame(sd).style.format("{:.1f}"), use_container_width=True)


# ═══════════════════════════════════════════════════════════
# TAB 8: DATA FIELDS
# ═══════════════════════════════════════════════════════════
with tab_fields:
    st.subheader("Available Data Fields")
    st.markdown("### Loan Static Data")
    st.dataframe(pd.DataFrame({
        "Field": ["asset_number","originator_name","origination_date","original_loan_amount",
                  "original_loan_term","original_interest_rate","loan_maturity_date","original_ltv",
                  "vehicle_manufacturer","vehicle_model","vehicle_new_used","vehicle_model_year",
                  "vehicle_type","vehicle_value","obligor_credit_score","obligor_credit_score_type",
                  "obligor_geographic_location","co_obligor_indicator","payment_to_income_ratio",
                  "income_verification_level","payment_type","subvention_indicator"],
        "Description": ["Unique loan ID","Originator","Month/year originated","Loan amount ($)",
                        "Term (months)","Rate (decimal, 0.0599=5.99%)","Maturity date","Loan-to-value",
                        "Vehicle make","Vehicle model","1=New, 2=Used","Model year",
                        "Type code","Value ($)","Credit score","Score model",
                        "State","Co-borrower","Payment/income (decimal)",
                        "Verification level","Payment type","Subsidized rate"],
    }), use_container_width=True, hide_index=True)

    st.markdown("### Monthly Performance Data")
    st.dataframe(pd.DataFrame({
        "Field": ["reporting_period_end","beginning_balance","ending_balance","scheduled_payment",
                  "actual_amount_paid","actual_interest_collected","actual_principal_collected",
                  "current_interest_rate","current_delinquency_status","remaining_term",
                  "paid_through_date","zero_balance_code","zero_balance_date",
                  "charged_off_amount","recoveries","modification_indicator","servicing_fee"],
        "Description": ["Period end date","Start balance ($)","End balance ($)","Scheduled payment ($)",
                        "Actual paid ($)","Interest ($)","Principal ($)",
                        "Current rate (decimal)","Months delinquent (0=current,1=30d,2=60d,3=90d,4+=120d+)",
                        "Months remaining","Interest paid through",
                        "1=prepaid,2=matured,3=charged off","When zeroed",
                        "Chargeoff amount ($)","Recovery amount ($)","Modified (true/false)","Servicing fee rate"],
    }), use_container_width=True, hide_index=True)

    st.markdown("### Pool Performance Data (from Servicer Certificate)")
    st.dataframe(pd.DataFrame({
        "Field": ["distribution_date","beginning/ending_pool_balance","beginning/ending_pool_count",
                  "interest_collections","principal_collections","recoveries",
                  "gross_charged_off_amount","cumulative_net_losses","cumulative_gross_losses",
                  "delinquent_31_60/61_90/91_120_balance","note_balance_a1 through n",
                  "overcollateralization_amount","reserve_account_balance",
                  "weighted_avg_apr","delinquency_trigger_level/actual",
                  "extensions_count/balance"],
        "Description": ["Distribution date","Pool balance ($)","Loan count",
                        "Interest collections ($)","Principal collections ($)","Recoveries ($)",
                        "Period gross chargeoffs ($)","Cumulative net losses ($)","Cumulative gross losses ($)",
                        "Delinquency bucket balances ($)","Note class balances ($)",
                        "Overcollateralization ($)","Reserve account ($)",
                        "Weighted avg coupon","Delinquency trigger %",
                        "Extension count and balance"],
    }), use_container_width=True, hide_index=True)
