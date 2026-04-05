#!/usr/bin/env python3
"""Check data availability for WAC and Cost of Debt across all deals.

Outputs a text report to deploy/LAST_DATA_CHECK.txt.
Run after export_dashboard_db.py to verify dashboard.db has what we need.
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "deploy", "LAST_DATA_CHECK.txt")


def check():
    db = DASHBOARD_DB if os.path.exists(DASHBOARD_DB) else DB_PATH
    if not os.path.exists(db):
        return "ERROR: No database found"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    lines = [f"Data Check Report (using {os.path.basename(db)})", "=" * 60, ""]

    # Check monthly_summary for weighted_avg_coupon
    lines.append("=== Monthly Summary: weighted_avg_coupon ===")
    cur = conn.execute("""
        SELECT deal, COUNT(*) as periods,
               COUNT(weighted_avg_coupon) as wac_periods,
               MIN(weighted_avg_coupon) as min_wac,
               MAX(weighted_avg_coupon) as max_wac,
               AVG(weighted_avg_coupon) as avg_wac
        FROM monthly_summary GROUP BY deal ORDER BY deal
    """)
    for row in cur:
        status = "OK" if row["wac_periods"] > 0 else "MISSING"
        wac_str = f"min={row['min_wac']:.4%} max={row['max_wac']:.4%} avg={row['avg_wac']:.4%}" if row["wac_periods"] else "no data"
        lines.append(f"  {status} {row['deal']:12s} {row['wac_periods']:3d}/{row['periods']:3d} periods  {wac_str}")

    # Check pool_performance for weighted_avg_apr
    lines.append("")
    lines.append("=== Pool Performance: weighted_avg_apr ===")
    cur = conn.execute("""
        SELECT deal, COUNT(*) as periods,
               COUNT(weighted_avg_apr) as wac_periods,
               MIN(weighted_avg_apr) as min_wac,
               MAX(weighted_avg_apr) as max_wac
        FROM pool_performance GROUP BY deal ORDER BY deal
    """)
    for row in cur:
        status = "OK" if row["wac_periods"] > 0 else "MISSING"
        wac_str = f"min={row['min_wac']:.4%} max={row['max_wac']:.4%}" if row["wac_periods"] else "no data"
        lines.append(f"  {status} {row['deal']:12s} {row['wac_periods']:3d}/{row['periods']:3d} periods  {wac_str}")

    # Check pool_performance for Cost of Debt components
    lines.append("")
    lines.append("=== Pool Performance: Cost of Debt (total_note_interest / aggregate_note_balance * 12) ===")
    cur = conn.execute("""
        SELECT deal, COUNT(*) as periods,
               COUNT(total_note_interest) as int_periods,
               COUNT(CASE WHEN aggregate_note_balance > 0 THEN 1 END) as bal_periods,
               MIN(CASE WHEN aggregate_note_balance > 0
                   THEN total_note_interest * 1.0 / aggregate_note_balance * 12 END) as min_cod,
               MAX(CASE WHEN aggregate_note_balance > 0
                   THEN total_note_interest * 1.0 / aggregate_note_balance * 12 END) as max_cod,
               AVG(CASE WHEN aggregate_note_balance > 0
                   THEN total_note_interest * 1.0 / aggregate_note_balance * 12 END) as avg_cod
        FROM pool_performance GROUP BY deal ORDER BY deal
    """)
    for row in cur:
        has_int = row["int_periods"] > 0
        has_bal = row["bal_periods"] > 0
        if has_int and has_bal and row["avg_cod"] is not None:
            cod_str = f"min={row['min_cod']:.4%} max={row['max_cod']:.4%} avg={row['avg_cod']:.4%}"
            suspicious = " ** SUSPICIOUS **" if row["max_cod"] > 0.15 or row["min_cod"] < 0.001 else ""
            status = "OK"
        else:
            cod_str = f"interest={row['int_periods']} bal={row['bal_periods']} periods"
            suspicious = ""
            status = "MISSING"
        lines.append(f"  {status} {row['deal']:12s} {row['int_periods']:3d}/{row['periods']:3d} periods  {cod_str}{suspicious}")

    # Sample: show first and last CoD values for each deal
    lines.append("")
    lines.append("=== Cost of Debt: First and Last values per deal ===")
    deals = [r[0] for r in conn.execute("SELECT DISTINCT deal FROM pool_performance ORDER BY deal")]
    for deal in deals:
        first = conn.execute("""
            SELECT distribution_date, total_note_interest, aggregate_note_balance
            FROM pool_performance WHERE deal=? AND total_note_interest IS NOT NULL
            AND aggregate_note_balance > 0 ORDER BY distribution_date LIMIT 1
        """, (deal,)).fetchone()
        last = conn.execute("""
            SELECT distribution_date, total_note_interest, aggregate_note_balance
            FROM pool_performance WHERE deal=? AND total_note_interest IS NOT NULL
            AND aggregate_note_balance > 0 ORDER BY distribution_date DESC LIMIT 1
        """, (deal,)).fetchone()
        if first:
            init_cod = first["total_note_interest"] / first["aggregate_note_balance"] * 12
            lines.append(f"  {deal:12s} INIT: date={first['distribution_date']} "
                        f"interest=${first['total_note_interest']:,.2f} "
                        f"balance=${first['aggregate_note_balance']:,.2f} "
                        f"CoD={init_cod:.4%}")
        else:
            lines.append(f"  {deal:12s} INIT: no data")
        if last and (not first or last["distribution_date"] != first["distribution_date"]):
            curr_cod = last["total_note_interest"] / last["aggregate_note_balance"] * 12
            lines.append(f"  {deal:12s} CURR: date={last['distribution_date']} "
                        f"interest=${last['total_note_interest']:,.2f} "
                        f"balance=${last['aggregate_note_balance']:,.2f} "
                        f"CoD={curr_cod:.4%}")

    conn.close()
    report = "\n".join(lines)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(report + "\n")
    print(report)
    return report


if __name__ == "__main__":
    check()
