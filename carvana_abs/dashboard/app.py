"""Streamlit dashboard for Carvana Auto Receivables Trust 2020-P1."""

import os
import sys
import sqlite3

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH

# --- Page Config ---
st.set_page_config(
    page_title="Carvana 2020-P1 ABS Dashboard",
    page_icon="\U0001F4CA",
    layout="wide",
)

# --- Database Connection ---
@st.cache_resource
def get_db_connection():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=300)
def load_pool_performance():
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query(
        "SELECT * FROM pool_performance ORDER BY distribution_date", conn
    )


@st.cache_data(ttl=300)
def load_loan_summary():
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT
            obligor_credit_score,
            obligor_geographic_location,
            original_loan_amount,
            original_loan_term,
            original_interest_rate,
            vehicle_manufacturer,
            vehicle_new_used,
            vehicle_model_year,
            original_ltv
        FROM loans
    """, conn)


@st.cache_data(ttl=300)
def load_loan_performance_agg():
    """Load aggregated loan performance by period."""
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT
            reporting_period_end,
            COUNT(*) as active_loans,
            SUM(ending_balance) as total_balance,
            SUM(CASE WHEN current_delinquency_status IS NOT NULL
                AND current_delinquency_status != '0'
                AND current_delinquency_status != ''
                THEN ending_balance ELSE 0 END) as delinquent_balance,
            SUM(CASE WHEN zero_balance_code IS NOT NULL THEN 1 ELSE 0 END) as zero_balance_count,
            SUM(COALESCE(charged_off_amount, 0)) as period_chargeoffs,
            SUM(COALESCE(recoveries, 0)) as period_recoveries,
            AVG(ending_balance) as avg_balance,
            COUNT(CASE WHEN days_delinquent >= 30 AND days_delinquent < 60 THEN 1 END) as dq_30_59,
            COUNT(CASE WHEN days_delinquent >= 60 AND days_delinquent < 90 THEN 1 END) as dq_60_89,
            COUNT(CASE WHEN days_delinquent >= 90 AND days_delinquent < 120 THEN 1 END) as dq_90_119,
            COUNT(CASE WHEN days_delinquent >= 120 THEN 1 END) as dq_120_plus
        FROM loan_performance
        GROUP BY reporting_period_end
        ORDER BY reporting_period_end
    """, conn)


@st.cache_data(ttl=300)
def load_filing_summary():
    conn = get_db_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql_query("""
        SELECT filing_type, COUNT(*) as count,
               SUM(ingested_pool) as pool_ingested,
               SUM(ingested_loans) as loans_ingested
        FROM filings
        GROUP BY filing_type
    """, conn)


# --- Header ---
st.title("Carvana Auto Receivables Trust 2020-P1")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")

conn = get_db_connection()
if conn is None:
    st.error(
        f"Database not found at `{DB_PATH}`. "
        "Run the ingestion script first:\n\n"
        "```bash\n"
        "export SEC_USER_AGENT='YourName your-email@example.com'\n"
        "cd carvana_abs && python run_ingestion.py\n"
        "```"
    )
    st.stop()

# --- Sidebar: Data Summary ---
with st.sidebar:
    st.header("Data Summary")

    filing_summary = load_filing_summary()
    if not filing_summary.empty:
        for _, row in filing_summary.iterrows():
            st.metric(f"{row['filing_type']} Filings", int(row['count']))

    pool_df = load_pool_performance()
    loans_df = load_loan_summary()
    loan_perf_df = load_loan_performance_agg()

    if not pool_df.empty:
        st.metric("Pool Data Points", len(pool_df))
    if not loans_df.empty:
        st.metric("Unique Loans", len(loans_df))
    if not loan_perf_df.empty:
        st.metric("Performance Periods", len(loan_perf_df))

    st.markdown("---")
    st.caption("Data sourced from SEC EDGAR 10-D filings")

# --- Tabs ---
tab_pool, tab_dq, tab_losses, tab_loans = st.tabs([
    "Pool Summary", "Delinquencies", "Losses", "Loan Explorer"
])

# ============================================================
# TAB 1: POOL SUMMARY
# ============================================================
with tab_pool:
    if pool_df.empty and loan_perf_df.empty:
        st.info("No pool or loan performance data available yet. Run the ingestion script.")
    else:
        st.subheader("Pool Balance Over Time")

        # Use whichever data source is available
        if not pool_df.empty:
            chart_df = pool_df[["distribution_date", "ending_pool_balance"]].dropna()
            if not chart_df.empty:
                fig = px.area(
                    chart_df, x="distribution_date", y="ending_pool_balance",
                    title="Remaining Pool Balance",
                    labels={"distribution_date": "Distribution Date",
                            "ending_pool_balance": "Balance ($)"},
                )
                fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)

                # Pool factor
                if pool_df["beginning_pool_balance"].iloc[0]:
                    original = pool_df["beginning_pool_balance"].iloc[0]
                    current = pool_df["ending_pool_balance"].iloc[-1] if pd.notna(pool_df["ending_pool_balance"].iloc[-1]) else 0
                    pool_factor = current / original if original else 0

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Original Pool Balance", f"${original:,.0f}")
                    col2.metric("Current Pool Balance", f"${current:,.0f}")
                    col3.metric("Pool Factor", f"{pool_factor:.2%}")

        elif not loan_perf_df.empty:
            fig = px.area(
                loan_perf_df, x="reporting_period_end", y="total_balance",
                title="Remaining Pool Balance (from loan-level data)",
                labels={"reporting_period_end": "Period End",
                        "total_balance": "Balance ($)"},
            )
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

        # Loan count over time
        if not pool_df.empty and "ending_pool_count" in pool_df.columns:
            count_df = pool_df[["distribution_date", "ending_pool_count"]].dropna()
            if not count_df.empty:
                fig2 = px.line(
                    count_df, x="distribution_date", y="ending_pool_count",
                    title="Active Loan Count",
                    labels={"distribution_date": "Distribution Date",
                            "ending_pool_count": "Loan Count"},
                )
                fig2.update_layout(hovermode="x unified")
                st.plotly_chart(fig2, use_container_width=True)
        elif not loan_perf_df.empty:
            fig2 = px.line(
                loan_perf_df, x="reporting_period_end", y="active_loans",
                title="Active Loan Count (from loan-level data)",
                labels={"reporting_period_end": "Period End",
                        "active_loans": "Loan Count"},
            )
            fig2.update_layout(hovermode="x unified")
            st.plotly_chart(fig2, use_container_width=True)

        # Note balances
        if not pool_df.empty:
            note_cols = [c for c in pool_df.columns if c.startswith("note_balance_")]
            note_df = pool_df[["distribution_date"] + note_cols].dropna(how="all", subset=note_cols)
            if not note_df.empty:
                st.subheader("Note Balances by Class")
                note_melted = note_df.melt(
                    id_vars=["distribution_date"],
                    value_vars=note_cols,
                    var_name="Note Class",
                    value_name="Balance"
                )
                note_melted["Note Class"] = note_melted["Note Class"].str.replace("note_balance_", "Class ").str.upper()
                fig3 = px.area(
                    note_melted, x="distribution_date", y="Balance",
                    color="Note Class",
                    title="Note Balances Over Time",
                    labels={"distribution_date": "Distribution Date"},
                )
                fig3.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
                st.plotly_chart(fig3, use_container_width=True)


# ============================================================
# TAB 2: DELINQUENCIES
# ============================================================
with tab_dq:
    st.subheader("Delinquency Analysis")

    has_pool_dq = (not pool_df.empty and
                   any(col in pool_df.columns for col in
                       ["delinquent_31_60_balance", "delinquent_61_90_balance"]))
    has_loan_dq = not loan_perf_df.empty and "dq_30_59" in loan_perf_df.columns

    if has_pool_dq:
        dq_cols = ["delinquent_31_60_balance", "delinquent_61_90_balance",
                    "delinquent_91_120_balance", "delinquent_121_plus_balance"]
        available_dq_cols = [c for c in dq_cols if c in pool_df.columns]
        dq_df = pool_df[["distribution_date"] + available_dq_cols].copy()
        dq_df = dq_df.dropna(how="all", subset=available_dq_cols)

        if not dq_df.empty:
            # Stacked area chart
            dq_melted = dq_df.melt(
                id_vars=["distribution_date"],
                value_vars=available_dq_cols,
                var_name="Bucket",
                value_name="Balance"
            )
            label_map = {
                "delinquent_31_60_balance": "31-60 Days",
                "delinquent_61_90_balance": "61-90 Days",
                "delinquent_91_120_balance": "91-120 Days",
                "delinquent_121_plus_balance": "121+ Days",
            }
            dq_melted["Bucket"] = dq_melted["Bucket"].map(label_map)

            fig = px.area(
                dq_melted, x="distribution_date", y="Balance",
                color="Bucket",
                title="Delinquent Balance by Bucket",
                labels={"distribution_date": "Distribution Date"},
                color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"],
            )
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

            # Delinquency rate
            if "ending_pool_balance" in pool_df.columns and "total_delinquent_balance" in pool_df.columns:
                rate_df = pool_df[["distribution_date", "total_delinquent_balance", "ending_pool_balance"]].copy()
                rate_df = rate_df.dropna()
                rate_df["delinquency_rate"] = rate_df["total_delinquent_balance"] / rate_df["ending_pool_balance"]

                fig2 = px.line(
                    rate_df, x="distribution_date", y="delinquency_rate",
                    title="Total Delinquency Rate (% of Pool Balance)",
                    labels={"distribution_date": "Distribution Date",
                            "delinquency_rate": "Delinquency Rate"},
                )
                fig2.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                st.plotly_chart(fig2, use_container_width=True)

    elif has_loan_dq:
        st.markdown("*Delinquency data derived from loan-level performance records*")
        dq_count_df = loan_perf_df[["reporting_period_end", "dq_30_59", "dq_60_89", "dq_90_119", "dq_120_plus"]].copy()
        dq_melted = dq_count_df.melt(
            id_vars=["reporting_period_end"],
            var_name="Bucket",
            value_name="Count"
        )
        label_map = {
            "dq_30_59": "30-59 Days",
            "dq_60_89": "60-89 Days",
            "dq_90_119": "90-119 Days",
            "dq_120_plus": "120+ Days",
        }
        dq_melted["Bucket"] = dq_melted["Bucket"].map(label_map)

        fig = px.area(
            dq_melted, x="reporting_period_end", y="Count",
            color="Bucket",
            title="Delinquent Loan Count by Bucket",
            labels={"reporting_period_end": "Period End"},
            color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"],
        )
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No delinquency data available yet.")


# ============================================================
# TAB 3: LOSSES
# ============================================================
with tab_losses:
    st.subheader("Loss Analysis")

    has_pool_losses = not pool_df.empty and "cumulative_net_losses" in pool_df.columns
    has_loan_losses = not loan_perf_df.empty and "period_chargeoffs" in loan_perf_df.columns

    if has_pool_losses:
        loss_df = pool_df[["distribution_date", "cumulative_net_losses", "charged_off_amount",
                            "recoveries", "ending_pool_balance", "beginning_pool_balance"]].copy()

        # Cumulative net losses
        cum_loss_df = loss_df[["distribution_date", "cumulative_net_losses"]].dropna()
        if not cum_loss_df.empty:
            fig = px.area(
                cum_loss_df, x="distribution_date", y="cumulative_net_losses",
                title="Cumulative Net Losses",
                labels={"distribution_date": "Distribution Date",
                        "cumulative_net_losses": "Cumulative Losses ($)"},
            )
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.3)")
            st.plotly_chart(fig, use_container_width=True)

        # Monthly charge-offs and recoveries
        monthly_df = loss_df[["distribution_date", "charged_off_amount", "recoveries"]].dropna()
        if not monthly_df.empty:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=monthly_df["distribution_date"],
                y=monthly_df["charged_off_amount"],
                name="Charge-offs",
                marker_color="#D32F2F",
            ))
            fig2.add_trace(go.Bar(
                x=monthly_df["distribution_date"],
                y=monthly_df["recoveries"],
                name="Recoveries",
                marker_color="#4CAF50",
            ))
            fig2.update_layout(
                title="Monthly Charge-offs vs Recoveries",
                barmode="group",
                yaxis_tickformat="$,.0f",
                hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Cumulative loss rate
        if not cum_loss_df.empty and pool_df["beginning_pool_balance"].iloc[0]:
            original_balance = pool_df["beginning_pool_balance"].iloc[0]
            rate_df = cum_loss_df.copy()
            rate_df["loss_rate"] = rate_df["cumulative_net_losses"] / original_balance

            fig3 = px.line(
                rate_df, x="distribution_date", y="loss_rate",
                title="Cumulative Loss Rate (% of Original Balance)",
                labels={"distribution_date": "Distribution Date",
                        "loss_rate": "Cumulative Loss Rate"},
            )
            fig3.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
            fig3.update_traces(line_color="#D32F2F")
            st.plotly_chart(fig3, use_container_width=True)

    elif has_loan_losses:
        st.markdown("*Loss data derived from loan-level performance records*")
        loss_df = loan_perf_df[["reporting_period_end", "period_chargeoffs", "period_recoveries"]].copy()
        loss_df["cumulative_chargeoffs"] = loss_df["period_chargeoffs"].cumsum()
        loss_df["cumulative_recoveries"] = loss_df["period_recoveries"].cumsum()
        loss_df["cumulative_net_losses"] = loss_df["cumulative_chargeoffs"] - loss_df["cumulative_recoveries"]

        fig = px.area(
            loss_df, x="reporting_period_end", y="cumulative_net_losses",
            title="Cumulative Net Losses (from loan-level data)",
            labels={"reporting_period_end": "Period End",
                    "cumulative_net_losses": "Cumulative Losses ($)"},
        )
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.3)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No loss data available yet.")


# ============================================================
# TAB 4: LOAN EXPLORER
# ============================================================
with tab_loans:
    st.subheader("Loan Portfolio Explorer")

    if loans_df.empty:
        st.info("No loan-level data available yet. Run ingestion with ABS-EE XML parsing.")
    else:
        col1, col2 = st.columns(2)

        # Credit Score Distribution
        with col1:
            score_df = loans_df["obligor_credit_score"].dropna()
            if not score_df.empty:
                fig = px.histogram(
                    score_df, nbins=30,
                    title="Credit Score Distribution",
                    labels={"value": "Credit Score", "count": "Number of Loans"},
                    color_discrete_sequence=["#1976D2"],
                )
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        # Original Loan Amount Distribution
        with col2:
            amt_df = loans_df["original_loan_amount"].dropna()
            if not amt_df.empty:
                fig = px.histogram(
                    amt_df, nbins=30,
                    title="Original Loan Amount Distribution",
                    labels={"value": "Loan Amount ($)", "count": "Number of Loans"},
                    color_discrete_sequence=["#388E3C"],
                )
                fig.update_layout(xaxis_tickformat="$,.0f", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)

        # Top Vehicle Manufacturers
        with col3:
            mfr_df = loans_df["vehicle_manufacturer"].dropna().value_counts().head(15)
            if not mfr_df.empty:
                fig = px.bar(
                    x=mfr_df.values, y=mfr_df.index,
                    orientation="h",
                    title="Top 15 Vehicle Manufacturers",
                    labels={"x": "Number of Loans", "y": "Manufacturer"},
                    color_discrete_sequence=["#FF9800"],
                )
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        # Geographic Distribution
        with col4:
            state_df = loans_df["obligor_geographic_location"].dropna().value_counts().head(15)
            if not state_df.empty:
                fig = px.bar(
                    x=state_df.values, y=state_df.index,
                    orientation="h",
                    title="Top 15 States by Loan Count",
                    labels={"x": "Number of Loans", "y": "State"},
                    color_discrete_sequence=["#7B1FA2"],
                )
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        # Interest Rate vs Credit Score scatter
        rate_score_df = loans_df[["original_interest_rate", "obligor_credit_score"]].dropna()
        if len(rate_score_df) > 0:
            st.subheader("Interest Rate vs Credit Score")
            # Sample if too many points
            if len(rate_score_df) > 5000:
                rate_score_df = rate_score_df.sample(5000, random_state=42)
            fig = px.scatter(
                rate_score_df,
                x="obligor_credit_score", y="original_interest_rate",
                title="Original Interest Rate vs Credit Score",
                labels={"obligor_credit_score": "Credit Score",
                        "original_interest_rate": "Interest Rate (%)"},
                opacity=0.3,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Summary statistics
        st.subheader("Portfolio Summary Statistics")
        summary_stats = loans_df[["original_loan_amount", "original_interest_rate",
                                   "original_loan_term", "obligor_credit_score",
                                   "original_ltv"]].describe()
        st.dataframe(summary_stats.style.format("{:.2f}"), use_container_width=True)
