"""Carvana ABS Dashboard — Entrypoint (sidebar + shared state only)."""

import streamlit as st
from utils import get_db, query_df, fmt_compact, MOBILE_CSS, DEALS, DB_PATH

st.set_page_config(page_title="Carvana ABS Dashboard", page_icon="\U0001F4CA", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

conn = get_db()
if conn is None:
    st.error(f"Database not found at `{DB_PATH}`.")
    st.stop()

# Deal list
available_deals = query_df("SELECT DISTINCT deal FROM filings ORDER BY deal")
deal_list = available_deals["deal"].tolist() if not available_deals.empty else list(DEALS.keys())

# Sidebar — deal selector and summary
with st.sidebar:
    st.header("Carvana ABS")
    selected_deal = st.selectbox("Deal", deal_list, index=0)
    st.session_state["selected_deal"] = selected_deal

    deal_cfg = DEALS.get(selected_deal, {})
    if deal_cfg:
        st.caption(deal_cfg.get("entity_name", ""))

    # Auto-detect original balance
    _configured_bal = deal_cfg.get("original_pool_balance")
    if _configured_bal:
        ORIG_BAL = _configured_bal
    else:
        _fp = query_df(
            "SELECT beginning_pool_balance FROM pool_performance WHERE deal = ? ORDER BY distribution_date LIMIT 1",
            (selected_deal,))
        if not _fp.empty and _fp.iloc[0]["beginning_pool_balance"]:
            ORIG_BAL = _fp.iloc[0]["beginning_pool_balance"]
        else:
            _total = query_df("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal = ?", (selected_deal,))
            ORIG_BAL = _total.iloc[0]["s"] if not _total.empty and _total.iloc[0]["s"] else 405_000_000
    st.session_state["ORIG_BAL"] = ORIG_BAL

    st.markdown("---")
    lc = query_df("SELECT COUNT(*) as n FROM loans WHERE deal = ?", (selected_deal,))
    pp = query_df("SELECT COUNT(*) as n FROM pool_performance WHERE deal = ?", (selected_deal,))
    ms = query_df("SELECT COUNT(*) as n FROM monthly_summary WHERE deal = ?", (selected_deal,))
    if not lc.empty:
        st.metric("Loans", f"{int(lc.iloc[0]['n']):,}")
    if not ms.empty and ms.iloc[0]["n"] > 0:
        st.metric("Periods", int(ms.iloc[0]["n"]))
    if not pp.empty:
        st.metric("Pool Records", int(pp.iloc[0]["n"]))

# Main page content
st.title("Carvana Auto Receivables Trust")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")
st.markdown(f"**Selected Deal:** {selected_deal} — {deal_cfg.get('entity_name', '')}")
st.markdown("Use the sidebar to navigate between pages.")
