"""Delinquencies page."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_lp, load_pool, get_deal, get_orig_bal, MOBILE_CSS

st.set_page_config(page_title="Delinquencies", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
lp = load_lp(deal)

st.header(f"Delinquencies — {deal}")

if lp.empty:
    st.info("No data yet.")
    st.stop()

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

# Trigger chart
pool_df = load_pool(deal)
if not pool_df.empty and "delinquency_trigger_level" in pool_df.columns:
    trig = pool_df[["period", "delinquency_trigger_level", "delinquency_trigger_actual"]].dropna()
    if not trig.empty:
        st.subheader("60+ DQ vs Trigger Level")
        ft = go.Figure()
        ft.add_trace(go.Scatter(x=trig["period"], y=trig["delinquency_trigger_level"], name="Trigger", line=dict(dash="dash", color="red")))
        ft.add_trace(go.Scatter(x=trig["period"], y=trig["delinquency_trigger_actual"], name="Actual", line=dict(color="blue")))
        ft.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
        st.plotly_chart(ft, use_container_width=True)

# Summary table
last = lp.iloc[-1]
st.subheader("Latest Period")
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
