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


def table_html(df):
    rows = "".join(f"<th>{c}</th>" for c in df.columns)
    header = f"<tr>{rows}</tr>"
    body = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{row[c]}</td>" for c in df.columns)
        body += f"<tr>{cells}</tr>"
    return f'<div class="tbl"><table><thead>{header}</thead><tbody>{body}</tbody></table></div>'


def get_orig_bal(deal):
    """Auto-detect original pool balance from first pool_performance record or loan sum."""
    # Known balances
    KNOWN = {"2020-P1": 405_000_000}
    if deal in KNOWN:
        return KNOWN[deal]
    fp = q("SELECT beginning_pool_balance FROM pool_performance WHERE deal=? ORDER BY distribution_date LIMIT 1", (deal,))
    if not fp.empty and fp.iloc[0]["beginning_pool_balance"] and fp.iloc[0]["beginning_pool_balance"] > 0:
        return fp.iloc[0]["beginning_pool_balance"]
    t = q("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal=?", (deal,))
    if not t.empty and t.iloc[0]["s"] and t.iloc[0]["s"] > 0:
        return t.iloc[0]["s"]
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
    lp["excess"] = lp["interest_collected"] + lp["period_recoveries"] - lp["est_servicing_fee"] - lp["net_loss"]
    lp["cum_excess"] = lp["excess"].cumsum()
    lp["cum_excess_pct"] = lp["cum_excess"] / ORIG_BAL
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
    if not pool.empty and "weighted_avg_apr" in pool.columns:
        wac = pool.dropna(subset=["weighted_avg_apr"])
        if not wac.empty:
            # Use pool dates directly but set x-axis range to match other charts
            h += chart([{"x": wac["period"].tolist(), "y": wac["weighted_avg_apr"].tolist(), "type": "scatter"}],
                       {"title": "Weighted Average Coupon", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
                        "xaxis": {"range": [x[0], x[-1]], "tickangle": -45, "automargin": True}})
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
    wf = lp[["period","interest_collected","principal_collected","period_recoveries","est_servicing_fee","period_chargeoffs","net_loss","excess"]].copy()
    wf.columns = ["Period","Interest","Principal","Recoveries","Svc Fee","Chargeoffs","Net Loss","Excess"]
    sums = wf.select_dtypes(include="number").sum()
    sr = pd.DataFrame([["TOTAL"]+sums.tolist()], columns=wf.columns)
    wf_all = pd.concat([wf, sr], ignore_index=True)
    wf_fmt = wf_all.copy()
    for c in wf_fmt.columns[1:]:
        wf_fmt[c] = wf_all[c].apply(lambda x: fm(x) if pd.notna(x) else "")
    h = "<h3>Monthly Cash Flows</h3>" + table_html(wf_fmt)
    h += chart([{"x": x, "y": lp["cum_excess_pct"].tolist(), "type": "scatter", "fill": "tozeroy", "line": {"color": "#388E3C"}}],
               {"title": "Cumulative Excess Spread (% of Original Balance)", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
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

    # Build deal selector dropdown
    first_deal = list(deal_contents.keys())[0]
    options = "\n".join(f'<option value="{d}" {"selected" if d == first_deal else ""}>{d}</option>' for d in deal_contents)
    deal_selector = f'<div class="deal-select"><select id="dealSelect" onchange="switchDeal(this.value)">{options}</select></div>'

    # Build per-deal content divs
    all_deal_html = ""
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
