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
        "Run the ingestion script first:\n\n"
        "```bash\n"
        "export SEC_USER_AGENT='YourName your-email@example.com'\n"
        "cd carvana_abs && python run_ingestion.py\n"
        "```"
    )
    st.stop()

# --- Sidebar: Deal Selector ---
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

    filing_df = query_df(
        "SELECT filing_type, COUNT(*) as cnt, SUM(ingested_pool) as pool, SUM(ingested_loans) as loans "
        "FROM filings WHERE deal = ? GROUP BY filing_type", (selected_deal,)
    )
    if not filing_df.empty:
        for _, row in filing_df.iterrows():
            st.metric(f"{row['filing_type']} Filings", int(row["cnt"]))

    pool_count = query_df(
        "SELECT COUNT(*) as n FROM pool_performance WHERE deal = ?", (selected_deal,)
    )
    loan_count = query_df(
        "SELECT COUNT(*) as n FROM loans WHERE deal = ?", (selected_deal,)
    )

    if not pool_count.empty:
        st.metric("Pool Data Points", int(pool_count.iloc[0]["n"]))
    if not loan_count.empty:
        st.metric("Unique Loans", int(loan_count.iloc[0]["n"]))

    st.markdown("---")

    # Deal comparison toggle (only if multiple deals)
    compare_mode = False
    compare_deals = []
    if len(deal_list) > 1:
        compare_mode = st.checkbox("Compare Deals")
        if compare_mode:
            compare_deals = st.multiselect(
                "Compare with", [d for d in deal_list if d != selected_deal]
            )

    st.caption("Data sourced from SEC EDGAR 10-D filings")


# --- Data Loading ---
def load_pool(deal: str) -> pd.DataFrame:
    return query_df(
        "SELECT * FROM pool_performance WHERE deal = ? ORDER BY distribution_date",
        (deal,)
    )


def load_loans(deal: str) -> pd.DataFrame:
    return query_df(
        "SELECT * FROM loans WHERE deal = ?", (deal,)
    )


def load_loan_perf_agg(deal: str) -> pd.DataFrame:
    return query_df("""
        SELECT
            reporting_period_end,
            COUNT(*) as active_loans,
            SUM(ending_balance) as total_balance,
            SUM(CASE WHEN current_delinquency_status IS NOT NULL
                AND current_delinquency_status != '0'
                AND current_delinquency_status != ''
                THEN ending_balance ELSE 0 END) as delinquent_balance,
            SUM(COALESCE(charged_off_amount, 0)) as period_chargeoffs,
            SUM(COALESCE(recoveries, 0)) as period_recoveries,
            COUNT(CASE WHEN days_delinquent >= 30 AND days_delinquent < 60 THEN 1 END) as dq_30_59,
            COUNT(CASE WHEN days_delinquent >= 60 AND days_delinquent < 90 THEN 1 END) as dq_60_89,
            COUNT(CASE WHEN days_delinquent >= 90 AND days_delinquent < 120 THEN 1 END) as dq_90_119,
            COUNT(CASE WHEN days_delinquent >= 120 THEN 1 END) as dq_120_plus
        FROM loan_performance WHERE deal = ?
        GROUP BY reporting_period_end
        ORDER BY reporting_period_end
    """, (deal,))


pool_df = load_pool(selected_deal)
loans_df = load_loans(selected_deal)
loan_perf_df = load_loan_perf_agg(selected_deal)


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

        # Build the primary balance chart
        if not pool_df.empty:
            chart_df = pool_df[["distribution_date", "ending_pool_balance"]].dropna()

            # If comparing, overlay other deals
            if compare_mode and compare_deals:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=chart_df["distribution_date"], y=chart_df["ending_pool_balance"],
                    name=selected_deal, mode="lines", fill="tozeroy",
                ))
                for cd in compare_deals:
                    cd_df = load_pool(cd)[["distribution_date", "ending_pool_balance"]].dropna()
                    if not cd_df.empty:
                        fig.add_trace(go.Scatter(
                            x=cd_df["distribution_date"], y=cd_df["ending_pool_balance"],
                            name=cd, mode="lines",
                        ))
                fig.update_layout(
                    title="Remaining Pool Balance — Deal Comparison",
                    yaxis_tickformat="$,.0f", hovermode="x unified",
                )
            else:
                fig = px.area(
                    chart_df, x="distribution_date", y="ending_pool_balance",
                    title="Remaining Pool Balance",
                    labels={"distribution_date": "Distribution Date",
                            "ending_pool_balance": "Balance ($)"},
                )
                fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")

            st.plotly_chart(fig, use_container_width=True)

            # Key metrics
            if pool_df["beginning_pool_balance"].iloc[0]:
                original = pool_df["beginning_pool_balance"].iloc[0]
                current = pool_df["ending_pool_balance"].iloc[-1] if pd.notna(pool_df["ending_pool_balance"].iloc[-1]) else 0
                pool_factor = current / original if original else 0

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Original Pool Balance", f"${original:,.0f}")
                col2.metric("Current Pool Balance", f"${current:,.0f}")
                col3.metric("Pool Factor", f"{pool_factor:.2%}")
                if pool_df["ending_pool_count"].iloc[-1]:
                    col4.metric("Active Loans", f"{int(pool_df['ending_pool_count'].iloc[-1]):,}")

        elif not loan_perf_df.empty:
            fig = px.area(
                loan_perf_df, x="reporting_period_end", y="total_balance",
                title="Remaining Pool Balance (from loan-level data)",
                labels={"reporting_period_end": "Period End", "total_balance": "Balance ($)"},
            )
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

        # Pool statistics over time
        if not pool_df.empty:
            stat_cols = ["weighted_avg_apr", "weighted_avg_remaining_term"]
            available_stats = [c for c in stat_cols if c in pool_df.columns and pool_df[c].notna().any()]
            if available_stats:
                st.subheader("Pool Statistics")
                col1, col2 = st.columns(2)
                if "weighted_avg_apr" in available_stats:
                    with col1:
                        wac_df = pool_df[["distribution_date", "weighted_avg_apr"]].dropna()
                        if not wac_df.empty:
                            fig = px.line(wac_df, x="distribution_date", y="weighted_avg_apr",
                                          title="Weighted Average APR")
                            fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                            st.plotly_chart(fig, use_container_width=True)
                if "weighted_avg_remaining_term" in available_stats:
                    with col2:
                        wam_df = pool_df[["distribution_date", "weighted_avg_remaining_term"]].dropna()
                        if not wam_df.empty:
                            fig = px.line(wam_df, x="distribution_date", y="weighted_avg_remaining_term",
                                          title="Weighted Average Remaining Term (months)")
                            fig.update_layout(hovermode="x unified")
                            st.plotly_chart(fig, use_container_width=True)

        # Note balances
        if not pool_df.empty:
            note_cols = [c for c in pool_df.columns if c.startswith("note_balance_")]
            note_df = pool_df[["distribution_date"] + note_cols].dropna(how="all", subset=note_cols)
            if not note_df.empty and note_df[note_cols].notna().any().any():
                st.subheader("Note Balances by Class")
                note_melted = note_df.melt(
                    id_vars=["distribution_date"], value_vars=note_cols,
                    var_name="Note Class", value_name="Balance"
                )
                note_melted["Note Class"] = (
                    note_melted["Note Class"]
                    .str.replace("note_balance_", "Class ")
                    .str.upper()
                )
                fig = px.area(
                    note_melted, x="distribution_date", y="Balance",
                    color="Note Class", title="Note Balances Over Time",
                )
                fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)


# ============================================================
# TAB 2: DELINQUENCIES
# ============================================================
with tab_dq:
    st.subheader("Delinquency Analysis")

    has_pool_dq = (not pool_df.empty and
                   pool_df.get("delinquent_31_60_balance") is not None and
                   pool_df["delinquent_31_60_balance"].notna().any())
    has_loan_dq = not loan_perf_df.empty and "dq_30_59" in loan_perf_df.columns

    if has_pool_dq:
        dq_cols = ["delinquent_31_60_balance", "delinquent_61_90_balance",
                    "delinquent_91_120_balance", "delinquent_121_plus_balance"]
        available_dq = [c for c in dq_cols if c in pool_df.columns]
        dq_df = pool_df[["distribution_date"] + available_dq].dropna(how="all", subset=available_dq)

        if not dq_df.empty:
            dq_melted = dq_df.melt(
                id_vars=["distribution_date"], value_vars=available_dq,
                var_name="Bucket", value_name="Balance"
            )
            label_map = {
                "delinquent_31_60_balance": "31-60 Days",
                "delinquent_61_90_balance": "61-90 Days",
                "delinquent_91_120_balance": "91-120 Days",
                "delinquent_121_plus_balance": "121+ Days",
            }
            dq_melted["Bucket"] = dq_melted["Bucket"].map(label_map)

            # Compare mode
            if compare_mode and compare_deals:
                fig = go.Figure()
                # Total delinquent for selected deal
                if "total_delinquent_balance" in pool_df.columns:
                    td = pool_df[["distribution_date", "total_delinquent_balance"]].dropna()
                    fig.add_trace(go.Scatter(
                        x=td["distribution_date"], y=td["total_delinquent_balance"],
                        name=selected_deal, mode="lines",
                    ))
                for cd in compare_deals:
                    cd_pool = load_pool(cd)
                    if "total_delinquent_balance" in cd_pool.columns:
                        cd_td = cd_pool[["distribution_date", "total_delinquent_balance"]].dropna()
                        if not cd_td.empty:
                            fig.add_trace(go.Scatter(
                                x=cd_td["distribution_date"], y=cd_td["total_delinquent_balance"],
                                name=cd, mode="lines",
                            ))
                fig.update_layout(
                    title="Total Delinquent Balance — Deal Comparison",
                    yaxis_tickformat="$,.0f", hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                fig = px.area(
                    dq_melted, x="distribution_date", y="Balance", color="Bucket",
                    title="Delinquent Balance by Bucket",
                    color_discrete_sequence=["#FFC107", "#FF9800", "#FF5722", "#D32F2F"],
                )
                fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
                st.plotly_chart(fig, use_container_width=True)

            # Delinquency rate
            if "ending_pool_balance" in pool_df.columns and "total_delinquent_balance" in pool_df.columns:
                rate_df = pool_df[["distribution_date", "total_delinquent_balance", "ending_pool_balance"]].dropna()
                rate_df["delinquency_rate"] = rate_df["total_delinquent_balance"] / rate_df["ending_pool_balance"]

                fig2 = px.line(
                    rate_df, x="distribution_date", y="delinquency_rate",
                    title="Total Delinquency Rate (% of Pool Balance)",
                )
                fig2.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                st.plotly_chart(fig2, use_container_width=True)

            # Delinquency trigger
            if pool_df.get("delinquency_trigger_level") is not None:
                trigger_df = pool_df[["distribution_date", "delinquency_trigger_level",
                                       "delinquency_trigger_actual"]].dropna()
                if not trigger_df.empty:
                    st.subheader("Delinquency Trigger")
                    fig3 = go.Figure()
                    fig3.add_trace(go.Scatter(
                        x=trigger_df["distribution_date"], y=trigger_df["delinquency_trigger_level"],
                        name="Trigger Level", line=dict(dash="dash", color="red"),
                    ))
                    fig3.add_trace(go.Scatter(
                        x=trigger_df["distribution_date"], y=trigger_df["delinquency_trigger_actual"],
                        name="Actual", line=dict(color="blue"),
                    ))
                    fig3.update_layout(
                        title="60+ Day Delinquency vs Trigger Level",
                        yaxis_tickformat=".2%", hovermode="x unified",
                    )
                    st.plotly_chart(fig3, use_container_width=True)

    elif has_loan_dq:
        st.markdown("*Delinquency data from loan-level records*")
        dq_count_df = loan_perf_df[["reporting_period_end", "dq_30_59", "dq_60_89", "dq_90_119", "dq_120_plus"]]
        dq_melted = dq_count_df.melt(id_vars=["reporting_period_end"], var_name="Bucket", value_name="Count")
        label_map = {"dq_30_59": "30-59 Days", "dq_60_89": "60-89 Days",
                     "dq_90_119": "90-119 Days", "dq_120_plus": "120+ Days"}
        dq_melted["Bucket"] = dq_melted["Bucket"].map(label_map)
        fig = px.area(
            dq_melted, x="reporting_period_end", y="Count", color="Bucket",
            title="Delinquent Loan Count by Bucket",
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

    has_pool_losses = not pool_df.empty and pool_df.get("cumulative_net_losses") is not None and pool_df["cumulative_net_losses"].notna().any()

    if has_pool_losses:
        # Cumulative net losses
        cum_df = pool_df[["distribution_date", "cumulative_net_losses"]].dropna()

        if compare_mode and compare_deals:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cum_df["distribution_date"], y=cum_df["cumulative_net_losses"],
                name=selected_deal, mode="lines", fill="tozeroy",
            ))
            for cd in compare_deals:
                cd_pool = load_pool(cd)
                cd_cum = cd_pool[["distribution_date", "cumulative_net_losses"]].dropna()
                if not cd_cum.empty:
                    fig.add_trace(go.Scatter(
                        x=cd_cum["distribution_date"], y=cd_cum["cumulative_net_losses"],
                        name=cd, mode="lines",
                    ))
            fig.update_layout(
                title="Cumulative Net Losses — Deal Comparison",
                yaxis_tickformat="$,.0f", hovermode="x unified",
            )
        else:
            fig = px.area(
                cum_df, x="distribution_date", y="cumulative_net_losses",
                title="Cumulative Net Losses",
            )
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.3)")

        st.plotly_chart(fig, use_container_width=True)

        # Monthly charge-offs vs recoveries
        loss_cols = ["distribution_date"]
        for c in ["gross_charged_off_amount", "net_charged_off_amount", "recoveries", "liquidation_proceeds"]:
            if c in pool_df.columns:
                loss_cols.append(c)
        monthly_df = pool_df[loss_cols].dropna(how="all", subset=loss_cols[1:])
        if len(loss_cols) > 1 and not monthly_df.empty:
            fig2 = go.Figure()
            charge_col = "gross_charged_off_amount" if "gross_charged_off_amount" in loss_cols else "net_charged_off_amount"
            if charge_col in loss_cols:
                fig2.add_trace(go.Bar(
                    x=monthly_df["distribution_date"], y=monthly_df[charge_col],
                    name="Charge-offs", marker_color="#D32F2F",
                ))
            if "recoveries" in loss_cols:
                fig2.add_trace(go.Bar(
                    x=monthly_df["distribution_date"], y=monthly_df["recoveries"],
                    name="Recoveries", marker_color="#4CAF50",
                ))
            fig2.update_layout(
                title="Monthly Charge-offs vs Recoveries",
                barmode="group", yaxis_tickformat="$,.0f", hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Cumulative loss rate
        original_balance = deal_cfg.get("original_pool_balance") or (
            pool_df["beginning_pool_balance"].iloc[0] if pool_df["beginning_pool_balance"].iloc[0] else None
        )
        if original_balance and not cum_df.empty:
            rate_df = cum_df.copy()
            rate_df["loss_rate"] = rate_df["cumulative_net_losses"] / original_balance

            if compare_mode and compare_deals:
                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(
                    x=rate_df["distribution_date"], y=rate_df["loss_rate"],
                    name=selected_deal, mode="lines",
                ))
                for cd in compare_deals:
                    cd_pool = load_pool(cd)
                    cd_cfg = DEALS.get(cd, {})
                    cd_orig = cd_cfg.get("original_pool_balance") or (
                        cd_pool["beginning_pool_balance"].iloc[0] if not cd_pool.empty else None
                    )
                    if cd_orig:
                        cd_cum = cd_pool[["distribution_date", "cumulative_net_losses"]].dropna()
                        cd_cum["loss_rate"] = cd_cum["cumulative_net_losses"] / cd_orig
                        fig3.add_trace(go.Scatter(
                            x=cd_cum["distribution_date"], y=cd_cum["loss_rate"],
                            name=cd, mode="lines",
                        ))
                fig3.update_layout(
                    title="Cumulative Loss Rate — Deal Comparison",
                    yaxis_tickformat=".2%", hovermode="x unified",
                )
            else:
                fig3 = px.line(
                    rate_df, x="distribution_date", y="loss_rate",
                    title=f"Cumulative Loss Rate (% of ${original_balance:,.0f} original balance)",
                )
                fig3.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                fig3.update_traces(line_color="#D32F2F")

            st.plotly_chart(fig3, use_container_width=True)

    elif not loan_perf_df.empty:
        st.markdown("*Loss data from loan-level records*")
        loss_df = loan_perf_df[["reporting_period_end", "period_chargeoffs", "period_recoveries"]].copy()
        loss_df["cumulative_net_losses"] = (loss_df["period_chargeoffs"] - loss_df["period_recoveries"]).cumsum()
        fig = px.area(
            loss_df, x="reporting_period_end", y="cumulative_net_losses",
            title="Cumulative Net Losses (from loan-level data)",
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

        # Rate vs Score scatter
        rate_score = loans_df[["original_interest_rate", "obligor_credit_score"]].dropna()
        if len(rate_score) > 0:
            st.subheader("Interest Rate vs Credit Score")
            sample = rate_score.sample(min(5000, len(rate_score)), random_state=42)
            fig = px.scatter(
                sample, x="obligor_credit_score", y="original_interest_rate",
                title="Original Interest Rate vs Credit Score",
                labels={"obligor_credit_score": "Credit Score",
                        "original_interest_rate": "Interest Rate (%)"},
                opacity=0.3,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Summary statistics
        st.subheader("Portfolio Summary Statistics")
        stat_cols = ["original_loan_amount", "original_interest_rate",
                     "original_loan_term", "obligor_credit_score", "original_ltv"]
        available = [c for c in stat_cols if c in loans_df.columns]
        if available:
            st.dataframe(
                loans_df[available].describe().style.format("{:.2f}"),
                use_container_width=True,
            )
