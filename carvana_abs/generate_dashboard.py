#!/usr/bin/env python3
"""Generate a static HTML dashboard from the database.

Produces plain HTML files with embedded Plotly charts. No server needed —
nginx serves them directly. Loads in <1 second.

Usage: python carvana_abs/generate_dashboard.py
Output: carvana_abs/static_site/index.html (+ per-deal pages)
"""

import os
import sys
import sqlite3
import json
import logging
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH, DEALS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Use the small dashboard DB if available
DB_DIR = os.path.dirname(DB_PATH)
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else DB_PATH

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "carvana_abs", "static_site")
os.makedirs(OUT_DIR, exist_ok=True)


def query(sql, params=()):
    conn = sqlite3.connect(ACTIVE_DB)
    conn.row_factory = sqlite3.Row
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def normalize_date(d):
    if not d:
        return d
    d = str(d).strip()
    for sep in ["-", "/"]:
        parts = d.split(sep)
        if len(parts) == 3 and len(parts[0]) <= 2 and len(parts[2]) == 4:
            return f"{parts[2]}{sep}{parts[0].zfill(2)}{sep}{parts[1].zfill(2)}"
    return d


def fmt(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "-"
    if abs(val) >= 1e9: return f"${val/1e9:.1f}B"
    if abs(val) >= 1e6: return f"${val/1e6:.1f}M"
    if abs(val) >= 1e3: return f"${val/1e3:.0f}K"
    return f"${val:,.0f}"


def chart_html(fig, height=350):
    """Convert Plotly figure to minimal HTML div (no full page wrapper)."""
    fig.update_layout(margin=dict(l=40, r=20, t=40, b=30), height=height,
                      template="plotly_white", font=dict(size=11))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def get_orig_bal(deal):
    cfg = DEALS.get(deal, {})
    bal = cfg.get("original_pool_balance")
    if bal:
        return bal
    fp = query("SELECT beginning_pool_balance FROM pool_performance WHERE deal=? ORDER BY distribution_date LIMIT 1", (deal,))
    if not fp.empty and fp.iloc[0]["beginning_pool_balance"]:
        return fp.iloc[0]["beginning_pool_balance"]
    t = query("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal=?", (deal,))
    return t.iloc[0]["s"] if not t.empty and t.iloc[0]["s"] else 405_000_000


def generate_deal_page(deal):
    """Generate a complete HTML page for one deal."""
    ORIG_BAL = get_orig_bal(deal)
    cfg = DEALS.get(deal, {})

    # Load data
    lp = query("SELECT * FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
    if lp.empty:
        return None
    lp["period"] = lp["reporting_period_end"].apply(normalize_date)
    lp = lp.sort_values("period").reset_index(drop=True)

    pool = query("SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date", (deal,))
    if not pool.empty:
        pool["period"] = pool["distribution_date"].apply(normalize_date)
        pool = pool.sort_values("period").reset_index(drop=True)

    # Compute cumulative columns
    lp["cum_co"] = lp["period_chargeoffs"].cumsum()
    lp["cum_rec"] = lp["period_recoveries"].cumsum()
    lp["cum_net"] = lp["cum_co"] - lp["cum_rec"]
    lp["loss_rate"] = lp["cum_net"] / ORIG_BAL
    lp["dq_rate"] = lp["total_dq_balance"] / lp["total_balance"]
    lp["net_loss"] = lp["period_chargeoffs"] - lp["period_recoveries"]
    lp["excess"] = lp["interest_collected"] + lp["period_recoveries"] - lp["est_servicing_fee"] - lp["net_loss"]
    lp["cum_excess"] = lp["excess"].cumsum()
    lp["cum_excess_pct"] = lp["cum_excess"] / ORIG_BAL
    lp["cum_rec_rate"] = lp["cum_rec"] / lp["cum_co"].replace(0, float("nan"))

    last = lp.iloc[-1]

    charts = []

    # Pool Balance
    fig = px.area(lp, x="period", y="total_balance", title="Remaining Pool Balance")
    fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
    charts.append(("Pool Balance", chart_html(fig)))

    # Delinquency Rate
    fig = px.line(lp, x="period", y="dq_rate", title="Total Delinquency Rate (30+ Days)")
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    charts.append(("Delinquency Rate", chart_html(fig)))

    # Cumulative Loss Rate
    fig = px.area(lp, x="period", y="loss_rate", title=f"Cumulative Net Loss Rate (% of {fmt(ORIG_BAL)})")
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    fig.update_traces(line_color="#D32F2F", fillcolor="rgba(211,47,47,0.2)")
    charts.append(("Cumulative Loss Rate", chart_html(fig)))

    # Gross vs Recoveries
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=lp["period"], y=lp["cum_co"], name="Gross Chargeoffs", line=dict(color="#D32F2F")))
    fig.add_trace(go.Scatter(x=lp["period"], y=lp["cum_rec"], name="Recoveries", line=dict(color="#4CAF50")))
    fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified", title="Cumulative Gross Losses vs Recoveries")
    charts.append(("Gross vs Recoveries", chart_html(fig)))

    # Recovery Rate
    rr = lp.dropna(subset=["cum_rec_rate"])
    if not rr.empty:
        fig = px.line(rr, x="period", y="cum_rec_rate", title="Cumulative Recovery Rate")
        fig.update_layout(yaxis_tickformat=".1%", hovermode="x unified")
        fig.update_traces(line_color="#4CAF50")
        charts.append(("Recovery Rate", chart_html(fig)))

    # Cumulative Excess Spread
    fig = px.area(lp, x="period", y="cum_excess_pct", title="Cumulative Excess Spread (% of Original Balance)")
    fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
    fig.update_traces(line_color="#388E3C", fillcolor="rgba(56,142,60,0.2)")
    charts.append(("Excess Spread", chart_html(fig)))

    # WAC from pool_performance
    if not pool.empty and "weighted_avg_apr" in pool.columns:
        wac = pool[["period", "weighted_avg_apr"]].dropna()
        if not wac.empty:
            fig = px.line(wac, x="period", y="weighted_avg_apr", title="Weighted Average Coupon")
            fig.update_layout(yaxis_tickformat=".2%", hovermode="x unified")
            charts.append(("WAC", chart_html(fig)))

    # Note balances
    if not pool.empty:
        nc = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                           "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
              if c in pool.columns and pool[c].notna().any()]
        if nc:
            nm = pool[["period"]+nc].melt(id_vars=["period"], var_name="Class", value_name="Balance")
            nm["Class"] = nm["Class"].str.replace("note_balance_","").str.upper()
            fig = px.area(nm, x="period", y="Balance", color="Class", title="Note Balances")
            fig.update_layout(yaxis_tickformat="$,.0f", hovermode="x unified")
            charts.append(("Note Balances", chart_html(fig)))

    # Build metrics HTML
    metrics_html = f"""
    <div class="metrics">
        <div class="metric"><div class="mv">{fmt(ORIG_BAL)}</div><div class="ml">Original Balance</div></div>
        <div class="metric"><div class="mv">{fmt(last['total_balance'])}</div><div class="ml">Current Balance</div></div>
        <div class="metric"><div class="mv">{last['total_balance']/ORIG_BAL:.1%}</div><div class="ml">Pool Factor</div></div>
        <div class="metric"><div class="mv">{int(last['active_loans']):,}</div><div class="ml">Active Loans</div></div>
        <div class="metric"><div class="mv">{last['loss_rate']:.2%}</div><div class="ml">Cum Loss Rate</div></div>
        <div class="metric"><div class="mv">{last['dq_rate']:.2%}</div><div class="ml">DQ Rate (30+)</div></div>
    </div>
    """

    # Build charts HTML
    charts_html = ""
    for title, html in charts:
        charts_html += f'<div class="chart-card"><h3>{title}</h3>{html}</div>\n'

    return metrics_html, charts_html


def generate_site():
    """Generate the complete static site."""
    deals = query("SELECT DISTINCT deal FROM filings ORDER BY deal")
    deal_list = deals["deal"].tolist() if not deals.empty else []

    # Generate per-deal content
    deal_pages = {}
    for deal in deal_list:
        logger.info(f"Generating {deal}...")
        result = generate_deal_page(deal)
        if result:
            deal_pages[deal] = result

    if not deal_pages:
        logger.error("No deals with data found")
        return

    # Build deal selector
    first_deal = list(deal_pages.keys())[0]
    options_html = "\n".join(
        f'<option value="{d}" {"selected" if d == first_deal else ""}>{d}</option>'
        for d in deal_pages.keys()
    )

    # Build all deal content (hidden, shown via JS)
    all_content = ""
    for deal, (metrics, charts) in deal_pages.items():
        display = "block" if deal == first_deal else "none"
        all_content += f'<div id="deal-{deal}" class="deal-content" style="display:{display}">\n'
        all_content += metrics + "\n" + charts + "\n</div>\n"

    # Write index.html
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carvana ABS Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #212121; }}
header {{ background: #1976D2; color: white; padding: 12px 16px; position: sticky; top: 0; z-index: 100; }}
header h1 {{ font-size: 1.1rem; font-weight: 600; }}
.deal-select {{ margin: 8px 16px; }}
.deal-select select {{ font-size: 1rem; padding: 8px 12px; border-radius: 6px; border: 1px solid #ccc;
                        width: 100%; max-width: 400px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 8px; padding: 8px 16px; }}
.metric {{ background: white; border-radius: 8px; padding: 12px; text-align: center;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.mv {{ font-size: 1.3rem; font-weight: 700; color: #1976D2; }}
.ml {{ font-size: 0.75rem; color: #666; margin-top: 4px; }}
.chart-card {{ background: white; border-radius: 8px; margin: 8px 16px; padding: 12px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.chart-card h3 {{ font-size: 0.9rem; color: #333; margin-bottom: 8px; }}
footer {{ text-align: center; padding: 16px; color: #999; font-size: 0.75rem; }}
@media (max-width: 600px) {{
    .mv {{ font-size: 1.1rem; }}
    .metrics {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>
<header><h1>Carvana ABS Dashboard</h1></header>
<div class="deal-select">
    <select id="dealSelector" onchange="switchDeal(this.value)">
        {options_html}
    </select>
</div>
{all_content}
<footer>Data from SEC EDGAR | Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</footer>
<script>
function switchDeal(deal) {{
    document.querySelectorAll('.deal-content').forEach(el => el.style.display = 'none');
    document.getElementById('deal-' + deal).style.display = 'block';
    // Re-trigger Plotly resize for visible charts
    setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
}}
</script>
</body>
</html>"""

    out_path = os.path.join(OUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    logger.info(f"Dashboard generated: {out_path} ({size_mb:.1f} MB)")
    logger.info(f"Deals: {len(deal_pages)}")


if __name__ == "__main__":
    generate_site()
