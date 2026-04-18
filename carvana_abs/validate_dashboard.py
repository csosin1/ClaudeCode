#!/usr/bin/env python3
"""Validate the generated dashboard HTML for common issues.

Run after generate_dashboard.py to check for problems BEFORE deploying.
Usage: python carvana_abs/validate_dashboard.py
"""

import os
import sys
import re

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
HTML_PATH = os.path.join(STATIC_DIR, "index.html")


def validate():
    if not os.path.exists(HTML_PATH):
        print("FAIL: index.html does not exist. Run generate_dashboard.py first.")
        return False

    with open(HTML_PATH, encoding="utf-8") as f:
        html = f.read()

    errors = []
    warnings = []
    info = []

    size_kb = len(html) / 1024
    info.append(f"File size: {size_kb:.0f} KB")

    # Check basic structure
    if "<html" not in html:
        errors.append("Missing <html> tag")
    if "plotly" not in html.lower():
        errors.append("Missing Plotly library reference")
    if "Plotly.newPlot" not in html:
        errors.append("No Plotly.newPlot calls found — charts are empty")

    # Count charts
    chart_count = html.count("Plotly.newPlot")
    info.append(f"Charts: {chart_count}")

    # Count deals
    deal_blocks = re.findall(r'id="deal-([^"]+)"', html)
    info.append(f"Deals: {len(deal_blocks)} — {', '.join(deal_blocks)}")

    # Check for deal dropdown
    if "dealSelect" in html and "<select" in html:
        info.append("Deal dropdown: YES")
    elif len(deal_blocks) > 1:
        errors.append("Multiple deals but no dropdown selector found")
    else:
        info.append("Deal dropdown: N/A (single deal)")

    # Check for NaN or None in chart data
    nan_count = html.count("NaN")
    none_count = html.count(": null")
    if nan_count > 10:
        warnings.append(f"Found {nan_count} NaN values in chart data — may cause empty charts")
    if none_count > 50:
        warnings.append(f"Found {none_count} null values in chart data")

    # Check for $0 metrics (possible bad data)
    zero_metrics = re.findall(r'class="mv">\$0<', html)
    if zero_metrics:
        warnings.append(f"Found {len(zero_metrics)} metrics showing $0 — possible data issue")

    # Check that charts have actual data values (not just 0-50 index)
    y_arrays = re.findall(r'"y":\s*\[([\d.,\s-]+)\]', html)
    for i, arr in enumerate(y_arrays[:5]):  # Check first 5 charts
        vals = [float(v.strip()) for v in arr.split(",") if v.strip()]
        if vals and max(vals) < 100 and min(vals) >= 0:
            warnings.append(f"Chart {i+1} y-values look like indices (0-{max(vals):.0f}) — data may not be rendering")

    # Check for tab navigation
    tab_count = html.count('class="tab')
    info.append(f"Tab buttons: {tab_count}")

    # Check for tables
    table_count = html.count("<table")
    info.append(f"Tables: {table_count}")

    # Check for waterfall data
    if "Residual" in html or "residual_cash" in html:
        info.append("Waterfall residual: YES")
    else:
        info.append("Waterfall residual: NO")

    # Check rate curves (consumer rate / cost of debt) — now separate charts
    individual_deals = [d for d in deal_blocks if d not in ("__prime__", "__nonprime__")]
    consumer_rate_count = html.count("Avg Consumer Rate")
    cod_count = html.count("Avg Trust Cost of Debt")
    info.append(f"Rate charts: Consumer Rate={consumer_rate_count}, Trust CoD={cod_count} (of {len(individual_deals)} deals)")
    if consumer_rate_count < len(individual_deals):
        warnings.append(f"{len(individual_deals) - consumer_rate_count} deal(s) missing Consumer Rate chart")
    if cod_count < len(individual_deals):
        warnings.append(f"{len(individual_deals) - cod_count} deal(s) missing Trust Cost of Debt chart")

    # Check comparison tabs
    if "deal-__prime__" in html:
        info.append("Prime comparison: YES")
    else:
        warnings.append("Prime comparison section missing")
    if "deal-__nonprime__" in html:
        info.append("Non-Prime comparison: YES")
    else:
        warnings.append("Non-Prime comparison section missing")

    # Check comparison summary tables for excessive dashes
    for section_id, label in [("deal-__prime__", "Prime"), ("deal-__nonprime__", "Non-Prime")]:
        start = html.find(f'id="{section_id}"')
        if start >= 0:
            end = html.find('</div>', start + 1000)  # Find end of section
            section = html[start:end+6] if end > start else ""
            dash_count = section.count("<td>-</td>")
            cell_count = section.count("<td>")
            if cell_count > 0 and dash_count / cell_count > 0.4:
                warnings.append(f"{label} comparison table: {dash_count}/{cell_count} cells are '-' ({dash_count/cell_count:.0%})")

    # Check for mobile CSS
    if "@media" in html:
        info.append("Mobile responsive: YES")
    else:
        warnings.append("No mobile responsive CSS found")

    # Report
    print("=" * 50)
    print("Dashboard Validation Report")
    print("=" * 50)
    for i in info:
        print(f"  INFO: {i}")
    for w in warnings:
        print(f"  WARN: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if errors:
        print(f"\nFAILED — {len(errors)} error(s)")
        return False
    elif warnings:
        print(f"\nPASSED with {len(warnings)} warning(s)")
        return True
    else:
        print(f"\nPASSED — all checks OK")
        return True


if __name__ == "__main__":
    ok = validate()
    sys.exit(0 if ok else 1)
