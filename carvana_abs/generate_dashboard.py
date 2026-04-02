#!/usr/bin/env python3
"""Generate a static HTML dashboard for Carvana 2020-P1 ABS data."""

import os, sys, sqlite3, logging
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
os.makedirs(OUT_DIR, exist_ok=True)

DEAL = "2020-P1"
ORIG_BAL = 405_000_000


def q(sql, params=()):
    conn = sqlite3.connect(ACTIVE_DB)
    conn.row_factory = sqlite3.Row
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
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


def ch(fig, h=350):
    fig.update_layout(margin=dict(l=40,r=20,t=40,b=30), height=h,
                      template="plotly_white", font=dict(size=11))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False})


def table_html(df, max_rows=None):
    if max_rows:
        df = df.head(max_rows)
    rows = "".join(f"<th>{c}</th>" for c in df.columns)
    header = f"<tr>{rows}</tr>"
    body = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{row[c]}</td>" for c in df.columns)
        body += f"<tr>{cells}</tr>"
    return f'<div class="tbl-wrap"><table><thead>{header}</thead><tbody>{body}</tbody></table></div>'


def main():
    logger.info(f"Generating dashboard for {DEAL}...")

    # Load data
    lp = q("SELECT * FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (DEAL,))
    if lp.empty:
        logger.error("No monthly_summary data. Run rebuild_summaries.py first.")
        return
    lp["period"] = lp["reporting_period_end"].apply(nd)
    lp = lp.sort_values("period").reset_index(drop=True)

    pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date", (DEAL,))
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

    last = lp.iloc[-1]

    sections = {}

    # ── TAB 1: POOL SUMMARY ──
    html = ""
    fig = px.area(lp, x="period", y="total_balance", title="Remaining Pool Balance")
    fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
    html += ch(fig)
    fig2 = px.line(lp, x="period", y="active_loans", title="Active Loan Count")
    fig2.update_layout(hovermode="x unified")
    html += ch(fig2)
    if not pool.empty and "weighted_avg_apr" in pool.columns:
        wac = pool[["period","weighted_avg_apr"]].dropna()
        if not wac.empty:
            f = px.line(wac, x="period", y="weighted_avg_apr", title="Weighted Average Coupon")
            f.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
            html += ch(f)
    sections["Pool Summary"] = html

    # ── TAB 2: DELINQUENCIES ──
    html = ""
    dq_cols = {"dq30r":"30d","dq60r":"60d","dq90r":"90d","dq120r":"120+d"}
    m = lp[["period"]+list(dq_cols.keys())].melt(id_vars=["period"], var_name="Bucket", value_name="Rate")
    m["Bucket"] = m["Bucket"].map(dq_cols)
    fig = px.area(m, x="period", y="Rate", color="Bucket", title="Delinquency Rates (% of Pool)",
                  color_discrete_sequence=["#FFC107","#FF9800","#FF5722","#D32F2F"])
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    html += ch(fig)
    # Trigger chart
    if not pool.empty and "delinquency_trigger_level" in pool.columns:
        trig = pool[["period","delinquency_trigger_level","delinquency_trigger_actual"]].dropna()
        if not trig.empty:
            ft = go.Figure()
            ft.add_trace(go.Scatter(x=trig["period"],y=trig["delinquency_trigger_level"],name="Trigger",line=dict(dash="dash",color="red")))
            ft.add_trace(go.Scatter(x=trig["period"],y=trig["delinquency_trigger_actual"],name="Actual",line=dict(color="blue")))
            ft.update_layout(yaxis_tickformat=".2%",hovermode="x unified",title="60+ DQ vs Trigger Level")
            html += ch(ft)
    # Summary table
    dq_tbl = pd.DataFrame({
        "Bucket":["30d","60d","90d","120+d","Total"],
        "Count":[int(last["dq_30_count"]),int(last["dq_60_count"]),int(last["dq_90_count"]),int(last["dq_120_plus_count"]),int(last["total_dq_count"])],
        "Balance":[fm(last["dq_30_balance"]),fm(last["dq_60_balance"]),fm(last["dq_90_balance"]),fm(last["dq_120_plus_balance"]),fm(last["total_dq_balance"])],
        "% Pool":[f"{last['dq30r']:.2%}",f"{last['dq60r']:.2%}",f"{last['dq90r']:.2%}",f"{last['dq120r']:.2%}",f"{last['dq_rate']:.2%}"],
    })
    html += "<h3>Latest Period</h3>" + table_html(dq_tbl)
    sections["Delinquencies"] = html

    # ── TAB 3: LOSSES ──
    html = ""
    fig = px.area(lp, x="period", y="loss_rate", title=f"Cumulative Net Loss Rate (% of {fm(ORIG_BAL)})")
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
    html += ch(fig)

    fg = go.Figure()
    fg.add_trace(go.Scatter(x=lp["period"],y=lp["cum_co"],name="Gross Chargeoffs",line=dict(color="#D32F2F")))
    fg.add_trace(go.Scatter(x=lp["period"],y=lp["cum_rec"],name="Recoveries",line=dict(color="#4CAF50")))
    fg.add_trace(go.Scatter(x=lp["period"],y=lp["cum_net"],name="Net Losses",line=dict(color="#FF9800",dash="dash")))
    fg.update_layout(yaxis_tickformat="$,.0f",hovermode="x unified",title="Cumulative Gross Losses vs Recoveries")
    html += ch(fg)

    rr = lp.dropna(subset=["cum_rec_rate"])
    if not rr.empty:
        fig = px.line(rr, x="period", y="cum_rec_rate", title="Cumulative Recovery Rate")
        fig.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
        fig.update_traces(line_color="#4CAF50")
        html += ch(fig)

    fb = go.Figure()
    fb.add_trace(go.Bar(x=lp["period"],y=lp["period_chargeoffs"],name="Chargeoffs",marker_color="#D32F2F"))
    fb.add_trace(go.Bar(x=lp["period"],y=lp["period_recoveries"],name="Recoveries",marker_color="#4CAF50"))
    fb.update_layout(title="Monthly Chargeoffs vs Recoveries",barmode="group",yaxis_tickformat="$,.0f",hovermode="x unified")
    html += ch(fb)

    # Loss by credit score
    lbs = q("""SELECT l.obligor_credit_score as segment, COUNT(*) as lc,
               SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.obligor_credit_score IS NOT NULL
            GROUP BY l.obligor_credit_score""", (DEAL,))
    if not lbs.empty:
        lbs["s"] = pd.to_numeric(lbs["segment"], errors="coerce")
        lbs = lbs.dropna(subset=["s"])
        lbs["bkt"] = pd.cut(lbs["s"], bins=[0,580,620,660,700,740,780,820,900],
                            labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
        b = lbs.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]
        b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Score":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
                           "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),
                           "Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        html += "<h3>Losses by Credit Score</h3>" + table_html(d)

    # Loss by rate
    lbr = q("""SELECT l.original_interest_rate as segment, COUNT(*) as lc,
               SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.original_interest_rate IS NOT NULL
            GROUP BY l.original_interest_rate""", (DEAL,))
    if not lbr.empty:
        lbr["r"] = pd.to_numeric(lbr["segment"], errors="coerce")
        lbr = lbr.dropna(subset=["r"])
        lbr["bkt"] = pd.cut(lbr["r"], bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                            labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
        b = lbr.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]
        b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Rate":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
                           "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),
                           "Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        html += "<h3>Losses by Interest Rate</h3>" + table_html(d)
    sections["Losses"] = html

    # ── TAB 4: CASH WATERFALL ──
    html = ""
    wf = lp[["period","interest_collected","principal_collected","period_recoveries",
             "est_servicing_fee","period_chargeoffs","net_loss","excess"]].copy()
    wf.columns = ["Period","Interest","Principal","Recoveries","Svc Fee","Chargeoffs","Net Loss","Excess"]
    sums = wf.select_dtypes(include="number").sum()
    sr = pd.DataFrame([["TOTAL"]+sums.tolist()], columns=wf.columns)
    wf_all = pd.concat([wf, sr], ignore_index=True)
    wf_fmt = wf_all.copy()
    for c in wf_fmt.columns[1:]:
        wf_fmt[c] = wf_all[c].apply(lambda x: fm(x) if pd.notna(x) else "")
    html += "<h3>Monthly Cash Flows</h3>" + table_html(wf_fmt)

    fig = px.area(lp, x="period", y="cum_excess_pct", title="Cumulative Excess Spread (% of Original Balance)")
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    fig.update_traces(line_color="#388E3C", fillcolor="rgba(56,142,60,0.2)")
    html += ch(fig)
    sections["Cash Waterfall"] = html

    # ── TAB 5: RECOVERY ──
    html = ""
    rec = q("""SELECT s.asset_number, s.chargeoff_period, s.total_chargeoff,
               s.first_recovery_period, s.total_recovery, l.obligor_credit_score
            FROM loan_loss_summary s
            LEFT JOIN loans l ON s.deal=l.deal AND s.asset_number=l.asset_number
            WHERE s.deal=? AND s.total_chargeoff > 0""", (DEAL,))
    if not rec.empty:
        from datetime import datetime as dt
        def pd_date(d):
            if not d: return None
            d = str(d).strip()
            for f in ["%m-%d-%Y","%m/%d/%Y","%Y-%m-%d"]:
                try: return dt.strptime(d,f)
                except: continue
            return None
        rec["co_dt"] = rec["chargeoff_period"].apply(pd_date)
        rec["rec_dt"] = rec["first_recovery_period"].apply(pd_date)
        rec["has_rec"] = rec["total_recovery"].notna() & (rec["total_recovery"] > 0)
        rec["rec_rate"] = rec.apply(lambda r: r["total_recovery"]/r["total_chargeoff"] if r["has_rec"] and r["total_chargeoff"]>0 else None, axis=1)
        rec["months"] = rec.apply(lambda r: ((r["rec_dt"].year-r["co_dt"].year)*12+r["rec_dt"].month-r["co_dt"].month) if pd.notna(r["rec_dt"]) and pd.notna(r["co_dt"]) else None, axis=1)

        tc = len(rec)
        wr = int(rec["has_rec"].sum())
        ar = rec.loc[rec["has_rec"],"rec_rate"].mean()
        mm = rec.loc[rec["has_rec"],"months"].median()
        tca = rec["total_chargeoff"].sum()
        tra = rec.loc[rec["has_rec"],"total_recovery"].sum()

        html += f"""<div class="metrics">
            <div class="metric"><div class="mv">{tc:,}</div><div class="ml">Charged-Off Loans</div></div>
            <div class="metric"><div class="mv">{wr:,} ({wr/tc:.0%})</div><div class="ml">With Recovery</div></div>
            <div class="metric"><div class="mv">{ar:.1%}</div><div class="ml">Avg Recovery Rate</div></div>
            <div class="metric"><div class="mv">{mm:.0f}</div><div class="ml">Median Months</div></div>
            <div class="metric"><div class="mv">{fm(tca)}</div><div class="ml">Total Chargeoffs</div></div>
            <div class="metric"><div class="mv">{fm(tra)} ({tra/tca:.1%})</div><div class="ml">Total Recovered</div></div>
        </div>"""

        rw = rec[rec["has_rec"] & rec["months"].notna()]
        if not rw.empty:
            fig = px.histogram(rw, x="months", nbins=30, title="Months to First Recovery", color_discrete_sequence=["#1976D2"])
            fig.update_layout(showlegend=False)
            html += ch(fig)

        # Recovery by score
        rs = rec[rec["obligor_credit_score"].notna()].copy()
        if not rs.empty:
            rs["bkt"] = pd.cut(rs["obligor_credit_score"], bins=[0,580,620,660,700,740,780,820,900],
                               labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
            bs = rs.groupby("bkt",observed=True).agg(cnt=("asset_number","count"),
                co=("total_chargeoff","sum"), rec_amt=("total_recovery",lambda x:x.dropna().sum())).reset_index()
            bs["rate"] = bs["rec_amt"] / bs["co"]
            d = pd.DataFrame({"Score":bs["bkt"],"Chargeoffs":bs["cnt"].apply(lambda x:f"{x:,}"),
                               "Total CO":bs["co"].apply(fm),"Recovered":bs["rec_amt"].apply(fm),
                               "Recovery Rate":bs["rate"].apply(lambda x:f"{x:.1%}")})
            html += "<h3>Recovery Rate by Credit Score</h3>" + table_html(d)
    sections["Recovery"] = html

    # ── TAB 6: NOTES & OC ──
    html = ""
    if not pool.empty:
        nc = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                           "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
              if c in pool.columns and pool[c].notna().any()]
        if nc:
            nm = pool[["period"]+nc].melt(id_vars=["period"],var_name="Class",value_name="Balance")
            nm["Class"] = nm["Class"].str.replace("note_balance_","").str.upper()
            fig = px.area(nm, x="period", y="Balance", color="Class", title="Note Balances")
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            html += ch(fig)
        oc = pool[["period","overcollateralization_amount","reserve_account_balance"]].dropna(
            how="all",subset=["overcollateralization_amount","reserve_account_balance"])
        if not oc.empty:
            fo = go.Figure()
            if oc["overcollateralization_amount"].notna().any():
                fo.add_trace(go.Scatter(x=oc["period"],y=oc["overcollateralization_amount"],name="OC"))
            if oc["reserve_account_balance"].notna().any():
                fo.add_trace(go.Scatter(x=oc["period"],y=oc["reserve_account_balance"],name="Reserve"))
            fo.update_layout(yaxis_tickformat="$,.0f",hovermode="x unified",title="OC & Reserve Account")
            html += ch(fo)
    sections["Notes & OC"] = html

    # ── BUILD HTML PAGE ──
    tabs_html = ""
    content_html = ""
    first = True
    for name, body in sections.items():
        tab_id = name.replace(" ","_").replace("&","and")
        active = "active" if first else ""
        display = "block" if first else "none"
        tabs_html += f'<button class="tab {active}" onclick="showTab(\'{tab_id}\')">{name}</button>\n'
        content_html += f'<div id="{tab_id}" class="tab-content" style="display:{display}">{body}</div>\n'
        first = False

    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Carvana 2020-P1 ABS Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;color:#212121}}
header{{background:#1976D2;color:white;padding:12px 16px;position:sticky;top:0;z-index:100}}
header h1{{font-size:1.1rem;font-weight:600}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;padding:8px 12px}}
.metric{{background:white;border-radius:8px;padding:10px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.mv{{font-size:1.2rem;font-weight:700;color:#1976D2}}.ml{{font-size:.7rem;color:#666;margin-top:2px}}
.tabs{{display:flex;flex-wrap:wrap;gap:4px;padding:8px 12px;position:sticky;top:44px;z-index:99;background:#f5f5f5}}
.tab{{padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:white;cursor:pointer;font-size:.8rem}}
.tab.active{{background:#1976D2;color:white;border-color:#1976D2}}
.tab-content{{padding:0 12px 12px}}
.tab-content .js-plotly-plot{{background:white;border-radius:8px;margin:8px 0;padding:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.tbl-wrap{{overflow-x:auto;margin:8px 0}}
table{{width:100%;border-collapse:collapse;font-size:.75rem;background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th{{background:#f5f5f5;padding:6px 8px;text-align:left;border-bottom:2px solid #ddd;white-space:nowrap}}
td{{padding:5px 8px;border-bottom:1px solid #eee;white-space:nowrap}}
tr:last-child td{{font-weight:700;border-top:2px solid #ddd}}
h3{{font-size:.9rem;color:#333;margin:12px 0 4px;padding:0 4px}}
footer{{text-align:center;padding:16px;color:#999;font-size:.7rem}}
@media(max-width:600px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.mv{{font-size:1rem}}.tab{{font-size:.7rem;padding:4px 8px}}}}
</style></head><body>
<header><h1>Carvana 2020-P1 ABS Dashboard</h1></header>
<div class="metrics">
    <div class="metric"><div class="mv">{fm(ORIG_BAL)}</div><div class="ml">Original Balance</div></div>
    <div class="metric"><div class="mv">{fm(last['total_balance'])}</div><div class="ml">Current Balance</div></div>
    <div class="metric"><div class="mv">{last['total_balance']/ORIG_BAL:.1%}</div><div class="ml">Pool Factor</div></div>
    <div class="metric"><div class="mv">{int(last['active_loans']):,}</div><div class="ml">Active Loans</div></div>
    <div class="metric"><div class="mv">{last['loss_rate']:.2%}</div><div class="ml">Cum Loss Rate</div></div>
    <div class="metric"><div class="mv">{last['dq_rate']:.2%}</div><div class="ml">30+ DQ Rate</div></div>
</div>
<div class="tabs">{tabs_html}</div>
{content_html}
<footer>Data from SEC EDGAR | Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</footer>
<script>
function showTab(id){{
    document.querySelectorAll('.tab-content').forEach(e=>e.style.display='none');
    document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
    document.getElementById(id).style.display='block';
    event.target.classList.add('active');
    setTimeout(()=>window.dispatchEvent(new Event('resize')),100);
}}
</script></body></html>"""

    out = os.path.join(OUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    sz = os.path.getsize(out)/(1024*1024)
    logger.info(f"Dashboard: {out} ({sz:.1f} MB)")


if __name__ == "__main__":
    main()
