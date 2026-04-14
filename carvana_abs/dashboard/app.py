"""Carvana ABS Dashboard — Entrypoint (sidebar + shared state only)."""

import streamlit as st
from utils import get_db, query_df, fmt_compact, MOBILE_CSS, DEALS, DB_PATH

st.set_page_config(page_title="Carvana ABS Dashboard", page_icon="\U0001F4CA", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

conn = get_db()  # Cached — only opens DB once, reused across all pages
if conn is None:
    st.error(f"Database not found at `{DB_PATH}`.")
    st.stop()


# ── Cached sidebar data (runs once per deal, not per page nav) ──

@st.cache_data(ttl=300)
def get_deal_list():
    df = query_df("SELECT DISTINCT deal FROM filings ORDER BY deal")
    return df["deal"].tolist() if not df.empty else list(DEALS.keys())


@st.cache_data(ttl=300)
def get_sidebar_metrics(deal):
    lc = query_df("SELECT COUNT(*) as n FROM loans WHERE deal = ?", (deal,))
    pp = query_df("SELECT COUNT(*) as n FROM pool_performance WHERE deal = ?", (deal,))
    ms = query_df("SELECT COUNT(*) as n FROM monthly_summary WHERE deal = ?", (deal,))
    return {
        "loans": int(lc.iloc[0]["n"]) if not lc.empty else 0,
        "pool": int(pp.iloc[0]["n"]) if not pp.empty else 0,
        "periods": int(ms.iloc[0]["n"]) if not ms.empty else 0,
    }


@st.cache_data(ttl=600)
def get_original_balance(deal):
    cfg = DEALS.get(deal, {})
    bal = cfg.get("original_pool_balance")
    if bal:
        return bal
    fp = query_df(
        "SELECT beginning_pool_balance FROM pool_performance WHERE deal = ? ORDER BY dist_date_iso LIMIT 1",
        (deal,))
    if not fp.empty and fp.iloc[0]["beginning_pool_balance"]:
        return fp.iloc[0]["beginning_pool_balance"]
    total = query_df("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal = ?", (deal,))
    if not total.empty and total.iloc[0]["s"]:
        return total.iloc[0]["s"]
    return 405_000_000


# ── Sidebar ──

deal_list = get_deal_list()

with st.sidebar:
    st.header("Carvana ABS")
    selected_deal = st.selectbox("Deal", deal_list, index=0)
    st.session_state["selected_deal"] = selected_deal

    deal_cfg = DEALS.get(selected_deal, {})
    if deal_cfg:
        st.caption(deal_cfg.get("entity_name", ""))

    ORIG_BAL = get_original_balance(selected_deal)
    st.session_state["ORIG_BAL"] = ORIG_BAL

    st.markdown("---")
    metrics = get_sidebar_metrics(selected_deal)
    if metrics["loans"]:
        st.metric("Loans", f"{metrics['loans']:,}")
    if metrics["periods"]:
        st.metric("Periods", metrics["periods"])
    if metrics["pool"]:
        st.metric("Pool Records", metrics["pool"])

# Main page
st.title("Carvana Auto Receivables Trust")
st.markdown("**ABS Performance Dashboard** | SEC EDGAR Data")
st.markdown(f"**Selected Deal:** {selected_deal}")
st.markdown("Use the sidebar to navigate between pages.")
