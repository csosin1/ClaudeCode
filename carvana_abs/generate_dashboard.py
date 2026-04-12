#!/usr/bin/env python3
"""Generate static HTML dashboard using raw Plotly.js (no Python Plotly serialization)."""

import os, sys, sqlite3, json, logging
from datetime import datetime
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
os.makedirs(OUT_DIR, exist_ok=True)

# Deals to include in the dashboard — all deals with ingested data
DASHBOARD_DEALS = [
    "2020-P1",
    "2021-N1", "2021-N2", "2021-N3", "2021-N4", "2021-P1", "2021-P2",
    "2022-P1", "2022-P2", "2022-P3",
    "2024-P2", "2024-P3", "2024-P4",
    "2025-P2", "2025-P3", "2025-P4",
]
PRIME_DEALS = [d for d in DASHBOARD_DEALS if "-P" in d]
NONPRIME_DEALS = [d for d in DASHBOARD_DEALS if "-N" in d]
COLORS = ["#1976D2","#D32F2F","#388E3C","#FF9800","#7B1FA2",
          "#00BCD4","#795548","#E91E63","#607D8B","#CDDC39","#FF5722","#3F51B5"]
_chart_id = 0


def q(sql, params=()):
    conn = sqlite3.connect(ACTIVE_DB)
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass
    return df


def nd(d):
    if not d: return d
    d = str(d).strip()
    for sep in ["-", "/"]:
        p = d.split(sep)
        if len(p) == 3 and len(p[0]) <= 2 and len(p[2]) == 4:
            return f"{p[2]}{sep}{p[0].zfill(2)}{sep}{p[1].zfill(2)}"
    return d


def fm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "-"
    if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
    if abs(v) >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def chart(traces, layout, height=350):
    """Generate a Plotly.js chart div using raw JSON data."""
    global _chart_id
    _chart_id += 1
    cid = f"c{_chart_id}"
    traces_json = json.dumps(traces)
    layout["margin"] = {"l": 70, "r": 15, "t": 40, "b": 50}
    layout["height"] = height
    layout["template"] = "plotly_white"
    layout["font"] = {"size": 11}
    layout.setdefault("xaxis", {})["tickangle"] = -45
    layout["xaxis"]["automargin"] = True
    layout.setdefault("yaxis", {})["automargin"] = True
    layout_json = json.dumps(layout)
    return f'<div id="{cid}" style="width:100%;height:{height}px;background:white;border-radius:8px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)"></div>\n<script>Plotly.newPlot("{cid}",{traces_json},{layout_json},{{displayModeBar:false,responsive:true}});</script>\n'


def table_html(df, cls=""):
    cls_attr = f' class="{cls}"' if cls else ""
    rows = "".join(f"<th>{c}</th>" for c in df.columns)
    header = f"<tr>{rows}</tr>"
    body = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{row[c]}</td>" for c in df.columns)
        body += f"<tr>{cells}</tr>"
    return f'<div class="tbl"><table{cls_attr}><thead>{header}</thead><tbody>{body}</tbody></table></div>'


def get_orig_bal(deal):
    """Return the deal's original cutoff pool balance.

    Priority:
      1. KNOWN override — deals whose first servicer cert predates our cache.
      2. MAX(beginning_pool_balance) from pool_performance. Pool balance is
         monotonically decreasing, so the max across all periods equals the
         earliest "Beginning Pool Balance" line item — which is the cutoff
         balance for any deal whose first 10-D we ingested.
      3. SUM(original_loan_amount) from the loan tape — last resort; overstates
         by a few % because it's the sum of each loan's origination amount
         (pre-pooling amortization included), not the cutoff pool balance.
    """
    KNOWN = {"2020-P1": 405_000_000}
    if deal in KNOWN:
        return KNOWN[deal]
    fp = q("SELECT MAX(beginning_pool_balance) AS m FROM pool_performance "
           "WHERE deal=? AND beginning_pool_balance > 0", (deal,))
    if not fp.empty and fp.iloc[0]["m"] and fp.iloc[0]["m"] > 0:
        return float(fp.iloc[0]["m"])
    t = q("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal=?", (deal,))
    if not t.empty and t.iloc[0]["s"] and t.iloc[0]["s"] > 0:
        return float(t.iloc[0]["s"])
    return 405_000_000


def generate_deal_content(deal):
    """Generate all HTML content (metrics + tabs) for a single deal. Returns (metrics_html, tabs_content) or None."""
    global _chart_id

    ORIG_BAL = get_orig_bal(deal)
    lp = q("SELECT * FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
    if lp.empty:
        logger.warning(f"No monthly_summary data for {deal}, skipping.")
        return None
    lp["period"] = lp["reporting_period_end"].apply(nd)
    lp = lp.sort_values("period").reset_index(drop=True)

    pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date", (deal,))
    # Log data availability for debugging
    has_pool = not pool.empty
    has_wac_pp = has_pool and "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any()
    has_wac_ms = "weighted_avg_coupon" in lp.columns and lp["weighted_avg_coupon"].notna().any()
    has_note_int = has_pool and "total_note_interest" in pool.columns and pool["total_note_interest"].notna().any()
    has_note_bal = has_pool and "aggregate_note_balance" in pool.columns and (pool["aggregate_note_balance"].fillna(0) > 0).any()
    logger.info(f"[{deal}] Data: pool_perf={has_pool}, wac_pp={has_wac_pp}, wac_ms={has_wac_ms}, "
                f"note_interest={has_note_int}, note_balance={has_note_bal}")
    if not pool.empty:
        pool["period"] = pool["distribution_date"].apply(nd)
        pool = pool.sort_values("period").reset_index(drop=True)

    # Cumulative columns
    lp["cum_co"] = lp["period_chargeoffs"].cumsum()
    lp["cum_rec"] = lp["period_recoveries"].cumsum()
    lp["cum_net"] = lp["cum_co"] - lp["cum_rec"]
    lp["loss_rate"] = lp["cum_net"] / ORIG_BAL
    lp["dq_rate"] = lp["total_dq_balance"] / lp["total_balance"]
    lp["dq30r"] = lp["dq_30_balance"] / lp["total_balance"]
    lp["dq60r"] = lp["dq_60_balance"] / lp["total_balance"]
    lp["dq90r"] = lp["dq_90_balance"] / lp["total_balance"]
    lp["dq120r"] = lp["dq_120_plus_balance"] / lp["total_balance"]
    lp["net_loss"] = lp["period_chargeoffs"] - lp["period_recoveries"]

    # For cash waterfall, we need pool_performance data to compute note paydowns
    # and estimate note interest. Without it, we can only show collections/losses.
    note_cols = ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                 "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
    if not pool.empty:
        avail_notes = [c for c in note_cols if c in pool.columns]
        if avail_notes:
            pool["total_notes"] = pool[avail_notes].fillna(0).sum(axis=1)
            pool["note_principal_paid"] = -pool["total_notes"].diff().fillna(0)
            pool["note_principal_paid"] = pool["note_principal_paid"].clip(lower=0)
            # Estimate note interest: WAC of pool is ~8%, note WAC is roughly 1-2% for investment grade
            # Use a conservative estimate: total_notes * 0.02 / 12 (2% annual blended coupon)
            pool["est_note_interest"] = pool["total_notes"] * 0.02 / 12

    lp["cum_rec_rate"] = lp["cum_rec"] / lp["cum_co"].replace(0, float("nan"))

    x = lp["period"].tolist()
    last = lp.iloc[-1]
    sections = {}

    # ── POOL SUMMARY ──
    # Use compact y-axis labels ($100M instead of $100,000,000) and same x-axis for all 3 charts
    bal_in_millions = [round(v / 1e6, 1) for v in lp["total_balance"].tolist()]
    h = chart([{"x": x, "y": bal_in_millions, "type": "scatter", "fill": "tozeroy", "name": "Balance"}],
              {"title": "Remaining Pool Balance ($M)", "yaxis": {"ticksuffix": "M", "tickprefix": "$"}, "hovermode": "x unified"})
    h += chart([{"x": x, "y": [int(v) for v in lp["active_loans"].tolist()], "type": "scatter", "name": "Loans"}],
               {"title": "Active Loan Count", "hovermode": "x unified"})
    # ── Rate Curves: Collateral WAC and Cost of Debt ──
    # 1) Collateral WAC: prefer pool_performance, fall back to monthly_summary pre-computed WAC
    wac = pd.DataFrame()
    if not pool.empty and "weighted_avg_apr" in pool.columns:
        wac = pool.dropna(subset=["weighted_avg_apr"])[["period", "weighted_avg_apr"]].copy()
    if wac.empty and "weighted_avg_coupon" in lp.columns:
        wac_ms = lp.dropna(subset=["weighted_avg_coupon"])[["period", "weighted_avg_coupon"]].copy()
        if not wac_ms.empty:
            wac_ms = wac_ms.rename(columns={"weighted_avg_coupon": "weighted_avg_apr"})
            wac = wac_ms
    # Fallback: flat line from avg loan interest rate
    if wac.empty:
        avg_rate = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
        if not avg_rate.empty and avg_rate.iloc[0]["r"]:
            flat_wac = float(avg_rate.iloc[0]["r"])
            wac = pd.DataFrame({"period": lp["period"], "weighted_avg_apr": flat_wac})
            logger.info(f"[{deal}] Using flat-line WAC from loan avg: {flat_wac:.4%}")
    # 2) Cost of Debt: weighted avg of note coupon rates × note balances
    cod = pd.DataFrame()
    try:
        notes_df = q("SELECT class, coupon_rate, original_balance FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
    except Exception:
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()

    # Merged Method 1+2: use actual interest data when available, weighted coupon fallback per period
    m1_count = 0
    m2_count = 0
    if not pool.empty:
        # Build normalized rate lookup from notes for Method 2 fallback
        norm_rate_lookup = {}
        if not notes_df.empty:
            for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                norm_rate_lookup[norm] = rate
        bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                    "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                    "D": "note_balance_d", "N": "note_balance_n"}
        # Forward-fill note balance columns
        for col in bal_cols.values():
            if col in pool.columns:
                pool[col] = pool[col].ffill()

        has_ni_col = "total_note_interest" in pool.columns
        has_nb_col = "aggregate_note_balance" in pool.columns
        cod_rows = []
        filtered_count = 0
        for _, row in pool.iterrows():
            # Method 1: actual interest / actual balance (best)
            used_m1 = False
            if has_ni_col and has_nb_col:
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(ni) and pd.notna(nb) and nb > 0 and ni > 0:
                    val = float(ni) / float(nb) * 12
                    if 0 < val < 0.25:
                        cod_rows.append({"period": row["period"], "cost_of_debt": val})
                        m1_count += 1
                        used_m1 = True
                    else:
                        logger.debug(f"  [{deal}] Period {row.get('period')}: CoD value {val:.4%} filtered (outside 0-25% range), ni={ni}, nb={nb}")
                        filtered_count += 1

            # Method 2 fallback: weighted coupon rates × note balances
            if not used_m1 and norm_rate_lookup:
                weighted_sum = 0.0
                total_bal = 0.0
                for cls, col in bal_cols.items():
                    if col in pool.columns and cls in norm_rate_lookup:
                        bal = row.get(col)
                        if pd.notna(bal) and float(bal) > 0:
                            weighted_sum += norm_rate_lookup[cls] * float(bal)
                            total_bal += float(bal)
                if total_bal > 0:
                    cod_rows.append({"period": row["period"], "cost_of_debt": weighted_sum / total_bal})
                    m2_count += 1

        if filtered_count > 0:
            logger.warning(f"[{deal}] Filtered {filtered_count} CoD values outside (0, 25%) range")
        if cod_rows:
            cod = pd.DataFrame(cod_rows)
            logger.info(f"[{deal}] Merged CoD: {m1_count} periods from actual interest, {m2_count} from weighted coupons")

    # Method 3: flat line from notes table — works even if pool_performance is empty
    if len(cod) < 3 and not notes_df.empty:
        flat_rate = None
        if "original_balance" in notes_df.columns and notes_df["original_balance"].notna().any():
            ob = notes_df["original_balance"].fillna(0)
            if ob.sum() > 0:
                flat_rate = float((notes_df["coupon_rate"] * ob).sum() / ob.sum())
        if flat_rate is None:
            flat_rate = float(notes_df["coupon_rate"].mean())
        if flat_rate and flat_rate > 0:
            # Use monthly_summary periods if pool_performance is empty
            periods = pool["period"] if not pool.empty else lp["period"]
            cod = pd.DataFrame({"period": periods, "cost_of_debt": flat_rate})
            logger.info(f"[{deal}] Using flat-line CoD from notes: {flat_rate:.4%}")

    # Method 4 (rough estimate): derive from avg loan interest rate if nothing else works
    if len(cod) < 3:
        avg_rate_q = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
        if not avg_rate_q.empty and avg_rate_q.iloc[0]["r"]:
            avg_loan_rate = float(avg_rate_q.iloc[0]["r"])
            rough_cod = avg_loan_rate * 0.4  # rough proxy: funding cost ~ 40% of loan yield
            periods = pool["period"] if not pool.empty else lp["period"]
            cod = pd.DataFrame({"period": periods, "cost_of_debt": rough_cod})
            logger.info(f"[{deal}] Using rough CoD estimate from loan avg rate ({avg_loan_rate:.4%} * 0.4 = {rough_cod:.4%})")

    # 3) Render separate charts for consumer rate and cost of debt
    if not wac.empty:
        h += chart([{"x": wac["period"].tolist(), "y": wac["weighted_avg_apr"].tolist(),
                     "type": "scatter", "line": {"color": "#1976D2"}}],
                   {"title": "Avg Consumer Rate", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
                    "xaxis": {"range": [x[0], x[-1]], "tickangle": -45, "automargin": True}})
    else:
        logger.warning(f"[{deal}] No consumer rate (WAC) data available")
    if not cod.empty:
        cod_min, cod_max = cod["cost_of_debt"].min(), cod["cost_of_debt"].max()
        logger.info(f"[{deal}] CoD range: {cod_min:.4%} - {cod_max:.4%} (n={len(cod)})")
        h += chart([{"x": cod["period"].tolist(), "y": cod["cost_of_debt"].tolist(),
                     "type": "scatter", "line": {"color": "#D32F2F"}}],
                   {"title": "Avg Trust Cost of Debt", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
                    "xaxis": {"range": [x[0], x[-1]], "tickangle": -45, "automargin": True}})
    else:
        logger.warning(f"[{deal}] No cost of debt data available")
    sections["Pool Summary"] = h

    # ── DELINQUENCIES ──
    h = chart([
        {"x": x, "y": lp["dq30r"].tolist(), "name": "30d", "stackgroup": "dq", "line": {"color": "#FFC107"}},
        {"x": x, "y": lp["dq60r"].tolist(), "name": "60d", "stackgroup": "dq", "line": {"color": "#FF9800"}},
        {"x": x, "y": lp["dq90r"].tolist(), "name": "90d", "stackgroup": "dq", "line": {"color": "#FF5722"}},
        {"x": x, "y": lp["dq120r"].tolist(), "name": "120+d", "stackgroup": "dq", "line": {"color": "#D32F2F"}},
    ], {"title": "Delinquency Rates (% of Pool)", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    if not pool.empty and "delinquency_trigger_level" in pool.columns:
        trig = pool.dropna(subset=["delinquency_trigger_level", "delinquency_trigger_actual"])
        if not trig.empty:
            h += chart([
                {"x": trig["period"].tolist(), "y": trig["delinquency_trigger_level"].tolist(), "name": "Trigger", "line": {"dash": "dash", "color": "red"}},
                {"x": trig["period"].tolist(), "y": trig["delinquency_trigger_actual"].tolist(), "name": "Actual", "line": {"color": "blue"}},
            ], {"title": "60+ DQ vs Trigger Level", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    dq_tbl = pd.DataFrame({
        "Bucket": ["30d","60d","90d","120+d","Total"],
        "Count": [int(last["dq_30_count"]),int(last["dq_60_count"]),int(last["dq_90_count"]),int(last["dq_120_plus_count"]),int(last["total_dq_count"])],
        "Balance": [fm(last["dq_30_balance"]),fm(last["dq_60_balance"]),fm(last["dq_90_balance"]),fm(last["dq_120_plus_balance"]),fm(last["total_dq_balance"])],
        "% Pool": [f"{last['dq30r']:.2%}",f"{last['dq60r']:.2%}",f"{last['dq90r']:.2%}",f"{last['dq120r']:.2%}",f"{last['dq_rate']:.2%}"],
    })
    h += "<h3>Latest Period</h3>" + table_html(dq_tbl)
    sections["Delinquencies"] = h

    # ── LOSSES ──
    h = chart([{"x": x, "y": lp["loss_rate"].tolist(), "type": "scatter", "fill": "tozeroy", "line": {"color": "#D32F2F"}}],
              {"title": f"Cumulative Net Loss Rate (% of {fm(ORIG_BAL)})", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    h += chart([
        {"x": x, "y": lp["cum_co"].tolist(), "name": "Gross Chargeoffs", "line": {"color": "#D32F2F"}},
        {"x": x, "y": lp["cum_rec"].tolist(), "name": "Recoveries", "line": {"color": "#4CAF50"}},
        {"x": x, "y": lp["cum_net"].tolist(), "name": "Net Losses", "line": {"color": "#FF9800", "dash": "dash"}},
    ], {"title": "Cumulative Gross Losses vs Recoveries", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
    rr = lp.dropna(subset=["cum_rec_rate"])
    if not rr.empty:
        h += chart([{"x": rr["period"].tolist(), "y": rr["cum_rec_rate"].tolist(), "line": {"color": "#4CAF50"}}],
                   {"title": "Cumulative Recovery Rate", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
    h += chart([
        {"x": x, "y": lp["period_chargeoffs"].tolist(), "name": "Chargeoffs", "type": "bar", "marker": {"color": "#D32F2F"}},
        {"x": x, "y": lp["period_recoveries"].tolist(), "name": "Recoveries", "type": "bar", "marker": {"color": "#4CAF50"}},
    ], {"title": "Monthly Chargeoffs vs Recoveries", "barmode": "group", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    # Loss by credit score
    lbs = q("""SELECT l.obligor_credit_score as segment, COUNT(*) as lc, SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.obligor_credit_score IS NOT NULL GROUP BY l.obligor_credit_score""", (deal,))
    if not lbs.empty:
        lbs["bkt"] = pd.cut(lbs["segment"], bins=[0,580,620,660,700,740,780,820,900],
                            labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
        b = lbs.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]; b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Score":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
            "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),"Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        h += "<h3>Losses by Credit Score</h3>" + table_html(d)

    # Loss by rate
    lbr = q("""SELECT l.original_interest_rate as segment, COUNT(*) as lc, SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.original_interest_rate IS NOT NULL GROUP BY l.original_interest_rate""", (deal,))
    if not lbr.empty:
        lbr["bkt"] = pd.cut(lbr["segment"], bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                            labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
        b = lbr.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]; b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Rate":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
            "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),"Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        h += "<h3>Losses by Interest Rate</h3>" + table_html(d)
    sections["Losses"] = h

    # ── CASH WATERFALL ──
    h = ""

    # Collections table from loan-level data
    wf = lp[["period","interest_collected","principal_collected","period_recoveries",
             "est_servicing_fee","period_chargeoffs","net_loss"]].copy()
    wf.columns = ["Period","Interest","Principal","Recoveries","Svc Fee","Chargeoffs","Net Loss"]
    sums = wf.select_dtypes(include="number").sum()
    sr = pd.DataFrame([["TOTAL"]+sums.tolist()], columns=wf.columns)
    wf_all = pd.concat([wf, sr], ignore_index=True)
    wf_fmt = wf_all.copy()
    for c in wf_fmt.columns[1:]:
        wf_fmt[c] = wf_all[c].apply(lambda x: fm(x) if pd.notna(x) else "")
    h += "<h3>Monthly Collections & Losses</h3>" + table_html(wf_fmt)

    # Cumulative cash flow chart
    cum_int = lp["interest_collected"].cumsum()
    cum_prin = lp["principal_collected"].cumsum()
    cum_svc = lp["est_servicing_fee"].cumsum()
    h += chart([
        {"x": x, "y": cum_int.tolist(), "name": "Cum Interest", "line": {"color": "#1976D2"}},
        {"x": x, "y": cum_prin.tolist(), "name": "Cum Principal", "line": {"color": "#388E3C"}},
        {"x": x, "y": lp["cum_co"].tolist(), "name": "Cum Chargeoffs", "line": {"color": "#D32F2F"}},
        {"x": x, "y": lp["cum_rec"].tolist(), "name": "Cum Recoveries", "line": {"color": "#4CAF50"}},
        {"x": x, "y": cum_svc.tolist(), "name": "Cum Servicing Fee", "line": {"color": "#FF9800", "dash": "dash"}},
    ], {"title": "Cumulative Cash Flows", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    # Actual waterfall from servicer certificate (where available)
    if not pool.empty and "residual_cash" in pool.columns and pool["residual_cash"].notna().any():
        pool_x = pool["period"].tolist()
        h += "<h3>Cash Waterfall (from Servicer Certificate)</h3>"

        # Build waterfall table with actual filing data
        wf_cols = ["period"]
        wf_names = ["Period"]
        for col, name in [("total_deposited", "Total Deposited"), ("available_funds", "Available Funds"),
                          ("actual_servicing_fee", "Servicing Fee"), ("total_note_interest", "Note Interest"),
                          ("regular_pda", "Principal Dist"), ("residual_cash", "Residual (to Equity)")]:
            if col in pool.columns and pool[col].notna().any():
                wf_cols.append(col)
                wf_names.append(name)
        if len(wf_cols) > 1:
            wf_pool = pool[wf_cols].copy()
            wf_pool.columns = wf_names
            # Add totals row
            sums_p = wf_pool.select_dtypes(include="number").sum()
            sr_p = pd.DataFrame([["TOTAL"] + sums_p.tolist()], columns=wf_pool.columns)
            wf_pool_all = pd.concat([wf_pool, sr_p], ignore_index=True)
            wf_pool_fmt = wf_pool_all.copy()
            for c in wf_pool_fmt.columns[1:]:
                wf_pool_fmt[c] = wf_pool_all[c].apply(lambda x: fm(x) if pd.notna(x) and x != 0 else "-")
            h += table_html(wf_pool_fmt)

        # Residual cash chart
        res_data = pool[pool["residual_cash"].notna()]
        if not res_data.empty:
            cum_res = res_data["residual_cash"].cumsum()
            cum_res_pct = cum_res / ORIG_BAL
            h += chart([{"x": res_data["period"].tolist(), "y": cum_res_pct.tolist(),
                         "type": "scatter", "fill": "tozeroy", "line": {"color": "#388E3C"}}],
                       {"title": "Cumulative Cash to Residual (% of Original Balance)",
                        "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})

    # Debt table from pool_performance (where available)
    if not pool.empty and "total_notes" in pool.columns:
        pool_x = pool["period"].tolist()
        h += "<h3>Debt & Equity (from Servicer Certificate)</h3>"

        # Build debt paydown table
        debt_cols = ["period"]
        debt_names = ["Period"]
        for nc in note_cols:
            if nc in pool.columns and pool[nc].notna().any():
                debt_cols.append(nc)
                debt_names.append(nc.replace("note_balance_","").upper())
        if "total_notes" in pool.columns:
            debt_cols.append("total_notes")
            debt_names.append("Total Debt")
        if "overcollateralization_amount" in pool.columns:
            debt_cols.append("overcollateralization_amount")
            debt_names.append("OC")
        if "reserve_account_balance" in pool.columns:
            debt_cols.append("reserve_account_balance")
            debt_names.append("Reserve")
        dt = pool[debt_cols].copy()
        dt.columns = debt_names
        dt_fmt = dt.copy()
        for c in dt_fmt.columns[1:]:
            dt_fmt[c] = dt[c].apply(lambda x: fm(x) if pd.notna(x) and x != 0 else "-")
        h += table_html(dt_fmt)

        # Debt paydown chart
        h += chart([
            {"x": pool_x, "y": pool["total_notes"].tolist(), "name": "Total Debt", "fill": "tozeroy", "line": {"color": "#7B1FA2"}},
        ], {"title": "Outstanding Debt Over Time", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    sections["Cash Waterfall"] = h

    # ── RECOVERY ──
    rec = q("""SELECT s.asset_number, s.chargeoff_period, s.total_chargeoff,
               s.first_recovery_period, s.total_recovery, l.obligor_credit_score
            FROM loan_loss_summary s LEFT JOIN loans l ON s.deal=l.deal AND s.asset_number=l.asset_number
            WHERE s.deal=? AND s.total_chargeoff > 0""", (deal,))
    h = ""
    if not rec.empty:
        from datetime import datetime as dt
        def pd_dt(d):
            if not d: return None
            for f in ["%m-%d-%Y","%m/%d/%Y","%Y-%m-%d"]:
                try: return dt.strptime(str(d).strip(),f)
                except: continue
            return None
        rec["co_dt"] = rec["chargeoff_period"].apply(pd_dt)
        rec["rec_dt"] = rec["first_recovery_period"].apply(pd_dt)
        rec["has_rec"] = rec["total_recovery"].notna() & (rec["total_recovery"] > 0)
        rec["months"] = rec.apply(lambda r: ((r["rec_dt"].year-r["co_dt"].year)*12+r["rec_dt"].month-r["co_dt"].month) if pd.notna(r["rec_dt"]) and pd.notna(r["co_dt"]) else None, axis=1)
        tc=len(rec); wr=int(rec["has_rec"].sum())
        ar=rec.loc[rec["has_rec"],"total_recovery"].sum()/rec["total_chargeoff"].sum() if rec["total_chargeoff"].sum()>0 else 0
        mm=rec.loc[rec["has_rec"],"months"].median()
        tca=rec["total_chargeoff"].sum(); tra=rec.loc[rec["has_rec"],"total_recovery"].sum()
        h += f'<div class="metrics"><div class="metric"><div class="mv">{tc:,}</div><div class="ml">Charged-Off Loans</div></div>'
        h += f'<div class="metric"><div class="mv">{wr:,} ({wr/tc:.0%})</div><div class="ml">With Recovery</div></div>'
        h += f'<div class="metric"><div class="mv">{ar:.1%}</div><div class="ml">Recovery Rate</div></div>'
        h += f'<div class="metric"><div class="mv">{mm:.0f}mo</div><div class="ml">Median Time</div></div>'
        h += f'<div class="metric"><div class="mv">{fm(tca)}</div><div class="ml">Total Chargeoffs</div></div>'
        h += f'<div class="metric"><div class="mv">{fm(tra)}</div><div class="ml">Total Recovered</div></div></div>'
        rw = rec[rec["has_rec"] & rec["months"].notna()]
        if not rw.empty:
            import numpy as np
            counts, edges = np.histogram(rw["months"].values, bins=30)
            centers = [(edges[i]+edges[i+1])/2 for i in range(len(counts))]
            h += chart([{"x": centers, "y": counts.tolist(), "type": "bar", "marker": {"color": "#1976D2"}}],
                       {"title": "Months to First Recovery", "hovermode": "x unified"})

        # Recovery rate by credit score
        rec_fico = rec[rec["obligor_credit_score"].notna()].copy()
        if not rec_fico.empty:
            rec_fico["bkt"] = pd.cut(rec_fico["obligor_credit_score"],
                bins=[0,580,620,660,700,740,780,820,900],
                labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
            b = rec_fico.groupby("bkt", observed=True).agg(
                loans=("asset_number","count"),
                chargeoffs=("total_chargeoff","sum"),
                recoveries=("total_recovery", lambda x: x.fillna(0).sum()),
            ).reset_index()
            b["rec_rate"] = b["recoveries"] / b["chargeoffs"].replace(0, float("nan"))
            # Bar chart
            h += chart([
                {"x": b["bkt"].tolist(), "y": [round(v,4) if pd.notna(v) else 0 for v in b["rec_rate"]], "type": "bar", "marker": {"color": "#4CAF50"}},
            ], {"title": "Recovery Rate by Credit Score", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
            # Table
            tbl = pd.DataFrame({
                "Score": b["bkt"],
                "Charged-Off Loans": b["loans"].apply(lambda x: f"{x:,}"),
                "Total Chargeoffs": b["chargeoffs"].apply(fm),
                "Total Recovered": b["recoveries"].apply(fm),
                "Recovery Rate": b["rec_rate"].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "-"),
            })
            h += table_html(tbl)

        # Recovery rate by interest rate
        rec_rate_data = q("""SELECT s.asset_number, s.total_chargeoff, s.total_recovery,
                             l.original_interest_rate
                          FROM loan_loss_summary s
                          LEFT JOIN loans l ON s.deal=l.deal AND s.asset_number=l.asset_number
                          WHERE s.deal=? AND s.total_chargeoff > 0
                          AND l.original_interest_rate IS NOT NULL""", (deal,))
        if not rec_rate_data.empty:
            rec_rate_data["bkt"] = pd.cut(rec_rate_data["original_interest_rate"],
                bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
            b = rec_rate_data.groupby("bkt", observed=True).agg(
                loans=("asset_number","count"),
                chargeoffs=("total_chargeoff","sum"),
                recoveries=("total_recovery", lambda x: x.fillna(0).sum()),
            ).reset_index()
            b["rec_rate"] = b["recoveries"] / b["chargeoffs"].replace(0, float("nan"))
            h += chart([
                {"x": b["bkt"].tolist(), "y": [round(v,4) if pd.notna(v) else 0 for v in b["rec_rate"]], "type": "bar", "marker": {"color": "#388E3C"}},
            ], {"title": "Recovery Rate by Interest Rate", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
            tbl = pd.DataFrame({
                "Rate": b["bkt"],
                "Charged-Off Loans": b["loans"].apply(lambda x: f"{x:,}"),
                "Total Chargeoffs": b["chargeoffs"].apply(fm),
                "Total Recovered": b["recoveries"].apply(fm),
                "Recovery Rate": b["rec_rate"].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "-"),
            })
            h += table_html(tbl)
    sections["Recovery"] = h

    # ── NOTES & OC ──
    h = ""
    if not pool.empty:
        nc = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                           "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
              if c in pool.columns and pool[c].notna().any()]
        if nc:
            traces = []
            for c in nc:
                traces.append({"x": pool["period"].tolist(), "y": pool[c].fillna(0).tolist(),
                               "name": c.replace("note_balance_","").upper(), "stackgroup": "notes"})
            h += chart(traces, {"title": "Note Balances", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
        oc = pool.dropna(subset=["overcollateralization_amount"], how="all")
        if not oc.empty:
            traces = []
            if "overcollateralization_amount" in oc.columns and oc["overcollateralization_amount"].notna().any():
                traces.append({"x": oc["period"].tolist(), "y": oc["overcollateralization_amount"].tolist(), "name": "OC"})
            if "reserve_account_balance" in oc.columns and oc["reserve_account_balance"].notna().any():
                traces.append({"x": oc["period"].tolist(), "y": oc["reserve_account_balance"].tolist(), "name": "Reserve"})
            if traces:
                h += chart(traces, {"title": "OC & Reserve Account", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
    sections["Notes & OC"] = h

    # ── DOCUMENTS ──
    h = ""
    try:
        # Query servicer certificates from filings table
        certs = q("SELECT filing_date, servicer_cert_url, accession_number FROM filings "
                  "WHERE deal=? AND servicer_cert_url IS NOT NULL ORDER BY filing_date DESC", (deal,))
        if not certs.empty:
            h += "<h3>Servicer Certificates</h3>"
            cert_rows = []
            for _, cert_row in certs.iterrows():
                fd = cert_row["filing_date"]
                cert_url = cert_row["servicer_cert_url"]
                try:
                    dt_obj = datetime.strptime(str(fd).strip()[:10], "%Y-%m-%d")
                    date_display = dt_obj.strftime("%b %Y")
                    date_slug = dt_obj.strftime("%Y-%m")
                except (ValueError, TypeError):
                    date_display = str(fd)[:10] if fd else "Unknown"
                    date_slug = str(fd)[:7] if fd else "unknown"
                # Link directly to SEC EDGAR. We used to try serving locally
                # generated PDFs (docs/<deal>/<file>.pdf), but EDGAR servicer
                # certificates are image-based — the body is a set of JPG page
                # scans referenced by relative URL with a hidden OCR text layer.
                # Rendering that HTML with weasyprint produced a PDF containing
                # only the hidden text + document header (looked like a bare
                # exhibit reference with no real content). SEC serves the JPGs
                # in place, so the canonical EDGAR URL renders correctly.
                link = f'<a href="{cert_url}" target="_blank" rel="noopener">SEC&nbsp;Filing</a>'
                cert_rows.append({"Date": date_display, "Download": link})
            cert_df = pd.DataFrame(cert_rows)
            h += table_html(cert_df, cls="compare")
    except Exception as e:
        logger.warning(f"[{deal}] Error building servicer cert links: {e}")

    # Prospectus & Annual Reports — link to SEC EDGAR search for the deal's CIK
    try:
        from carvana_abs.config import DEALS as DEAL_REGISTRY
        deal_info = DEAL_REGISTRY.get(deal, {})
        cik = deal_info.get("cik", "")
        entity = deal_info.get("entity_name", f"Carvana Auto Receivables Trust {deal}")
        if cik:
            h += "<h3>Prospectus &amp; Other Filings</h3>"
            edgar_base = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            filing_links = [
                {"Document": "All SEC Filings",
                 "Description": f"Complete filing history for {entity}",
                 "Link": f'<a href="{edgar_base}&type=&dateb=&owner=include&count=40" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Prospectus (424B)",
                 "Description": "Offering prospectus and supplements",
                 "Link": f'<a href="{edgar_base}&type=424B&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Annual Reports (10-K)",
                 "Description": "Annual reports filed with SEC",
                 "Link": f'<a href="{edgar_base}&type=10-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Current Reports (8-K)",
                 "Description": "Material event disclosures",
                 "Link": f'<a href="{edgar_base}&type=8-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
            ]
            h += table_html(pd.DataFrame(filing_links), cls="compare")
    except Exception as e:
        logger.warning(f"[{deal}] Error building prospectus links: {e}")

    if not h:
        h = "<p>No documents available for this deal.</p>"
    sections["Documents"] = h

    # Build metrics + tabs HTML for this deal
    metrics_html = f"""<div class="metrics">
<div class="metric"><div class="mv">{fm(ORIG_BAL)}</div><div class="ml">Original Balance</div></div>
<div class="metric"><div class="mv">{fm(last['total_balance'])}</div><div class="ml">Current Balance</div></div>
<div class="metric"><div class="mv">{last['total_balance']/ORIG_BAL:.1%}</div><div class="ml">Pool Factor</div></div>
<div class="metric"><div class="mv">{int(last['active_loans']):,}</div><div class="ml">Active Loans</div></div>
<div class="metric"><div class="mv">{last['loss_rate']:.2%}</div><div class="ml">Cum Loss Rate</div></div>
<div class="metric"><div class="mv">{last['dq_rate']:.2%}</div><div class="ml">30+ DQ Rate</div></div>
</div>"""

    # Build tab buttons and content
    deal_safe = deal.replace("-","_")
    tabs_html = ""; content_html = ""; first = True
    for name, body in sections.items():
        tid = f"{deal_safe}_{name.replace(' ','_').replace('&','and')}"
        tabs_html += f'<button class="tab{" active" if first else ""}" onclick="showTab(\'{tid}\',this)">{name}</button>\n'
        content_html += f'<div id="{tid}" class="tc" style="display:{"block" if first else "none"}">{body}</div>\n'
        first = False

    return metrics_html, f'<div class="tabs">{tabs_html}</div>\n{content_html}'


def generate_comparison_content(deals, title):
    """Generate comparison HTML (summary table + loss curve) for a group of deals."""
    h = ""

    # ── Summary Table ──
    rows = []
    for deal in deals:
        loan_stats = q("SELECT AVG(original_interest_rate) as avg_yield, AVG(obligor_credit_score) as avg_fico FROM loans WHERE deal=?", (deal,))
        avg_fico = loan_stats.iloc[0]["avg_fico"] if not loan_stats.empty and loan_stats.iloc[0]["avg_fico"] else None
        init_bal = get_orig_bal(deal)

        # ── Collateral WAC (init + current) ──
        # Prefer pool_performance.weighted_avg_apr, fall back to monthly_summary.weighted_avg_coupon
        init_wac = None
        curr_wac = None
        first_wac = q("SELECT weighted_avg_apr FROM pool_performance WHERE deal=? AND weighted_avg_apr IS NOT NULL ORDER BY distribution_date LIMIT 1", (deal,))
        last_wac = q("SELECT weighted_avg_apr FROM pool_performance WHERE deal=? AND weighted_avg_apr IS NOT NULL ORDER BY distribution_date DESC LIMIT 1", (deal,))
        if not first_wac.empty and first_wac.iloc[0]["weighted_avg_apr"]:
            init_wac = first_wac.iloc[0]["weighted_avg_apr"]
        if not last_wac.empty and last_wac.iloc[0]["weighted_avg_apr"]:
            curr_wac = last_wac.iloc[0]["weighted_avg_apr"]
        # monthly_summary fallback (pre-computed from loan-level data)
        if init_wac is None or curr_wac is None:
            wac_ms = q("SELECT weighted_avg_coupon FROM monthly_summary WHERE deal=? AND weighted_avg_coupon IS NOT NULL ORDER BY reporting_period_end", (deal,))
            if not wac_ms.empty:
                if init_wac is None and wac_ms.iloc[0]["weighted_avg_coupon"]:
                    init_wac = wac_ms.iloc[0]["weighted_avg_coupon"]
                if curr_wac is None and wac_ms.iloc[-1]["weighted_avg_coupon"]:
                    curr_wac = wac_ms.iloc[-1]["weighted_avg_coupon"]
        # Last resort: avg loan interest rate
        if init_wac is None or curr_wac is None:
            avg_rate = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
            if not avg_rate.empty and avg_rate.iloc[0]["r"]:
                flat = float(avg_rate.iloc[0]["r"])
                if init_wac is None:
                    init_wac = flat
                if curr_wac is None:
                    curr_wac = flat

        # ── Cost of Debt: compute full time series, take first/last ──
        init_cod = None
        curr_cod = None
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()

        # Build full CoD time series (same merged Method 1+2 as per-deal chart)
        pool_all = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date", (deal,))
        if not pool_all.empty:
            norm_rate_lookup = {}
            if not notes_df.empty:
                for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                    norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                    norm_rate_lookup[norm] = rate
            bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                        "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                        "D": "note_balance_d", "N": "note_balance_n"}
            for col in bal_cols.values():
                if col in pool_all.columns:
                    pool_all[col] = pool_all[col].ffill()
            has_ni = "total_note_interest" in pool_all.columns
            has_nb = "aggregate_note_balance" in pool_all.columns
            cod_series = []
            for _, row in pool_all.iterrows():
                # Method 1: actual interest ratio
                if has_ni and has_nb:
                    ni = row.get("total_note_interest")
                    nb = row.get("aggregate_note_balance")
                    if pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                        val = float(ni) / float(nb) * 12
                        if 0 < val < 0.25:
                            cod_series.append(val)
                            continue
                # Method 2: weighted coupon × balance
                if norm_rate_lookup:
                    w_sum, t_bal = 0.0, 0.0
                    for cls, col in bal_cols.items():
                        if col in pool_all.columns and cls in norm_rate_lookup:
                            bal = row.get(col)
                            if pd.notna(bal) and float(bal) > 0:
                                w_sum += norm_rate_lookup[cls] * float(bal)
                                t_bal += float(bal)
                    if t_bal > 0:
                        cod_series.append(w_sum / t_bal)
                        continue
                cod_series.append(None)

            # Take first and last non-None values
            valid = [(i, v) for i, v in enumerate(cod_series) if v is not None]
            if valid:
                init_cod = valid[0][1]
                curr_cod = valid[-1][1]
                logger.info(f"  [{deal}] Summary CoD from time series: init={init_cod:.4%}, curr={curr_cod:.4%} ({len(valid)} points)")

        # Fallback: flat rate from notes table
        if init_cod is None or curr_cod is None:
            if not notes_df.empty:
                try:
                    notes_ob = q("SELECT class, coupon_rate, original_balance FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
                except Exception:
                    notes_ob = notes_df
                flat = None
                if "original_balance" in notes_ob.columns and notes_ob["original_balance"].notna().any():
                    ob = notes_ob["original_balance"].fillna(0)
                    if ob.sum() > 0:
                        flat = float((notes_ob["coupon_rate"] * ob).sum() / ob.sum())
                if flat is None:
                    flat = float(notes_df["coupon_rate"].mean())
                if flat and flat > 0:
                    if init_cod is None:
                        init_cod = flat
                    if curr_cod is None:
                        curr_cod = flat

        # Fallback: rough estimate from avg loan interest rate
        if init_cod is None or curr_cod is None:
            avg_rate_fb = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
            if not avg_rate_fb.empty and avg_rate_fb.iloc[0]["r"]:
                rough = float(avg_rate_fb.iloc[0]["r"]) * 0.4
                if init_cod is None:
                    init_cod = rough
                if curr_cod is None:
                    curr_cod = rough

        # Pool factor from monthly_summary (more reliable than pool_performance)
        latest_ms = q("SELECT total_balance FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end DESC LIMIT 1", (deal,))
        latest_bal = latest_ms.iloc[0]["total_balance"] if not latest_ms.empty and latest_ms.iloc[0]["total_balance"] else None
        pool_factor = latest_bal / init_bal if (latest_bal and init_bal and init_bal > 0) else None

        equity = q("SELECT SUM(residual_cash) as total_residual FROM pool_performance WHERE deal=? AND residual_cash IS NOT NULL", (deal,))
        total_residual = equity.iloc[0]["total_residual"] if not equity.empty and equity.iloc[0]["total_residual"] else 0
        equity_pct = total_residual / init_bal if (init_bal and init_bal > 0) else None

        # Cumulative loss rate
        loss = q("SELECT SUM(period_chargeoffs) as co, SUM(period_recoveries) as rec FROM monthly_summary WHERE deal=?", (deal,))
        cum_loss_rate = None
        if not loss.empty and loss.iloc[0]["co"] is not None and init_bal and init_bal > 0:
            net = (loss.iloc[0]["co"] or 0) - (loss.iloc[0]["rec"] or 0)
            cum_loss_rate = net / init_bal

        rows.append({
            "Deal": deal,
            "Avg FICO": f"{avg_fico:.0f}" if avg_fico else "-",
            "Initial Avg Consumer Rate": f"{init_wac:.2%}" if init_wac is not None else None,
            "Current Avg Consumer Rate": f"{curr_wac:.2%}" if curr_wac is not None else None,
            "Initial Avg Trust Cost of Debt": f"{init_cod:.2%}" if init_cod is not None else None,
            "Current Avg Trust Cost of Debt": f"{curr_cod:.2%}" if curr_cod is not None else None,
            "Init Balance": fm(init_bal),
            "Pool Factor": f"{pool_factor:.1%}" if pool_factor is not None else "-",
            "Cum Loss": f"{cum_loss_rate:.2%}" if cum_loss_rate is not None else "-",
            "Equity Dist": f"{equity_pct:.2%}" if equity_pct is not None else "-",
        })

    if rows:
        summary_df = pd.DataFrame(rows)
        # Drop columns where ALL values are None (no deal has data for that metric)
        for col in ["Initial Avg Consumer Rate", "Current Avg Consumer Rate",
                     "Initial Avg Trust Cost of Debt", "Current Avg Trust Cost of Debt"]:
            if col in summary_df.columns and summary_df[col].isna().all():
                summary_df = summary_df.drop(columns=[col])
                logger.warning(f"[{title}] Dropped column '{col}' — no data for any deal")
            elif col in summary_df.columns:
                summary_df[col] = summary_df[col].fillna("-")
        h += f"<h3>{title} — Summary</h3>" + table_html(summary_df, cls="compare")

    # ── Cumulative Loss Curve (by deal age in months) ──
    traces = []
    for i, deal in enumerate(deals):
        ms = q("SELECT reporting_period_end, period_chargeoffs, period_recoveries FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
        if ms.empty:
            continue
        ms["period"] = ms["reporting_period_end"].apply(nd)
        ms = ms.sort_values("period").reset_index(drop=True)
        orig_bal = get_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue
        ms["cum_net"] = (ms["period_chargeoffs"].fillna(0) - ms["period_recoveries"].fillna(0)).cumsum()
        ms["loss_rate"] = ms["cum_net"] / orig_bal
        months = list(range(1, len(ms) + 1))
        traces.append({
            "x": months,
            "y": [round(v, 6) for v in ms["loss_rate"].tolist()],
            "type": "scatter",
            "mode": "lines",
            "name": deal,
            "line": {"color": COLORS[i % len(COLORS)]},
        })

    if traces:
        h += chart(traces, {
            "title": f"{title} — Cumulative Net Loss Rate by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    # ── Pool Factor vs Month, Cum Loss vs Pool Factor, Excess Spread ──
    # Collect per-deal time series once, then feed three charts.
    pf_traces = []       # x=calendar period, y=pool_factor
    pf_loss_traces = []  # x=pool_factor, y=cum net loss rate (chronological line)
    spread_traces = []   # x=calendar period, y=WAC - CoD
    note_bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                     "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                     "D": "note_balance_d", "N": "note_balance_n"}

    for i, deal in enumerate(deals):
        color = COLORS[i % len(COLORS)]
        orig_bal = get_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue

        # Pool factor + cum loss from monthly_summary (consistent month-ends across deals)
        ms = q("SELECT reporting_period_end, total_balance, period_chargeoffs, period_recoveries "
               "FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
        if not ms.empty:
            ms["period"] = ms["reporting_period_end"].apply(nd)
            ms = ms.sort_values("period").reset_index(drop=True)
            ms["pool_factor"] = ms["total_balance"].astype(float) / orig_bal
            ms["cum_loss_rate"] = (ms["period_chargeoffs"].fillna(0) - ms["period_recoveries"].fillna(0)).cumsum() / orig_bal
            pf_traces.append({
                "x": list(range(1, len(ms) + 1)),
                "y": [round(v, 6) for v in ms["pool_factor"].tolist()],
                "type": "scatter", "mode": "lines", "name": deal,
                "line": {"color": color},
            })
            pf_loss_traces.append({
                "x": [round(v, 6) for v in ms["pool_factor"].tolist()],
                "y": [round(v, 6) for v in ms["cum_loss_rate"].tolist()],
                "type": "scatter", "mode": "lines+markers", "name": deal,
                "line": {"color": color},
                "marker": {"size": 4},
            })

        # Excess spread: WAC − CoD aligned on collection-period (year, month).
        # WAC source (pool_performance.weighted_avg_apr for Prime; monthly_summary
        # .weighted_avg_coupon for Non-Prime, which doesn't populate WAC in the
        # servicer report) is keyed by the month-end of the collection period.
        # CoD comes from pool_performance — but those rows use the distribution
        # date, which is ~10 days after the collection period it reports on.
        # Shifting the distribution month back by one gives the collection month.
        pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date", (deal,))
        if pool.empty:
            continue
        pool["period"] = pool["distribution_date"].apply(nd)
        pool = pool.sort_values("period").reset_index(drop=True)

        def _ym(s):
            s = str(s).strip()
            if len(s) >= 7 and s[4] in "-/":
                try:
                    return (int(s[:4]), int(s[5:7]))
                except ValueError:
                    return None
            return None

        # WAC by collection month
        wac_by_col = {}
        if "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any():
            for _, row in pool.iterrows():
                ym = _ym(row["period"])
                w = row["weighted_avg_apr"]
                if ym and pd.notna(w):
                    col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
                    wac_by_col[col_ym] = float(w)
        else:
            wac_ms = q("SELECT reporting_period_end, weighted_avg_coupon FROM monthly_summary "
                       "WHERE deal=? AND weighted_avg_coupon IS NOT NULL ORDER BY reporting_period_end", (deal,))
            for _, row in wac_ms.iterrows():
                ym = _ym(nd(row["reporting_period_end"]))
                if ym:
                    wac_by_col[ym] = float(row["weighted_avg_coupon"])

        # CoD by collection month
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()
        norm_rate_lookup = {}
        if not notes_df.empty:
            for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                norm_rate_lookup[norm] = rate
        for col in note_bal_cols.values():
            if col in pool.columns:
                pool[col] = pool[col].ffill()

        cod_by_col = {}
        has_ni = "total_note_interest" in pool.columns
        has_nb = "aggregate_note_balance" in pool.columns
        for _, row in pool.iterrows():
            ym = _ym(row["period"])
            if not ym:
                continue
            col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
            cod_val = None
            if has_ni and has_nb:
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                    v = float(ni) / float(nb) * 12
                    if 0 < v < 0.25:
                        cod_val = v
            if cod_val is None and norm_rate_lookup:
                w_sum, t_bal = 0.0, 0.0
                for cls, col in note_bal_cols.items():
                    if col in pool.columns and cls in norm_rate_lookup:
                        bal = row.get(col)
                        if pd.notna(bal) and float(bal) > 0:
                            w_sum += norm_rate_lookup[cls] * float(bal)
                            t_bal += float(bal)
                if t_bal > 0:
                    cod_val = w_sum / t_bal
            if cod_val is not None:
                cod_by_col[col_ym] = cod_val

        keys = sorted(set(wac_by_col) & set(cod_by_col))
        if keys:
            spread_traces.append({
                "x": list(range(1, len(keys) + 1)),
                "y": [round(wac_by_col[k] - cod_by_col[k], 6) for k in keys],
                "type": "scatter", "mode": "lines", "name": deal,
                "line": {"color": color},
            })

    if pf_traces:
        h += chart(pf_traces, {
            "title": f"{title} — Pool Factor by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".0%", "title": "Pool Factor (Remaining / Original)"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if pf_loss_traces:
        h += chart(pf_loss_traces, {
            "title": f"{title} — Cumulative Net Loss vs Pool Factor",
            "xaxis": {"title": "Pool Factor (Remaining / Original)",
                      "tickformat": ".0%", "autorange": "reversed"},
            "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
            "hovermode": "closest",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if spread_traces:
        h += chart(spread_traces, {
            "title": f"{title} — Excess Spread by Deal Age (Consumer Rate − Trust Cost of Debt)",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "Excess Spread"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    return h


def generate_model_content():
    """Generate HTML for the Default Model analysis section."""
    mr = None
    try:
        mr = q("SELECT value FROM model_results WHERE key='default_model'")
    except Exception:
        pass

    # If no pre-computed results, try to run the model inline
    if mr is None or mr.empty:
        logger.info("No pre-computed model results found, running model inline...")
        try:
            import importlib.util
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_model.py")
            spec = importlib.util.spec_from_file_location("default_model", model_path)
            dm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(dm)
            dm.DASHBOARD_DB = ACTIVE_DB
            dm.OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "LAST_MODEL_RESULTS.json")
            df = dm.load_data(ACTIVE_DB)
            logger.info(f"Inline model: loaded {len(df)} loans")
            if len(df) > 0:
                df, feature_cols = dm.engineer_features(df)
                results = dm.train_models(df, feature_cols)
                if results:
                    dm.save_results(results, ACTIVE_DB, dm.OUTPUT_JSON)
                    mr = q("SELECT value FROM model_results WHERE key='default_model'")
        except Exception as e:
            logger.error(f"Inline model failed: {e}")

    if mr is None or mr.empty:
        return "<p>Default model could not be computed.</p>"

    results = json.loads(mr.iloc[0]["value"])
    ds = results["dataset"]
    h = ""

    # ── Dataset Summary ──
    h += f"""<div class="metrics">
<div class="metric"><div class="mv">{ds['total_loans']:,}</div><div class="ml">Total Loans</div></div>
<div class="metric"><div class="mv">{ds['defaults']:,}</div><div class="ml">Defaults</div></div>
<div class="metric"><div class="mv">{ds['default_rate']:.2%}</div><div class="ml">Default Rate</div></div>
<div class="metric"><div class="mv">{ds['train_size']:,}</div><div class="ml">Train Set</div></div>
<div class="metric"><div class="mv">{ds['test_size']:,}</div><div class="ml">Test Set</div></div>
</div>"""

    # ── Model Comparison Table ──
    rows = []
    for name, m in results["models"].items():
        rows.append({
            "Model": name.replace("_", " ").title(),
            "Accuracy": f"{m['accuracy']:.1%}",
            "AUC-ROC": f"{m['auc_roc']:.3f}",
            "Precision": f"{m['precision']:.1%}",
            "Recall": f"{m['recall']:.1%}",
            "F1 Score": f"{m['f1']:.1%}",
        })
    h += "<h3>Model Performance</h3>" + table_html(pd.DataFrame(rows), cls="compare")

    # ── ROC Curves ──
    roc_traces = []
    colors = {"logistic_regression": "#1976D2", "random_forest": "#D32F2F"}
    for name, m in results["models"].items():
        roc = m["roc_curve"]
        roc_traces.append({
            "x": roc["fpr"], "y": roc["tpr"],
            "type": "scatter", "mode": "lines",
            "name": f"{name.replace('_',' ').title()} (AUC={m['auc_roc']:.3f})",
            "line": {"color": colors.get(name, "#388E3C")},
        })
    roc_traces.append({
        "x": [0, 1], "y": [0, 1], "type": "scatter", "mode": "lines",
        "name": "Random (AUC=0.5)", "line": {"color": "#999", "dash": "dash"},
    })
    h += chart(roc_traces, {
        "title": "ROC Curve",
        "xaxis": {"title": "False Positive Rate"},
        "yaxis": {"title": "True Positive Rate"},
        "legend": {"orientation": "h", "y": -0.2},
    })

    # ── Feature Importance (Random Forest) ──
    rf = results["models"].get("random_forest", {})
    if "feature_importance" in rf:
        fi = rf["feature_importance"]
        sorted_fi = sorted(fi.items(), key=lambda x: x[1], reverse=True)
        h += chart([{
            "x": [kv[0] for kv in sorted_fi],
            "y": [kv[1] for kv in sorted_fi],
            "type": "bar", "marker": {"color": "#1976D2"},
        }], {"title": "Feature Importance (Random Forest)", "yaxis": {"tickformat": ".1%"}})

    # ── Logistic Regression Coefficients ──
    lr = results["models"].get("logistic_regression", {})
    if "coefficients" in lr:
        coefs = lr["coefficients"]
        sorted_c = sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True)
        colors_c = ["#D32F2F" if v < 0 else "#388E3C" for _, v in sorted_c]
        h += chart([{
            "x": [kv[0] for kv in sorted_c],
            "y": [kv[1] for kv in sorted_c],
            "type": "bar", "marker": {"color": colors_c},
        }], {"title": "Logistic Regression Coefficients (standardized)",
             "yaxis": {"title": "Coefficient"}})

    # ── Confusion Matrices ──
    for name, m in results["models"].items():
        cm = m["confusion_matrix"]
        cm_df = pd.DataFrame({
            "": ["Actual No Default", "Actual Default"],
            "Predicted No Default": [f"{cm[0][0]:,}", f"{cm[1][0]:,}"],
            "Predicted Default": [f"{cm[0][1]:,}", f"{cm[1][1]:,}"],
        })
        h += f"<h3>Confusion Matrix — {name.replace('_',' ').title()}</h3>" + table_html(cm_df, cls="compare")

    # ── Segment Analysis: Predicted vs Actual ──
    segs = results.get("segments", {})

    for seg_key, seg_title in [("by_fico", "Default Rate by FICO Score"),
                                ("by_vintage", "Default Rate by Origination Year"),
                                ("by_ltv", "Default Rate by LTV"),
                                ("by_rate", "Default Rate by Interest Rate")]:
        seg = segs.get(seg_key)
        if not seg:
            continue
        h += chart([
            {"x": seg["labels"], "y": seg["actual_rate"], "type": "bar",
             "name": "Actual", "marker": {"color": "#D32F2F"}},
            {"x": seg["labels"], "y": seg["predicted_rate"], "type": "bar",
             "name": "Predicted", "marker": {"color": "#1976D2"}},
        ], {"title": seg_title, "barmode": "group",
            "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.2}})
        # Table
        tbl_rows = []
        for i, label in enumerate(seg["labels"]):
            row = {"Segment": label, "Loans": f"{seg['loans'][i]:,}",
                   "Actual Default": f"{seg['actual_rate'][i]:.2%}",
                   "Predicted Default": f"{seg['predicted_rate'][i]:.2%}"}
            tbl_rows.append(row)
        h += table_html(pd.DataFrame(tbl_rows), cls="compare")

    # ── Loss Severity ──
    sev = segs.get("loss_severity")
    if sev:
        h += f"""<h3>Loss Severity (Defaulted Loans Only)</h3>
<div class="metrics">
<div class="metric"><div class="mv">{sev['total_defaulted']:,}</div><div class="ml">Defaulted Loans</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_chargeoff'])}</div><div class="ml">Avg Chargeoff</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_recovery'])}</div><div class="ml">Avg Recovery</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_net_loss'])}</div><div class="ml">Avg Net Loss</div></div>
<div class="metric"><div class="mv">{sev['recovery_rate']:.1%}</div><div class="ml">Recovery Rate</div></div>
<div class="metric"><div class="mv">{fm(sev['median_chargeoff'])}</div><div class="ml">Median Chargeoff</div></div>
</div>"""

    return h


def main():
    global _chart_id
    _chart_id = 0

    deal_contents = {}
    for deal in DASHBOARD_DEALS:
        logger.info(f"Generating {deal}...")
        result = generate_deal_content(deal)
        if result:
            deal_contents[deal] = result

    if not deal_contents:
        logger.error("No deals with data found.")
        return

    # Generate comparison sections
    logger.info("Generating Prime comparison...")
    prime_html = generate_comparison_content(
        [d for d in PRIME_DEALS if d in deal_contents], "Prime Deals")
    logger.info("Generating Non-Prime comparison...")
    nonprime_html = generate_comparison_content(
        [d for d in NONPRIME_DEALS if d in deal_contents], "Non-Prime Deals")

    # Generate default model analysis
    logger.info("Generating Default Model analysis...")
    model_html = generate_model_content()

    # Build deal selector dropdown with comparison entries at top
    first_deal = list(deal_contents.keys())[0]
    options = '<option value="__model__">--- Default Model ---</option>\n'
    options += '<option value="__prime__">--- Prime Comparison ---</option>\n'
    options += '<option value="__nonprime__">--- Non-Prime Comparison ---</option>\n'
    options += '<option disabled>──────────────────</option>\n'
    options += "\n".join(f'<option value="{d}" {"selected" if d == first_deal else ""}>{d}</option>' for d in deal_contents)
    deal_selector = f'<div class="deal-select"><select id="dealSelect" onchange="switchDeal(this.value)">{options}</select></div>'

    # Build per-deal content divs
    all_deal_html = ""
    # Add model and comparison sections first (hidden by default)
    all_deal_html += f'<div id="deal-__model__" class="deal-block" style="display:none">\n{model_html}\n</div>\n'
    all_deal_html += f'<div id="deal-__prime__" class="deal-block" style="display:none">\n{prime_html}\n</div>\n'
    all_deal_html += f'<div id="deal-__nonprime__" class="deal-block" style="display:none">\n{nonprime_html}\n</div>\n'
    # Add individual deal sections
    for deal, (metrics, tabs) in deal_contents.items():
        display = "block" if deal == first_deal else "none"
        all_deal_html += f'<div id="deal-{deal}" class="deal-block" style="display:{display}">\n{metrics}\n{tabs}\n</div>\n'

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Carvana ABS Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;color:#212121}}
header{{background:#1976D2;color:white;padding:12px 16px;position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:1.1rem;font-weight:600}}
.deal-select{{padding:4px 12px}}
.deal-select select{{font-size:.9rem;padding:6px 10px;border-radius:6px;border:1px solid #ccc;width:100%;max-width:300px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;padding:8px 12px}}
.metric{{background:white;border-radius:8px;padding:8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.mv{{font-size:1.1rem;font-weight:700;color:#1976D2}}.ml{{font-size:.65rem;color:#666;margin-top:2px}}
.tabs{{display:flex;flex-wrap:wrap;gap:4px;padding:6px 12px;position:sticky;top:44px;z-index:99;background:#f5f5f5}}
.tab{{padding:5px 10px;border:1px solid #ccc;border-radius:6px;background:white;cursor:pointer;font-size:.75rem}}
.tab.active{{background:#1976D2;color:white;border-color:#1976D2}}
.tc{{padding:0 12px 12px}}
.tbl{{overflow-x:auto;margin:8px 0}}
table{{width:100%;border-collapse:collapse;font-size:.7rem;background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th{{background:#f5f5f5;padding:5px 6px;text-align:left;border-bottom:2px solid #ddd;white-space:nowrap}}
td{{padding:4px 6px;border-bottom:1px solid #eee;white-space:nowrap}}
tr:last-child td{{font-weight:700;border-top:2px solid #ddd}}
table.compare tr:last-child td{{font-weight:normal;border-top:none}}
h3{{font-size:.85rem;color:#333;margin:10px 0 4px;padding:0 4px}}
footer{{text-align:center;padding:12px;color:#999;font-size:.65rem}}
@media(max-width:600px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.mv{{font-size:.95rem}}.tab{{font-size:.65rem;padding:4px 6px}}}}
</style></head><body>
<header><h1>Carvana ABS Dashboard</h1></header>
{deal_selector}
{all_deal_html}
<footer>Data from SEC EDGAR | Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</footer>
<script>
function showTab(id,btn){{
    // Hide all tabs in current deal, show selected
    var deal = btn.closest('.deal-block');
    deal.querySelectorAll('.tc').forEach(e=>e.style.display='none');
    deal.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
    document.getElementById(id).style.display='block';
    btn.classList.add('active');
    setTimeout(()=>window.dispatchEvent(new Event('resize')),100);
}}
function switchDeal(deal){{
    document.querySelectorAll('.deal-block').forEach(e=>e.style.display='none');
    document.getElementById('deal-'+deal).style.display='block';
    setTimeout(()=>window.dispatchEvent(new Event('resize')),100);
}}
</script>
</body></html>"""

    out = os.path.join(OUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    logger.info(f"Dashboard: {out} ({os.path.getsize(out)/1024:.0f} KB, {len(deal_contents)} deals)")


if __name__ == "__main__":
    main()
