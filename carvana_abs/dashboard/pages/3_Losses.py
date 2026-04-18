"""Losses page."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_lp, load_losses_by_segment, get_deal, get_orig_bal, fmt_compact, MOBILE_CSS

st.set_page_config(page_title="Losses", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
ORIG_BAL = get_orig_bal()
lp = load_lp(deal)

st.header(f"Losses — {deal}")

if lp.empty:
    st.info("No data yet.")
    st.stop()

last = lp.iloc[-1]
la1, la2 = st.columns(2)
la1.metric("Cum Net Losses", fmt_compact(last['cum_net_losses']))
la2.metric("Loss Rate", f"{last['cum_loss_rate']:.2%}")
lb1, lb2 = st.columns(2)
lb1.metric("Cum Gross Losses", fmt_compact(last['cum_chargeoffs']))
lb2.metric("Through", last["period"])

fig = px.area(lp, x="period", y="cum_loss_rate", title=f"Cumulative Net Loss Rate (% of {fmt_compact(ORIG_BAL)})")
fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Cumulative Gross Losses vs Recoveries")
fg = go.Figure()
fg.add_trace(go.Scatter(x=lp["period"], y=lp["cum_chargeoffs"], name="Gross Chargeoffs", line=dict(color="#D32F2F")))
fg.add_trace(go.Scatter(x=lp["period"], y=lp["cum_recoveries"], name="Recoveries", line=dict(color="#4CAF50")))
fg.add_trace(go.Scatter(x=lp["period"], y=lp["cum_net_losses"], name="Net Losses", line=dict(color="#FF9800", dash="dash")))
fg.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
st.plotly_chart(fg, use_container_width=True)

st.subheader("Cumulative Recovery Rate")
fr = px.line(lp.dropna(subset=["cum_recovery_rate"]), x="period", y="cum_recovery_rate")
fr.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
fr.update_traces(line_color="#4CAF50")
st.plotly_chart(fr, use_container_width=True)

f2 = go.Figure()
f2.add_trace(go.Bar(x=lp["period"], y=lp["period_chargeoffs"], name="Chargeoffs", marker_color="#D32F2F"))
f2.add_trace(go.Bar(x=lp["period"], y=lp["period_recoveries"], name="Recoveries", marker_color="#4CAF50"))
f2.update_layout(title="Monthly Chargeoffs vs Recoveries", barmode="group", yaxis_tickformat="$,.0f", hovermode="x unified")
st.plotly_chart(f2, use_container_width=True)

# By credit score
st.subheader("Losses by Credit Score")
lbs = load_losses_by_segment(deal, "obligor_credit_score")
if not lbs.empty:
    lbs["s"] = pd.to_numeric(lbs["segment"], errors="coerce")
    lbs = lbs.dropna(subset=["s"])
    lbs["bucket"] = pd.cut(lbs["s"], bins=[0,580,620,660,700,740,780,820,900],
                           labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
    b = lbs.groupby("bucket", observed=True).agg({"loan_count":"sum","original_balance":"sum","total_chargeoffs":"sum","total_recoveries":"sum"}).reset_index()
    b["net"] = b["total_chargeoffs"] - b["total_recoveries"]
    b["rate"] = b["net"] / b["original_balance"]
    d = b[["bucket","loan_count","original_balance","net","rate"]].copy()
    d.columns = ["Score","Loans","Orig Bal","Net Loss","Loss Rate"]
    d["Orig Bal"] = d["Orig Bal"].apply(lambda x: fmt_compact(x))
    d["Net Loss"] = d["Net Loss"].apply(lambda x: fmt_compact(x))
    d["Loss Rate"] = d["Loss Rate"].apply(lambda x: f"{x:.2%}")
    d["Loans"] = d["Loans"].apply(lambda x: f"{x:,}")
    st.dataframe(d, use_container_width=True, hide_index=True)

# By rate
st.subheader("Losses by Interest Rate")
lbr = load_losses_by_segment(deal, "original_interest_rate")
if not lbr.empty:
    lbr["r"] = pd.to_numeric(lbr["segment"], errors="coerce")
    lbr = lbr.dropna(subset=["r"])
    lbr["bucket"] = pd.cut(lbr["r"], bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                           labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
    b = lbr.groupby("bucket", observed=True).agg({"loan_count":"sum","original_balance":"sum","total_chargeoffs":"sum","total_recoveries":"sum"}).reset_index()
    b["net"] = b["total_chargeoffs"] - b["total_recoveries"]
    b["rate"] = b["net"] / b["original_balance"]
    d = b[["bucket","loan_count","original_balance","net","rate"]].copy()
    d.columns = ["Rate","Loans","Orig Bal","Net Loss","Loss Rate"]
    d["Orig Bal"] = d["Orig Bal"].apply(lambda x: fmt_compact(x))
    d["Net Loss"] = d["Net Loss"].apply(lambda x: fmt_compact(x))
    d["Loss Rate"] = d["Loss Rate"].apply(lambda x: f"{x:.2%}")
    d["Loans"] = d["Loans"].apply(lambda x: f"{x:,}")
    st.dataframe(d, use_container_width=True, hide_index=True)
