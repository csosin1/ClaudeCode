"""Recovery Analysis page."""
import streamlit as st
import plotly.express as px
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_recovery_data, get_deal, fmt_compact, MOBILE_CSS

st.set_page_config(page_title="Recovery Analysis", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
rec_df = load_recovery_data(deal)

st.header(f"Recovery Analysis — {deal}")

if rec_df.empty:
    st.info("No chargeoff data found.")
    st.stop()

total_co = len(rec_df)
with_rec = rec_df["has_recovery"].sum()
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

rec_with = rec_df[rec_df["has_recovery"] & rec_df["months_to_recovery"].notna()]
if not rec_with.empty:
    st.subheader("Months from Chargeoff to First Recovery")
    fig = px.histogram(rec_with, x="months_to_recovery", nbins=30, color_discrete_sequence=["#1976D2"])
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

rec_rates = rec_df[rec_df["has_recovery"]]["recovery_rate"].dropna()
if not rec_rates.empty:
    st.subheader("Recovery Rate Distribution")
    fig2 = px.histogram(rec_rates.clip(upper=1.5), nbins=40, color_discrete_sequence=["#4CAF50"])
    fig2.update_layout(xaxis_tickformat=".0%", showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("Recovery Rate by Credit Score")
rec_scored = rec_df[rec_df["obligor_credit_score"].notna()].copy()
if not rec_scored.empty:
    rec_scored["bucket"] = pd.cut(rec_scored["obligor_credit_score"],
        bins=[0,580,620,660,700,740,780,820,900],
        labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
    by_score = rec_scored.groupby("bucket", observed=True).agg(
        count=("asset_number","count"), with_rec=("has_recovery","sum"),
        co=("total_chargeoff","sum"), rec=("total_recoveries", lambda x: x.dropna().sum())).reset_index()
    by_score["rate"] = by_score["rec"] / by_score["co"]
    d = by_score[["bucket","count","co","rec","rate"]].copy()
    d.columns = ["Score","Chargeoffs","Total CO","Recovered","Recovery Rate"]
    d["Total CO"] = d["Total CO"].apply(fmt_compact)
    d["Recovered"] = d["Recovered"].apply(fmt_compact)
    d["Recovery Rate"] = d["Recovery Rate"].apply(lambda x: f"{x:.1%}")
    st.dataframe(d, use_container_width=True, hide_index=True)
