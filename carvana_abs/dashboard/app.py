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

# --- Page Config ---
st.set_page_config(
    page_title="Carvana ABS Dashboard",
    page_icon="\U0001F4CA",
    layout="wide",
)


# --- Database ---
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


# --- Header ---
st.title("Carvana Auto Receivables Trust")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")

conn = get_db()
if conn is None:
    st.error(
        f"Database not found at `{DB_PATH}`. "
        "Run the ingestion script first."
    )
    st.stop()

# --- Sidebar ---
available_deals = query_df("SELECT DISTINCT deal FROM filings ORDER BY deal")
deal_list = available_deals["deal"].tolist() if not available_deals.empty else list(DEALS.keys())

with st.sidebar:
    st.header("Deal Selection")
    selected_deal = st.selectbox("Deal", deal_list, index=0)
    deal_cfg = DEALS.get(selected_deal, {})
    if deal_cfg:
        st.caption(deal_cfg.get("entity_name", ""))

    st.markdown("---")
    st.header("Data Summary")
    loan_count = query_df("SELECT COUNT(*) as n FROM loans WHERE deal = ?", (selected_deal,))
    perf_periods = query_df("SELECT COUNT(DISTINCT reporting_period_end) as n FROM loan_performance WHERE deal = ?", (selected_deal,))
    if not loan_count.empty:
        st.metric("Unique Loans", f"{int(loan_count.iloc[0]['n']):,}")
    if not perf_periods.empty:
        st.metric("Monthly Periods", int(perf_periods.iloc[0]["n"]))

    st.markdown("---")
    st.caption("Data sourced from SEC EDGAR ABS-EE filings")

# --- Get original pool balance ---
ORIGINAL_BALANCE = deal_cfg.get("original_pool_balance", 405_000_000)

# --- Data Loading ---
# The key fix: exclude zero-balance loans from pool totals, and use
# currentDelinquencyStatus correctly (it's months delinquent as integer: 0,1,2,3...)
# Interest rates are stored as decimals (0.10986 = 10.986%)

@st.cache_data(ttl=300)
def load_loan_perf_agg(deal: str) -> pd.DataFrame:
    return query_df("""
        SELECT
            reporting_period_end,
            -- Only count loans with positive balance as "active"
            COUNT(CASE WHEN ending_balance > 0 THEN 1 END) as active_loans,
            -- Sum only positive balances (exclude paid-off/charged-off)
            SUM(CASE WHEN ending_balance > 0 THEN ending_balance ELSE 0 END) as total_balance,
            -- Delinquency: currentDelinquencyStatus is months delinquent (0=current, 1=30d, 2=60d, etc.)
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 1 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_30_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 2 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_60_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 3 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_90_balance,
            SUM(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 4 AND ending_balance > 0
                THEN ending_balance ELSE 0 END) as dq_120_plus_balance,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 1 AND ending_balance > 0 THEN 1 END) as dq_30_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 2 AND ending_balance > 0 THEN 1 END) as dq_60_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) = 3 AND ending_balance > 0 THEN 1 END) as dq_90_count,
            COUNT(CASE WHEN CAST(current_delinquency_status AS INTEGER) >= 4 AND ending_balance > 0 THEN 1 END) as dq_120_plus_count,
            -- Losses
            SUM(COALESCE(charged_off_amount, 0)) as period_chargeoffs,
            SUM(COALESCE(recoveries, 0)) as period_recoveries
        FROM loan_performance WHERE deal = ?
        GROUP BY reporting_period_end
        ORDER BY reporting_period_end
    """, (deal,))


@st.cache_data(ttl=300)
def load_loans(deal: str) -> pd.DataFrame:
    df = query_df("SELECT * FROM loans WHERE deal = ?", (deal,))
    if not df.empty:
        # Convert interest rate from decimal to percentage for display
        if "original_interest_rate" in df.columns:
            df["original_interest_rate_pct"] = df["original_interest_rate"] * 100
    return df


@st.cache_data(ttl=300)
def load_losses_by_segment(deal: str, segment_col: str, segment_label: str) -> pd.DataFrame:
    """Load cumulative losses grouped by a loan attribute."""
    return query_df(f"""
        SELECT
            l.{segment_col} as segment,
            SUM(l.original_loan_amount) as original_balance,
            COUNT(DISTINCT l.asset_number) as loan_count,
            SUM(COALESCE(lp.charged_off_amount, 0)) as total_chargeoffs,
            SUM(COALESCE(lp.recoveries, 0)) as total_recoveries
        FROM loans l
        JOIN loan_performance lp ON l.deal = lp.deal AND l.asset_number = lp.asset_number
        WHERE l.deal = ?
        AND l.{segment_col} IS NOT NULL
        GROUP BY l.{segment_col}
        ORDER BY l.{segment_col}
    """, (deal,))


loans_df = load_loans(selected_deal)
loan_perf_df = load_loan_perf_agg(selected_deal)

# Compute cumulative losses
if not loan_perf_df.empty:
    loan_perf_df["cumulative_chargeoffs"] = loan_perf_df["period_chargeoffs"].cumsum()
    loan_perf_df["cumulative_recoveries"] = loan_perf_df["period_recoveries"].cumsum()
    loan_perf_df["cumulative_net_losses"] = loan_perf_df["cumulative_chargeoffs"] - loan_perf_df["cumulative_recoveries"]
    loan_perf_df["cumulative_loss_rate"] = loan_perf_df["cumulative_net_losses"] / ORIGINAL_BALANCE
    loan_perf_df["total_dq_balance"] = (
        loan_perf_df["dq_30_balance"] + loan_perf_df["dq_60_balance"] +
        loan_perf_df["dq_90_balance"] + loan_perf_df["dq_120_plus_balance"]
    )
    loan_perf_df["dq_rate"] = loan_perf_df["total_dq_balance"] / loan_perf_df["total_balance"]


# --- Tabs ---
tab_pool, tab_dq, tab_losses, tab_loans, tab_fields = st.tabs([
    "Pool Summary", "Delinquencies", "Losses", "Loan Explorer", "Data Fields"
])


# ============================================================
# TAB 1: POOL SUMMARY
# ============================================================
with tab_pool:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        # Key metrics
        first_period = loan_perf_df.iloc[0]
        last_period = loan_perf_df.iloc[-1]
        current_balance = last_period["total_balance"]
        pool_factor = current_balance / ORIGINAL_BALANCE if ORIGINAL_BALANCE else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Original Pool Balance", f"${ORIGINAL_BALANCE:,.0f}")
        col2.metric("Current Pool Balance", f"${current_balance:,.0f}")
        col3.metric("Pool Factor", f"{pool_factor:.2%}")
        col4.metric("Active Loans", f"{int(last_period['active_loans']):,}")

        st.subheader("Remaining Pool Balance")
        fig = px.area(
            loan_perf_df, x="reporting_period_end", y="total_balance",
            labels={"reporting_period_end": "Reporting Period", "total_balance": "Balance ($)"},
        )
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Loan count over time
        st.subheader("Active Loan Count")
        fig2 = px.line(
            loan_perf_df, x="reporting_period_end", y="active_loans",
            labels={"reporting_period_end": "Reporting Period", "active_loans": "Active Loans"},
        )
        fig2.update_layout(hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)


# ============================================================
# TAB 2: DELINQUENCIES
# ============================================================
with tab_dq:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        st.subheader("Delinquency Analysis")

        # Stacked area by bucket (balance)
        dq_cols = {
            "dq_30_balance": "30 Days",
            "dq_60_balance": "60 Days",
            "dq_90_balance": "90 Days",
            "dq_120_plus_balance": "120+ Days",
        }
        dq_melted = loan_perf_df[["reporting_period_end"] + list(dq_cols.keys())].melt(
            id_vars=["reporting_period_end"], var_name="Bucket", value_name="Balance"
        )
        dq_melted["Bucket"] = dq_melted["Bucket"].map(dq_cols)

        fig = px.area(
            dq_melted, x="reporting_period_end", y="Balance", color="Bucket",
            title="Delinquent Balance by Bucket",
            labels={"reporting_period_end": "Reporting Period"},
            color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"],
        )
        fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Delinquency rate
        fig2 = px.line(
            loan_perf_df, x="reporting_period_end", y="dq_rate",
            title="Total Delinquency Rate (% of Active Pool Balance)",
            labels={"reporting_period_end": "Reporting Period", "dq_rate": "Delinquency Rate"},
        )
        fig2.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)

        # Delinquency count table
        st.subheader("Delinquent Loan Counts (Latest Period)")
        latest = loan_perf_df.iloc[-1]
        dq_summary = pd.DataFrame({
            "Bucket": ["30 Days", "60 Days", "90 Days", "120+ Days", "Total"],
            "Count": [int(latest["dq_30_count"]), int(latest["dq_60_count"]),
                      int(latest["dq_90_count"]), int(latest["dq_120_plus_count"]),
                      int(latest["dq_30_count"] + latest["dq_60_count"] + latest["dq_90_count"] + latest["dq_120_plus_count"])],
            "Balance": [latest["dq_30_balance"], latest["dq_60_balance"],
                        latest["dq_90_balance"], latest["dq_120_plus_balance"],
                        latest["total_dq_balance"]],
        })
        dq_summary["Balance"] = dq_summary["Balance"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(dq_summary, use_container_width=True, hide_index=True)


# ============================================================
# TAB 3: LOSSES
# ============================================================
with tab_losses:
    if loan_perf_df.empty:
        st.info("No performance data available yet.")
    else:
        st.subheader("Loss Analysis")

        # Key loss metrics
        latest = loan_perf_df.iloc[-1]
        col1, col2, col3 = st.columns(3)
        col1.metric("Cumulative Net Losses", f"${latest['cumulative_net_losses']:,.0f}")
        col2.metric("Cumulative Loss Rate", f"{latest['cumulative_loss_rate']:.2%}")
        col3.metric("Through Period", latest["reporting_period_end"])

        # Cumulative loss rate chart (as % of original balance)
        fig = px.area(
            loan_perf_df, x="reporting_period_end", y="cumulative_loss_rate",
            title=f"Cumulative Net Loss Rate (% of ${ORIGINAL_BALANCE/1e6:.0f}M Original Balance)",
            labels={"reporting_period_end": "Reporting Period",
                    "cumulative_loss_rate": "Cumulative Loss Rate"},
        )
        fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
        st.plotly_chart(fig, use_container_width=True)

        # Monthly charge-offs vs recoveries
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=loan_perf_df["reporting_period_end"], y=loan_perf_df["period_chargeoffs"],
            name="Charge-offs", marker_color="#D32F2F",
        ))
        fig2.add_trace(go.Bar(
            x=loan_perf_df["reporting_period_end"], y=loan_perf_df["period_recoveries"],
            name="Recoveries", marker_color="#4CAF50",
        ))
        fig2.update_layout(
            title="Monthly Charge-offs vs Recoveries",
            barmode="group", yaxis_tickformat="$,.0f", hovermode="x unified",
        )
        st.plotly_chart(fig2, use_container_width=True)

        # --- Losses by Credit Score ---
        st.subheader("Cumulative Losses by Credit Score")
        loss_by_score = load_losses_by_segment(selected_deal, "obligor_credit_score", "Credit Score")
        if not loss_by_score.empty:
            # Bucket credit scores
            loss_by_score["score"] = pd.to_numeric(loss_by_score["segment"], errors="coerce")
            loss_by_score = loss_by_score.dropna(subset=["score"])
            bins = [0, 580, 620, 660, 700, 740, 780, 820, 900]
            labels = ["<580", "580-619", "620-659", "660-699", "700-739", "740-779", "780-819", "820+"]
            loss_by_score["Score Bucket"] = pd.cut(loss_by_score["score"], bins=bins, labels=labels, right=False)
            bucketed = loss_by_score.groupby("Score Bucket", observed=True).agg({
                "loan_count": "sum",
                "original_balance": "sum",
                "total_chargeoffs": "sum",
                "total_recoveries": "sum",
            }).reset_index()
            bucketed["net_losses"] = bucketed["total_chargeoffs"] - bucketed["total_recoveries"]
            bucketed["loss_rate"] = bucketed["net_losses"] / bucketed["original_balance"]

            display_score = bucketed[["Score Bucket", "loan_count", "original_balance", "net_losses", "loss_rate"]].copy()
            display_score.columns = ["Credit Score", "Loans", "Original Balance", "Net Losses", "Loss Rate"]
            display_score["Original Balance"] = display_score["Original Balance"].apply(lambda x: f"${x:,.0f}")
            display_score["Net Losses"] = display_score["Net Losses"].apply(lambda x: f"${x:,.0f}")
            display_score["Loss Rate"] = display_score["Loss Rate"].apply(lambda x: f"{x:.2%}")
            display_score["Loans"] = display_score["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(display_score, use_container_width=True, hide_index=True)

        # --- Losses by Interest Rate ---
        st.subheader("Cumulative Losses by Original Interest Rate")
        loss_by_rate = load_losses_by_segment(selected_deal, "original_interest_rate", "Interest Rate")
        if not loss_by_rate.empty:
            loss_by_rate["rate"] = pd.to_numeric(loss_by_rate["segment"], errors="coerce")
            loss_by_rate = loss_by_rate.dropna(subset=["rate"])
            # Rates are stored as decimals (0.05 = 5%)
            rate_bins = [0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 1.0]
            rate_labels = ["<4%", "4-5.99%", "6-7.99%", "8-9.99%", "10-11.99%", "12-14.99%", "15-19.99%", "20%+"]
            loss_by_rate["Rate Bucket"] = pd.cut(loss_by_rate["rate"], bins=rate_bins, labels=rate_labels, right=False)
            bucketed_rate = loss_by_rate.groupby("Rate Bucket", observed=True).agg({
                "loan_count": "sum",
                "original_balance": "sum",
                "total_chargeoffs": "sum",
                "total_recoveries": "sum",
            }).reset_index()
            bucketed_rate["net_losses"] = bucketed_rate["total_chargeoffs"] - bucketed_rate["total_recoveries"]
            bucketed_rate["loss_rate"] = bucketed_rate["net_losses"] / bucketed_rate["original_balance"]

            display_rate = bucketed_rate[["Rate Bucket", "loan_count", "original_balance", "net_losses", "loss_rate"]].copy()
            display_rate.columns = ["Interest Rate", "Loans", "Original Balance", "Net Losses", "Loss Rate"]
            display_rate["Original Balance"] = display_rate["Original Balance"].apply(lambda x: f"${x:,.0f}")
            display_rate["Net Losses"] = display_rate["Net Losses"].apply(lambda x: f"${x:,.0f}")
            display_rate["Loss Rate"] = display_rate["Loss Rate"].apply(lambda x: f"{x:.2%}")
            display_rate["Loans"] = display_rate["Loans"].apply(lambda x: f"{x:,}")
            st.dataframe(display_rate, use_container_width=True, hide_index=True)


# ============================================================
# TAB 4: LOAN EXPLORER
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
                fig = px.histogram(
                    score_df, nbins=30, title="Credit Score Distribution",
                    labels={"value": "Credit Score", "count": "Loans"},
                    color_discrete_sequence=["#1976D2"],
                )
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            amt_df = loans_df["original_loan_amount"].dropna()
            if not amt_df.empty:
                fig = px.histogram(
                    amt_df, nbins=30, title="Original Loan Amount Distribution",
                    labels={"value": "Loan Amount ($)", "count": "Loans"},
                    color_discrete_sequence=["#388E3C"],
                )
                fig.update_layout(xaxis_tickformat="$,.0f", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)

        with col3:
            mfr_df = loans_df["vehicle_manufacturer"].dropna().value_counts().head(15)
            if not mfr_df.empty:
                fig = px.bar(
                    x=mfr_df.values, y=mfr_df.index, orientation="h",
                    title="Top 15 Vehicle Manufacturers",
                    labels={"x": "Loans", "y": "Manufacturer"},
                    color_discrete_sequence=["#FF9800"],
                )
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        with col4:
            state_df = loans_df["obligor_geographic_location"].dropna().value_counts().head(15)
            if not state_df.empty:
                fig = px.bar(
                    x=state_df.values, y=state_df.index, orientation="h",
                    title="Top 15 States by Loan Count",
                    labels={"x": "Loans", "y": "State"},
                    color_discrete_sequence=["#7B1FA2"],
                )
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

        # Rate vs Score scatter — RATES AS PERCENTAGES
        if "original_interest_rate_pct" in loans_df.columns:
            rate_score = loans_df[["original_interest_rate_pct", "obligor_credit_score"]].dropna()
            if len(rate_score) > 0:
                st.subheader("Interest Rate vs Credit Score")
                sample = rate_score.sample(min(5000, len(rate_score)), random_state=42)
                fig = px.scatter(
                    sample, x="obligor_credit_score", y="original_interest_rate_pct",
                    title="Original Interest Rate vs Credit Score",
                    labels={"obligor_credit_score": "Credit Score",
                            "original_interest_rate_pct": "Interest Rate (%)"},
                    opacity=0.3,
                )
                fig.update_layout(yaxis_ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)

        # Summary statistics with rates as percentages
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
            stat_data["LTV"] = (loans_df["original_ltv"] * 100).describe()
        if stat_data:
            stats_df = pd.DataFrame(stat_data)
            st.dataframe(stats_df.style.format("{:.2f}"), use_container_width=True)


# ============================================================
# TAB 5: DATA FIELDS
# ============================================================
with tab_fields:
    st.subheader("Available Data Fields")
    st.markdown("These are the fields available in the loan-level data from SEC EDGAR ABS-EE filings.")

    st.markdown("### Loan Static Data (one per loan)")
    loan_fields = {
        "asset_number": "Unique loan identifier",
        "originator_name": "Entity that originated the loan (Carvana, LLC)",
        "origination_date": "Month/year the loan was originated",
        "original_loan_amount": "Loan amount at origination ($)",
        "original_loan_term": "Loan term in months at origination",
        "original_interest_rate": "Interest rate at origination (decimal, e.g. 0.0599 = 5.99%)",
        "loan_maturity_date": "Scheduled final payment month/year",
        "original_ltv": "Loan-to-value ratio (loan amount / vehicle value)",
        "vehicle_manufacturer": "Vehicle make (Toyota, Honda, Ford, etc.)",
        "vehicle_model": "Vehicle model (Camry, Civic, F-150, etc.)",
        "vehicle_new_used": "1 = New, 2 = Used",
        "vehicle_model_year": "Vehicle model year",
        "vehicle_type": "Vehicle type code (1 = passenger car, etc.)",
        "vehicle_value": "Vehicle value at origination ($)",
        "obligor_credit_score": "Borrower credit score at origination",
        "obligor_credit_score_type": "Credit score model used",
        "obligor_geographic_location": "Borrower state (2-letter code)",
        "co_obligor_indicator": "Whether there is a co-borrower (true/false)",
        "payment_to_income_ratio": "Monthly payment as % of income (decimal)",
        "income_verification_level": "How income was verified (1-4)",
        "payment_type": "Payment type code",
        "subvention_indicator": "Whether rate was subsidized",
    }
    st.dataframe(
        pd.DataFrame(loan_fields.items(), columns=["Field", "Description"]),
        use_container_width=True, hide_index=True,
    )

    st.markdown("### Monthly Performance Data (one per loan per month)")
    perf_fields = {
        "reporting_period_end": "End date of the reporting period",
        "beginning_balance": "Loan balance at start of period ($)",
        "ending_balance": "Loan balance at end of period ($)",
        "scheduled_payment": "Scheduled payment amount ($)",
        "actual_amount_paid": "Actual total amount paid ($)",
        "actual_interest_collected": "Interest portion of payment ($)",
        "actual_principal_collected": "Principal portion of payment ($)",
        "current_interest_rate": "Current interest rate (decimal)",
        "current_delinquency_status": "Months delinquent (0=current, 1=30d, 2=60d, 3=90d, 4+=120d+)",
        "remaining_term": "Remaining months to maturity",
        "paid_through_date": "Date through which interest is paid",
        "zero_balance_code": "Why balance went to zero (1=prepaid, 2=matured, 3=charged off, etc.)",
        "zero_balance_date": "Month/year balance went to zero",
        "charged_off_amount": "Amount charged off this period ($)",
        "recoveries": "Amount recovered this period ($)",
        "modification_indicator": "Whether loan was modified (true/false)",
        "servicing_fee": "Servicing fee amount or percentage",
    }
    st.dataframe(
        pd.DataFrame(perf_fields.items(), columns=["Field", "Description"]),
        use_container_width=True, hide_index=True,
    )
