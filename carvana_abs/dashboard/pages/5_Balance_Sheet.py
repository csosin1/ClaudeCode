"""Trust Balance Sheet page."""
import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_lp, load_pool, get_deal, get_orig_bal, fmt_compact, MOBILE_CSS

st.set_page_config(page_title="Balance Sheet", layout="wide")
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

deal = get_deal()
ORIG_BAL = get_orig_bal()
lp = load_lp(deal)
pool_df = load_pool(deal)

st.header(f"Trust Balance Sheet — {deal}")

if lp.empty:
    st.info("No data yet.")
    st.stop()

assets = lp[["period", "total_balance", "dq_30_balance", "dq_60_balance",
              "dq_90_balance", "dq_120_plus_balance", "active_loans",
              "cum_chargeoffs", "cum_recoveries", "cum_net_losses"]].copy()
assets["performing"] = (assets["total_balance"] - assets["dq_30_balance"]
                        - assets["dq_60_balance"] - assets["dq_90_balance"]
                        - assets["dq_120_plus_balance"])

if not pool_df.empty:
    liab_cols = ["period", "note_balance_a1", "note_balance_a2", "note_balance_a3",
                 "note_balance_a4", "note_balance_b", "note_balance_c",
                 "note_balance_d", "note_balance_n",
                 "overcollateralization_amount", "reserve_account_balance"]
    liab = pool_df[[c for c in liab_cols if c in pool_df.columns]].copy()
    rated = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3",
                          "note_balance_a4","note_balance_b","note_balance_c","note_balance_d"]
             if c in liab.columns]
    liab["total_rated_debt"] = liab[rated].fillna(0).sum(axis=1)
    if "note_balance_n" in liab.columns:
        liab["total_all_debt"] = liab["total_rated_debt"] + liab["note_balance_n"].fillna(0)
    else:
        liab["total_all_debt"] = liab["total_rated_debt"]

    def period_to_ym(p):
        return str(p).replace("/", "-")[:7]
    def dist_to_ym(p):
        s = str(p).replace("/", "-")
        try:
            y, m = int(s[:4]), int(s[5:7])
            m -= 1
            if m == 0: m, y = 12, y - 1
            return f"{y:04d}-{m:02d}"
        except (ValueError, IndexError):
            return s[:7]

    assets["ym"] = assets["period"].apply(period_to_ym)
    liab["ym"] = liab["period"].apply(dist_to_ym)
    merged = assets.merge(liab.drop(columns=["period"]), on="ym", how="left")
else:
    merged = assets.copy()

# Assets table
st.markdown("### Assets")
ad = merged[["period", "performing", "dq_30_balance", "dq_60_balance",
             "dq_90_balance", "dq_120_plus_balance", "total_balance",
             "cum_chargeoffs", "cum_recoveries", "cum_net_losses"]].copy()
ad.columns = ["Period", "Performing", "30d DQ", "60d DQ", "90d DQ",
              "120+ DQ", "Total Pool", "Cum Gross Loss", "Cum Recovery", "Cum Net Loss"]
af = ad.copy()
for c in af.columns[1:]:
    af[c] = af[c].apply(lambda x: fmt_compact(x) if pd.notna(x) and x != 0 else "-")
st.dataframe(af, use_container_width=True, hide_index=True, height=400)

# Liabilities table
if "total_rated_debt" in merged.columns:
    st.markdown("### Liabilities & Equity")
    lcols = ["period"]
    lnames = ["Period"]
    for nc in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
               "note_balance_b","note_balance_c","note_balance_d"]:
        if nc in merged.columns:
            lcols.append(nc)
            lnames.append(nc.replace("note_balance_","").upper())
    lcols += ["total_rated_debt"]
    lnames += ["Total Debt"]
    if "overcollateralization_amount" in merged.columns:
        lcols += ["overcollateralization_amount"]
        lnames += ["OC"]
    if "reserve_account_balance" in merged.columns:
        lcols += ["reserve_account_balance"]
        lnames += ["Reserve"]
    ld = merged[lcols].copy()
    ld.columns = lnames
    lf = ld.copy()
    for c in lf.columns[1:]:
        lf[c] = lf[c].apply(lambda x: fmt_compact(x) if pd.notna(x) and x != 0 else "-")
    st.dataframe(lf, use_container_width=True, hide_index=True, height=400)
