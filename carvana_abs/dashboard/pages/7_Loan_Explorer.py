"""Loan Explorer page."""
import streamlit as st
import plotly.express as px
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_loans, get_deal, MOBILE_CSS

st.set_page_config(page_title="Loan Explorer", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
st.header(f"Loan Explorer — {deal}")

loans_df = load_loans(deal)
if loans_df.empty:
    st.info("No data yet.")
    st.stop()

c1, c2 = st.columns(2)
with c1:
    s = loans_df["obligor_credit_score"].dropna()
    if not s.empty:
        fig = px.histogram(s, nbins=30, title="Credit Score", color_discrete_sequence=["#1976D2"])
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
with c2:
    a = loans_df["original_loan_amount"].dropna()
    if not a.empty:
        fig = px.histogram(a, nbins=30, title="Loan Amount", color_discrete_sequence=["#388E3C"])
        fig.update_layout(xaxis_tickformat="$,.0f", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

c3, c4 = st.columns(2)
with c3:
    m = loans_df["vehicle_manufacturer"].dropna().value_counts().head(15)
    if not m.empty:
        fig = px.bar(x=m.values, y=m.index, orientation="h", title="Top Manufacturers",
                     color_discrete_sequence=["#FF9800"])
        fig.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
with c4:
    s = loans_df["obligor_geographic_location"].dropna().value_counts().head(15)
    if not s.empty:
        fig = px.bar(x=s.values, y=s.index, orientation="h", title="Top States",
                     color_discrete_sequence=["#7B1FA2"])
        fig.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

if "rate_pct" in loans_df.columns:
    rs = loans_df[["rate_pct", "obligor_credit_score"]].dropna()
    if len(rs) > 0:
        st.subheader("Rate vs Credit Score")
        sample = rs.sample(min(5000, len(rs)), random_state=42)
        fig = px.scatter(sample, x="obligor_credit_score", y="rate_pct",
                         labels={"obligor_credit_score": "Score", "rate_pct": "Rate (%)"},
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
