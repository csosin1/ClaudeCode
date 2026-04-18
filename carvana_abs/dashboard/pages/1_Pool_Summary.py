"""Pool Summary page."""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_lp, load_pool, get_deal, get_orig_bal, fmt_compact, MOBILE_CSS

st.set_page_config(page_title="Pool Summary", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
ORIG_BAL = get_orig_bal()
lp = load_lp(deal)
pool_df = load_pool(deal)

st.header(f"Pool Summary — {deal}")

if lp.empty:
    st.info("No data yet.")
    st.stop()

last = lp.iloc[-1]
r1c1, r1c2 = st.columns(2)
r1c1.metric("Original Balance", fmt_compact(ORIG_BAL))
r1c2.metric("Current Balance", fmt_compact(last["total_balance"]))
r2c1, r2c2 = st.columns(2)
r2c1.metric("Pool Factor", f"{last['total_balance']/ORIG_BAL:.2%}")
r2c2.metric("Active Loans", f"{int(last['active_loans']):,}")

fig = px.area(lp, x="period", y="total_balance", title="Remaining Pool Balance",
              labels={"period": "Period", "total_balance": "Balance ($)"})
fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

fig2 = px.line(lp, x="period", y="active_loans", title="Active Loan Count")
fig2.update_layout(hovermode="x unified")
st.plotly_chart(fig2, use_container_width=True)

# WAC/WAM from pool_performance
if not pool_df.empty:
    wac = pool_df[["period", "weighted_avg_apr"]].dropna()
    wam = pool_df[["period", "weighted_avg_remaining_term"]].dropna()
    if not wac.empty or not wam.empty:
        st.subheader("Pool Statistics")
        c1, c2 = st.columns(2)
        if not wac.empty:
            with c1:
                f = px.line(wac, x="period", y="weighted_avg_apr", title="WAC")
                f.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
                st.plotly_chart(f, use_container_width=True)
        if not wam.empty:
            with c2:
                f = px.line(wam, x="period", y="weighted_avg_remaining_term", title="WAM (months)")
                f.update_layout(hovermode="x unified")
                st.plotly_chart(f, use_container_width=True)

    # Note balances
    note_cols = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                              "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
                 if c in pool_df.columns and pool_df[c].notna().any()]
    if note_cols:
        st.subheader("Note Balances by Class")
        nm = pool_df[["period"] + note_cols].melt(id_vars=["period"], var_name="Class", value_name="Balance")
        nm["Class"] = nm["Class"].str.replace("note_balance_", "").str.upper()
        f = px.area(nm, x="period", y="Balance", color="Class")
        f.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(f, use_container_width=True)

    # OC and Reserve
    oc = pool_df[["period", "overcollateralization_amount", "reserve_account_balance"]].dropna(
        how="all", subset=["overcollateralization_amount", "reserve_account_balance"])
    if not oc.empty:
        st.subheader("Credit Enhancement")
        f = go.Figure()
        if oc["overcollateralization_amount"].notna().any():
            f.add_trace(go.Scatter(x=oc["period"], y=oc["overcollateralization_amount"], name="OC"))
        if oc["reserve_account_balance"].notna().any():
            f.add_trace(go.Scatter(x=oc["period"], y=oc["reserve_account_balance"], name="Reserve"))
        f.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
        st.plotly_chart(f, use_container_width=True)
