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


@st.cache_resource
def get_db():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query(sql, conn, params=params)


st.title("Carvana Auto Receivables Trust")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")

conn = get_db()
if conn is None:
    st.error(f"Database not found at `{DB_PATH}`. Run the ingestion script first.")
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
    loan_count = query_df("SELECT COUNT(*) as n FROM loans WHERE deal = ?", (selected_deal,))
    perf_periods = query_df("SELECT COUNT(DISTINCT reporting_period_end) as n FROM loan_performance WHERE deal = ?", (selected_deal,))
    if not loan_count.empty:
        st.metric("Unique Loans", f"{int(loan_count.iloc[0]['n']):,}")
    if not perf_periods.empty:
        st.metric("Monthly Periods", int(perf_periods.iloc[0]["n"]))
    st.markdown("---")
    st.caption("Data sourced from SEC EDGAR ABS-EE filings")

ORIGINAL_BALANCE = deal_cfg.get("original_pool_balance", 405_000_000)


# --- Data Loading ---

@st.cache_data(ttl=300)
def load_loan_perf_agg(deal: str) -> pd.DataFrame:
    """Aggregate loan performance by period. Normalize dates for consistent grouping."""
    df = query_df("""
        SELECT
            reporting_period_end as raw_date,
            COUNT(CASE WHEN ending_balance > 0 THEN 1 END) as active_loans,
            SUM(CASE WHEN ending_balance > 0 THEN ending_balance ELSE 0 END) as total_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 1 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as total_dq_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 1 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_30_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 2 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_60_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 3 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_90_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 4 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_120_plus_balance,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 1 AND ending_balance > 0 THEN 1 END) as total_dq_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 1 AND ending_balance > 0 THEN 1 END) as dq_30_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 2 AND ending_balance > 0 THEN 1 END) as dq_60_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 3 AND ending_balance > 0 THEN 1 END) as dq_90_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 4 AND ending_balance > 0 THEN 1 END) as dq_120_plus_count,
            SUM(COALESCE(charged_off_amount, 0)) as period_chargeoffs,
            SUM(COALESCE(recoveries, 0)) as period_recoveries
        FROM loan_performance WHERE deal = ?
        GROUP BY reporting_period_end
        ORDER BY reporting_period_end
    """, (deal,))

    if df.empty:
        return df

    # Normalize dates: convert various formats to YYYY-MM-DD for consistent sorting
    def normalize_date(d):
        if not d:
            return d
        d = str(d).strip()
        # Handle MM-DD-YYYY or MM/DD/YYYY
        for sep in ["-", "/"]:
            parts = d.split(sep)
            if len(parts) == 3:
                if len(parts[0]) == 4:  # YYYY-MM-DD already
                    return d
                if len(parts[2]) == 4:  # MM-DD-YYYY
                    return f"{parts[2]}{sep}{parts[0].zfill(2)}{sep}{parts[1].zfill(2)}"
        return d

    df["period"] = df["raw_date"].apply(normalize_date)
    df = df.sort_values("period").reset_index(drop=True)
    return df


@st.cache_data(ttl=300)
def load_loans(deal: str) -> pd.DataFrame:
    df = query_df("SELECT * FROM loans WHERE deal = ?", (deal,))
    if not df.empty and "original_interest_rate" in df.columns:
        df["original_interest_rate_pct"] = df["original_interest_rate"] * 100
    return df


@st.cache_data(ttl=300)
def load_losses_by_segment(deal: str, segment_col: str) -> pd.DataFrame:
    """Load cumulative losses grouped by a loan attribute.

    FIX: Aggregate performance per-loan FIRST, then join to loans table.
    This prevents original_balance from being multiplied by # of periods.
    """
    return query_df(f"""
        SELECT
            l.{segment_col} as segment,
            COUNT(*) as loan_count,
            SUM(l.original_loan_amount) as original_balance,
            SUM(COALESCE(perf.total_chargeoffs, 0)) as total_chargeoffs,
            SUM(COALESCE(perf.total_recoveries, 0)) as total_recoveries
        FROM loans l
        LEFT JOIN (
            SELECT deal, asset_number,
                   SUM(COALESCE(charged_off_amount, 0)) as total_chargeoffs,
                   SUM(COALESCE(recoveries, 0)) as total_recoveries
            FROM loan_performance
            WHERE deal = ?
            GROUP BY deal, asset_number
        ) perf ON l.deal = perf.deal AND l.asset_number = perf.asset_number
        WHERE l.deal = ?
        AND l.{segment_col} IS NOT NULL
        GROUP BY l.{segment_col}
        ORDER BY l.{segment_col}
    """, (deal, deal))


loans_df = load_loans(selected_deal)
loan_perf_df = load_loan_perf_agg(selected_deal)

if not loan_perf_df.empty:
    loan_perf_df["cumulative_chargeoffs"] = loan_perf_df["period_chargeoffs"].cumsum()
    loan_perf_df["cumulative_recoveries"] = loan_perf_df["period_recoveries"].cumsum()
    loan_perf_df["cumulative_net_losses"] = loan_perf_df["cumulative_chargeoffs"] - loan_perf_df["cumulative_recoveries"]
    loan_perf_df["cumulative_loss_rate"] = loan_perf_df["cumulative_net_losses"] / ORIGINAL_BALANCE
    loan_perf_df["dq_rate"] = loan_perf_df["total_dq_balance"] / loan_perf_df["total_balance"]
    loan_perf_df["dq_30_rate"] = loan_perf_df["dq_30_balance"] / loan_perf_df["total_balance"]
    loan_perf_df["dq_60_rate"] = loan_perf_df["dq_60_balance"] / loan_perf_df["total_balance"]
    loan_perf_df["dq_90_rate"] = loan_perf_df["dq_90_balance"] / loan_perf_df["total_balance"]
    loan_perf_df["dq_120_plus_rate"] = loan_perf_df["dq_120_plus_balance"] / loan_perf_df["total_balance"]


@st.cache_data(ttl=300)
def load_waterfall(deal: str) -> pd.DataFrame:
    """Load monthly cash flow components for waterfall analysis."""
    df = query_df("""
        SELECT
            reporting_period_end as raw_date,
            SUM(CASE WHEN beginning_balance > 0 THEN beginning_balance ELSE 0 END) as total_beginning_balance,
            SUM(CASE WHEN ending_balance > 0 THEN ending_balance ELSE 0 END) as total_ending_balance,
            SUM(COALESCE(actual_amount_paid, 0)) as total_payments,
            SUM(COALESCE(actual_interest_collected, 0)) as interest_collected,
            SUM(COALESCE(actual_principal_collected, 0)) as principal_collected,
            SUM(COALESCE(recoveries, 0)) as recoveries,
            SUM(COALESCE(charged_off_amount, 0)) as chargeoffs,
            -- Servicing fee: the field stores a rate (e.g. 0.0054 = 0.54% annual).
            -- Estimate monthly dollar fee = balance * rate / 12
            SUM(CASE WHEN beginning_balance > 0 AND servicing_fee > 0
                THEN beginning_balance * servicing_fee / 12.0 ELSE 0 END) as est_servicing_fee
        FROM loan_performance WHERE deal = ?
        GROUP BY reporting_period_end
        ORDER BY reporting_period_end
    """, (deal,))

    if df.empty:
        return df

    # Normalize dates
    def normalize_date(d):
        if not d:
            return d
        d = str(d).strip()
        for sep in ["-", "/"]:
            parts = d.split(sep)
            if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
                return f"{parts[2]}{sep}{parts[0].zfill(2)}{sep}{parts[1].zfill(2)}"
        return d

    df["period"] = df["raw_date"].apply(normalize_date)
    df = df.sort_values("period").reset_index(drop=True)

    # Compute waterfall components
    # Available Funds = Interest + Recoveries
    df["available_funds"] = df["interest_collected"] + df["recoveries"]

    # After servicing fee
    df["after_servicing"] = df["available_funds"] - df["est_servicing_fee"]

    # Net losses this period
    df["net_losses"] = df["chargeoffs"] - df["recoveries"]

    # Pool principal reduction (positive = paydown)
    df["pool_paydown"] = df["total_beginning_balance"] - df["total_ending_balance"] - df["chargeoffs"]

    # Total debt principal paid ~ principal collected (what goes to noteholders)
    df["debt_principal_paid"] = df["principal_collected"]

    # Excess spread = interest available - servicing - net losses (approx)
    # This is what's available to OC build or residual holders
    df["excess_spread"] = df["after_servicing"] - df["net_losses"]

    # Residual cash = total collections - debt service - servicing - losses
    # Approximation: what's left after paying down notes and covering losses
    df["residual_cash"] = (df["interest_collected"] + df["principal_collected"] + df["recoveries"]
                           - df["est_servicing_fee"] - df["debt_principal_paid"] - df["net_losses"])

    # Cumulative
    df["cum_interest_collected"] = df["interest_collected"].cumsum()
    df["cum_principal_collected"] = df["principal_collected"].cumsum()
    df["cum_servicing_fees"] = df["est_servicing_fee"].cumsum()
    df["cum_chargeoffs"] = df["chargeoffs"].cumsum()
    df["cum_recoveries"] = df["recoveries"].cumsum()
    df["cum_net_losses"] = df["net_losses"].cumsum()
    df["cum_excess_spread"] = df["excess_spread"].cumsum()

    return df


tab_pool, tab_dq, tab_losses, tab_waterfall, tab_loans, tab_fields = st.tabs([
    "Pool Summary", "Delinquencies", "Losses", "Cash Waterfall", "Loan Explorer", "Data Fields"
])

# ============================================================
# TAB 1: POOL SUMMARY
# ============================================================
with tab_pool:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        last = loan_perf_df.iloc[-1]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Original Pool Balance", f"${ORIGINAL_BALANCE:,.0f}")
        col2.metric("Current Pool Balance", f"${last['total_balance']:,.0f}")
        col3.metric("Pool Factor", f"{last['total_balance'] / ORIGINAL_BALANCE:.2%}")
        col4.metric("Active Loans", f"{int(last['active_loans']):,}")

        st.subheader("Remaining Pool Balance")
        fig = px.area(loan_perf_df, x="period", y="total_balance",
                      labels={"period": "Reporting Period", "total_balance": "Balance ($)"})
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Active Loan Count")
        fig2 = px.line(loan_perf_df, x="period", y="active_loans",
                       labels={"period": "Reporting Period", "active_loans": "Active Loans"})
        fig2.update_layout(hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

# ============================================================
# TAB 2: DELINQUENCIES (as % of outstanding balance)
# ============================================================
with tab_dq:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        st.subheader("Delinquency Rates (% of Outstanding Balance)")

        dq_view = st.radio(
            "Show delinquencies:",
            ["All (30+ Days)", "30 Days", "60 Days", "90 Days", "120+ Days", "60+ Days"],
            horizontal=True,
        )

        if dq_view == "All (30+ Days)":
            dq_rate_cols = {"dq_30_rate": "30 Days", "dq_60_rate": "60 Days",
                            "dq_90_rate": "90 Days", "dq_120_plus_rate": "120+ Days"}
            dq_melted = loan_perf_df[["period"] + list(dq_rate_cols.keys())].melt(
                id_vars=["period"], var_name="Bucket", value_name="Rate")
            dq_melted["Bucket"] = dq_melted["Bucket"].map(dq_rate_cols)
            fig = px.area(dq_melted, x="period", y="Rate", color="Bucket",
                          title="Delinquency Rate by Bucket (% of Pool)",
                          labels={"period": "Reporting Period"},
                          color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"])
        elif dq_view == "60+ Days":
            df_60plus = loan_perf_df.copy()
            df_60plus["dq_60_plus_rate"] = (df_60plus["dq_60_balance"] + df_60plus["dq_90_balance"] +
                                             df_60plus["dq_120_plus_balance"]) / df_60plus["total_balance"]
            fig = px.line(df_60plus, x="period", y="dq_60_plus_rate",
                          title="60+ Day Delinquency Rate",
                          labels={"period": "Reporting Period", "dq_60_plus_rate": "Rate"})
            fig.update_traces(line_color="#FF5722")
        else:
            col_map = {"30 Days": "dq_30_rate", "60 Days": "dq_60_rate",
                       "90 Days": "dq_90_rate", "120+ Days": "dq_120_plus_rate"}
            col = col_map[dq_view]
            fig = px.line(loan_perf_df, x="period", y=col,
                          title=f"{dq_view} Delinquency Rate",
                          labels={"period": "Reporting Period", col: "Rate"})
            fig.update_traces(line_color="#FF9800")

        fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Summary table
        st.subheader("Latest Period Delinquency Summary")
        last = loan_perf_df.iloc[-1]
        dq_summary = pd.DataFrame({
            "Bucket": ["30 Days", "60 Days", "90 Days", "120+ Days", "Total 30+"],
            "Count": [int(last["dq_30_count"]), int(last["dq_60_count"]),
                      int(last["dq_90_count"]), int(last["dq_120_plus_count"]),
                      int(last["total_dq_count"])],
            "Balance": [f"${last['dq_30_balance']:,.0f}", f"${last['dq_60_balance']:,.0f}",
                        f"${last['dq_90_balance']:,.0f}", f"${last['dq_120_plus_balance']:,.0f}",
                        f"${last['total_dq_balance']:,.0f}"],
            "% of Pool": [f"{last['dq_30_rate']:.2%}", f"{last['dq_60_rate']:.2%}",
                          f"{last['dq_90_rate']:.2%}", f"{last['dq_120_plus_rate']:.2%}",
                          f"{last['dq_rate']:.2%}"],
        })
        st.dataframe(dq_summary, use_container_width=True, hide_index=True)

# ============================================================
# TAB 3: LOSSES
# ============================================================
with tab_losses:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        st.subheader("Loss Analysis")
        last = loan_perf_df.iloc[-1]
        col1, col2, col3 = st.columns(3)
        col1.metric("Cumulative Net Losses", f"${last['cumulative_net_losses']:,.0f}")
        col2.metric("Cumulative Loss Rate", f"{last['cumulative_loss_rate']:.2%}")
        col3.metric("Through Period", last["period"])

        fig = px.area(loan_perf_df, x="period", y="cumulative_loss_rate",
                      title=f"Cumulative Net Loss Rate (% of ${ORIGINAL_BALANCE/1e6:.0f}M Original Balance)",
                      labels={"period": "Reporting Period", "cumulative_loss_rate": "Loss Rate"})
        fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
        st.plotly_chart(fig, use_container_width=True)

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=loan_perf_df["period"], y=loan_perf_df["period_chargeoffs"],
                              name="Charge-offs", marker_color="#D32F2F"))
        fig2.add_trace(go.Bar(x=loan_perf_df["period"], y=loan_perf_df["period_recoveries"],
                              name="Recoveries", marker_color="#4CAF50"))
        fig2.update_layout(title="Monthly Charge-offs vs Recoveries",
                           barmode="group", yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

        # --- Losses by Credit Score ---
        st.subheader("Cumulative Losses by Credit Score")
        loss_by_score = load_losses_by_segment(selected_deal, "obligor_credit_score")
        if not loss_by_score.empty:
            loss_by_score["score"] = pd.to_numeric(loss_by_score["segment"], errors="coerce")
            loss_by_score = loss_by_score.dropna(subset=["score"])
            bins = [0, 580, 620, 660, 700, 740, 780, 820, 900]
            labels = ["<580", "580-619", "620-659", "660-699", "700-739", "740-779", "780-819", "820+"]
            loss_by_score["bucket"] = pd.cut(loss_by_score["score"], bins=bins, labels=labels, right=False)
            b = loss_by_score.groupby("bucket", observed=True).agg(
                {"loan_count": "sum", "original_balance": "sum",
                 "total_chargeoffs": "sum", "total_recoveries": "sum"}).reset_index()
            b["net_losses"] = b["total_chargeoffs"] - b["total_recoveries"]
            b["loss_rate"] = b["net_losses"] / b["original_balance"]
            display = b[["bucket", "loan_count", "original_balance", "net_losses", "loss_rate"]].copy()
            display.columns = ["Credit Score", "Loans", "Original Balance", "Net Losses", "Loss Rate"]
            display["Original Balance"] = display["Original Balance"].apply(lambda x: f"${x:,.0f}")
            display["Net Losses"] = display["Net Losses"].apply(lambda x: f"${x:,.0f}")
            display["Loss Rate"] = display["Loss Rate"].apply(lambda x: f"{x:.2%}")
            display["Loans"] = display["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(display, use_container_width=True, hide_index=True)

        # --- Losses by Interest Rate ---
        st.subheader("Cumulative Losses by Original Interest Rate")
        loss_by_rate = load_losses_by_segment(selected_deal, "original_interest_rate")
        if not loss_by_rate.empty:
            loss_by_rate["rate"] = pd.to_numeric(loss_by_rate["segment"], errors="coerce")
            loss_by_rate = loss_by_rate.dropna(subset=["rate"])
            rate_bins = [0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 1.0]
            rate_labels = ["<4%", "4-5.99%", "6-7.99%", "8-9.99%", "10-11.99%", "12-14.99%", "15-19.99%", "20%+"]
            loss_by_rate["bucket"] = pd.cut(loss_by_rate["rate"], bins=rate_bins, labels=rate_labels, right=False)
            b = loss_by_rate.groupby("bucket", observed=True).agg(
                {"loan_count": "sum", "original_balance": "sum",
                 "total_chargeoffs": "sum", "total_recoveries": "sum"}).reset_index()
            b["net_losses"] = b["total_chargeoffs"] - b["total_recoveries"]
            b["loss_rate"] = b["net_losses"] / b["original_balance"]
            display = b[["bucket", "loan_count", "original_balance", "net_losses", "loss_rate"]].copy()
            display.columns = ["Interest Rate", "Loans", "Original Balance", "Net Losses", "Loss Rate"]
            display["Original Balance"] = display["Original Balance"].apply(lambda x: f"${x:,.0f}")
            display["Net Losses"] = display["Net Losses"].apply(lambda x: f"${x:,.0f}")
            display["Loss Rate"] = display["Loss Rate"].apply(lambda x: f"{x:.2%}")
            display["Loans"] = display["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(display, use_container_width=True, hide_index=True)

# ============================================================
# TAB 4: CASH WATERFALL
# ============================================================
with tab_waterfall:
    wf = load_waterfall(selected_deal)
    if wf.empty:
        st.info("No performance data available yet.")
    else:
        st.subheader("Cash Waterfall Analysis")
        st.caption("Derived from loan-level data. Servicing fee estimated from per-loan rate.")

        # Monthly collections breakdown
        st.markdown("### Monthly Collections")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=wf["period"], y=wf["interest_collected"],
                             name="Interest Collected", marker_color="#1976D2"))
        fig.add_trace(go.Bar(x=wf["period"], y=wf["principal_collected"],
                             name="Principal Collected", marker_color="#388E3C"))
        fig.add_trace(go.Bar(x=wf["period"], y=wf["recoveries"],
                             name="Recoveries", marker_color="#4CAF50"))
        fig.update_layout(barmode="stack", yaxis_tickformat="$,.0f", hovermode="x unified",
                          title="Monthly Cash Inflows")
        st.plotly_chart(fig, use_container_width=True)

        # Monthly outflows
        st.markdown("### Monthly Cash Outflows")
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=wf["period"], y=wf["est_servicing_fee"],
                              name="Servicing Fee (est.)", marker_color="#FF9800"))
        fig2.add_trace(go.Bar(x=wf["period"], y=wf["chargeoffs"],
                              name="Charge-offs (Losses)", marker_color="#D32F2F"))
        fig2.add_trace(go.Bar(x=wf["period"], y=wf["debt_principal_paid"],
                              name="Debt Principal Paid", marker_color="#7B1FA2"))
        fig2.update_layout(barmode="stack", yaxis_tickformat="$,.0f", hovermode="x unified",
                           title="Monthly Cash Outflows")
        st.plotly_chart(fig2, use_container_width=True)

        # Excess spread over time
        st.markdown("### Excess Spread (Interest Available After Servicing & Losses)")
        fig3 = px.area(wf, x="period", y="excess_spread",
                       labels={"period": "Period", "excess_spread": "Excess Spread ($)"})
        fig3.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        fig3.update_traces(line_color="#388E3C", fillcolor="rgba(56,142,60,0.2)")
        st.plotly_chart(fig3, use_container_width=True)

        # Cumulative waterfall
        st.markdown("### Cumulative Cash Flows")
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=wf["period"], y=wf["cum_interest_collected"],
                                  name="Cumulative Interest", mode="lines"))
        fig4.add_trace(go.Scatter(x=wf["period"], y=wf["cum_principal_collected"],
                                  name="Cumulative Principal", mode="lines"))
        fig4.add_trace(go.Scatter(x=wf["period"], y=wf["cum_servicing_fees"],
                                  name="Cumulative Servicing Fees", mode="lines",
                                  line=dict(dash="dash")))
        fig4.add_trace(go.Scatter(x=wf["period"], y=wf["cum_net_losses"],
                                  name="Cumulative Net Losses", mode="lines",
                                  line=dict(color="#D32F2F")))
        fig4.add_trace(go.Scatter(x=wf["period"], y=wf["cum_excess_spread"],
                                  name="Cumulative Excess Spread (to Residual)",
                                  mode="lines", line=dict(color="#388E3C", width=3)))
        fig4.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified",
                           title="Cumulative Cash Flows")
        st.plotly_chart(fig4, use_container_width=True)

        # Monthly waterfall table (latest period)
        st.markdown("### Latest Period Waterfall")
        latest = wf.iloc[-1]
        waterfall_items = [
            ("Interest Collected", latest["interest_collected"]),
            ("Recoveries", latest["recoveries"]),
            ("**Available Funds**", latest["available_funds"]),
            ("Less: Servicing Fee (est.)", -latest["est_servicing_fee"]),
            ("Less: Net Losses", -latest["net_losses"]),
            ("**Excess Spread**", latest["excess_spread"]),
            ("", None),
            ("Principal Collected", latest["principal_collected"]),
            ("Debt Principal Paid", latest["debt_principal_paid"]),
            ("", None),
            ("**Cumulative Excess Spread (to Residual)**", latest["cum_excess_spread"]),
        ]
        wf_table = pd.DataFrame(
            [(item, f"${val:,.2f}" if val is not None else "") for item, val in waterfall_items],
            columns=["Item", "Amount"]
        )
        st.dataframe(wf_table, use_container_width=True, hide_index=True)

        st.markdown("""
        **Note:** This waterfall is derived from loan-level data. The exact split of interest
        and principal payments across note tranches (A-1 through N) requires the Servicer
        Certificate data, which is filed as images for recent periods. The cumulative excess
        spread approximates cash returned to residual/equity holders.
        """)


# ============================================================
# TAB 5: LOAN EXPLORER
# ============================================================
with tab_loans:
    st.subheader("Loan Portfolio Explorer")
    if loans_df.empty:
        st.info("No loan-level data available yet.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            score_df = loans_df["obligor_credit_score"].dropna()
            if not score_df.empty:
                fig = px.histogram(score_df, nbins=30, title="Credit Score Distribution",
                                   labels={"value": "Credit Score", "count": "Loans"},
                                   color_discrete_sequence=["#1976D2"])
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        with col2:
            amt_df = loans_df["original_loan_amount"].dropna()
            if not amt_df.empty:
                fig = px.histogram(amt_df, nbins=30, title="Original Loan Amount Distribution",
                                   labels={"value": "Loan Amount ($)", "count": "Loans"},
                                   color_discrete_sequence=["#388E3C"])
                fig.update_layout(xaxis_tickformat="$,.0f", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)
        with col3:
            mfr_df = loans_df["vehicle_manufacturer"].dropna().value_counts().head(15)
            if not mfr_df.empty:
                fig = px.bar(x=mfr_df.values, y=mfr_df.index, orientation="h",
                             title="Top 15 Vehicle Manufacturers",
                             labels={"x": "Loans", "y": "Manufacturer"},
                             color_discrete_sequence=["#FF9800"])
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
        with col4:
            state_df = loans_df["obligor_geographic_location"].dropna().value_counts().head(15)
            if not state_df.empty:
                fig = px.bar(x=state_df.values, y=state_df.index, orientation="h",
                             title="Top 15 States by Loan Count",
                             labels={"x": "Loans", "y": "State"},
                             color_discrete_sequence=["#7B1FA2"])
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        if "original_interest_rate_pct" in loans_df.columns:
            rate_score = loans_df[["original_interest_rate_pct", "obligor_credit_score"]].dropna()
            if len(rate_score) > 0:
                st.subheader("Interest Rate vs Credit Score")
                sample = rate_score.sample(min(5000, len(rate_score)), random_state=42)
                fig = px.scatter(sample, x="obligor_credit_score", y="original_interest_rate_pct",
                                 title="Original Interest Rate vs Credit Score",
                                 labels={"obligor_credit_score": "Credit Score",
                                         "original_interest_rate_pct": "Interest Rate (%)"},
                                 opacity=0.3)
                fig.update_layout(yaxis_ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Portfolio Summary Statistics")
        stat_data = {}
        if "original_loan_amount" in loans_df.columns:
            stat_data["Loan Amount ($)"] = loans_df["original_loan_amount"].describe()
        if "original_interest_rate_pct" in loans_df.columns:
            stat_data["Interest Rate (%)"] = loans_df["original_interest_rate_pct"].describe()
        if "original_loan_term" in loans_df.columns:
            stat_data["Loan Term (months)"] = loans_df["original_loan_term"].describe()
        if "obligor_credit_score" in loans_df.columns:
            stat_data["Credit Score"] = loans_df["obligor_credit_score"].describe()
        if "original_ltv" in loans_df.columns:
            stat_data["LTV (%)"] = (loans_df["original_ltv"] * 100).describe()
        if stat_data:
            st.dataframe(pd.DataFrame(stat_data).style.format("{:.2f}"), use_container_width=True)

# ============================================================
# TAB 6: DATA FIELDS
# ============================================================
with tab_fields:
    st.subheader("Available Data Fields")
    st.markdown("These are the fields from SEC EDGAR ABS-EE filings (73 XML elements per loan).")
    st.markdown("### Loan Static Data (one per loan)")
    loan_fields = {
        "asset_number": "Unique loan identifier",
        "originator_name": "Entity that originated the loan",
        "origination_date": "Month/year originated",
        "original_loan_amount": "Loan amount at origination ($)",
        "original_loan_term": "Term in months at origination",
        "original_interest_rate": "Rate at origination (decimal: 0.0599 = 5.99%)",
        "loan_maturity_date": "Scheduled final payment date",
        "original_ltv": "Loan-to-value ratio",
        "vehicle_manufacturer": "Vehicle make",
        "vehicle_model": "Vehicle model",
        "vehicle_new_used": "1=New, 2=Used",
        "vehicle_model_year": "Vehicle model year",
        "vehicle_type": "Vehicle type code",
        "vehicle_value": "Vehicle value at origination ($)",
        "obligor_credit_score": "Borrower credit score at origination",
        "obligor_credit_score_type": "Credit score model",
        "obligor_geographic_location": "Borrower state",
        "co_obligor_indicator": "Co-borrower (true/false)",
        "payment_to_income_ratio": "Monthly payment / income (decimal)",
        "income_verification_level": "How income was verified (1-4)",
        "payment_type": "Payment type code",
        "subvention_indicator": "Rate subsidized (0/1)",
    }
    st.dataframe(pd.DataFrame(loan_fields.items(), columns=["Field", "Description"]),
                 use_container_width=True, hide_index=True)

    st.markdown("### Monthly Performance Data (one per loan per month)")
    perf_fields = {
        "reporting_period_end": "Period end date",
        "beginning_balance": "Balance at start of period ($)",
        "ending_balance": "Balance at end of period ($)",
        "scheduled_payment": "Scheduled payment ($)",
        "actual_amount_paid": "Actual total paid ($)",
        "actual_interest_collected": "Interest collected ($)",
        "actual_principal_collected": "Principal collected ($)",
        "current_interest_rate": "Current rate (decimal)",
        "current_delinquency_status": "Months delinquent (0=current, 1=30d, 2=60d, 3=90d, 4+=120d+)",
        "remaining_term": "Months remaining",
        "paid_through_date": "Date interest paid through",
        "zero_balance_code": "Why zeroed (1=prepaid, 2=matured, 3=charged off, etc.)",
        "zero_balance_date": "When balance went to zero",
        "charged_off_amount": "Amount charged off ($)",
        "recoveries": "Amount recovered ($)",
        "modification_indicator": "Modified (true/false)",
        "servicing_fee": "Servicing fee",
    }
    st.dataframe(pd.DataFrame(perf_fields.items(), columns=["Field", "Description"]),
                 use_container_width=True, hide_index=True)
