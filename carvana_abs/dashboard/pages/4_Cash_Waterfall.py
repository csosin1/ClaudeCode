"""Cash Waterfall page."""
import streamlit as st
import plotly.express as px
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_lp, get_deal, get_orig_bal, fmt_compact, MOBILE_CSS

st.set_page_config(page_title="Cash Waterfall", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
ORIG_BAL = get_orig_bal()
lp = load_lp(deal)

st.header(f"Cash Waterfall — {deal}")

if lp.empty:
    st.info("No data yet.")
    st.stop()

wf = lp[["period", "interest_collected", "principal_collected", "period_recoveries",
          "est_servicing_fee", "period_chargeoffs", "net_losses", "excess_spread"]].copy()
wf.columns = ["Period", "Interest", "Principal", "Recoveries", "Svc Fee", "Chargeoffs", "Net Loss", "Excess"]

sums = wf.select_dtypes(include="number").sum()
sum_row = pd.DataFrame([["TOTAL"] + sums.tolist()], columns=wf.columns)
wf_display = pd.concat([wf, sum_row], ignore_index=True)

st.markdown("### Monthly Cash Flows")
fmt_d = wf_display.copy()
for c in fmt_d.columns[1:]:
    fmt_d[c] = fmt_d[c].apply(lambda x: fmt_compact(x) if pd.notna(x) else "")
st.dataframe(fmt_d, use_container_width=True, hide_index=True, height=400)

st.subheader("Cumulative Excess Spread (% of Original Balance)")
lp_es = lp.copy()
lp_es["cum_excess_pct"] = lp_es["cum_excess"] / ORIG_BAL
fig = px.area(lp_es, x="period", y="cum_excess_pct", title="Cumulative Excess Spread")
fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
fig.update_traces(line_color="#388E3C", fillcolor="rgba(56,142,60,0.2)")
st.plotly_chart(fig, use_container_width=True)
