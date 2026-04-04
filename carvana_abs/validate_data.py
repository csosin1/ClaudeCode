#!/usr/bin/env python3
"""Comprehensive data validation for Carvana ABS database.

Checks every data element for sanity, cross-references between tables,
and reports issues. Run after ingestion or reingest.

Usage: python carvana_abs/validate_data.py
"""
import os
import sys
import sqlite3
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carvana_abs.config import DB_PATH, DEALS

DASHBOARD_DB = os.path.join(os.path.dirname(DB_PATH), "dashboard.db")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "deploy", "LAST_DATA_CHECK.txt")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate(db_path=None):
    db = db_path or (DASHBOARD_DB if os.path.exists(DASHBOARD_DB) else DB_PATH)
    if not os.path.exists(db):
        return "ERROR: No database found"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    lines = [f"Data Validation Report ({os.path.basename(db)})", "=" * 70, ""]
    errors = 0
    warnings = 0

    # ── 1. Table row counts ──
    lines.append("=== Table Row Counts ===")
    for table in ["filings", "pool_performance", "monthly_summary", "loans",
                   "loan_loss_summary", "notes"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            lines.append(f"  {table:25s} {count:>8,} rows")
        except Exception:
            lines.append(f"  {table:25s} TABLE MISSING")

    # ── 2. Deal coverage ──
    lines.append("")
    lines.append("=== Deal Coverage ===")
    for deal in sorted(DEALS.keys()):
        ms = conn.execute("SELECT COUNT(*) FROM monthly_summary WHERE deal=?", (deal,)).fetchone()[0]
        pp = conn.execute("SELECT COUNT(*) FROM pool_performance WHERE deal=?", (deal,)).fetchone()[0]
        loans = conn.execute("SELECT COUNT(*) FROM loans WHERE deal=?", (deal,)).fetchone()[0]
        try:
            notes = conn.execute("SELECT COUNT(*) FROM notes WHERE deal=?", (deal,)).fetchone()[0]
        except Exception:
            notes = -1
        status = "OK" if ms > 0 and pp > 0 else "GAPS"
        if ms == 0 and pp == 0:
            status = "EMPTY"
        lines.append(f"  {status:5s} {deal:12s} monthly={ms:3d} pool={pp:3d} loans={loans:>6,} notes={notes}")
        if ms == 0:
            errors += 1

    # ── 3. Monthly summary sanity checks ──
    lines.append("")
    lines.append("=== Monthly Summary Sanity Checks ===")
    for deal in sorted(DEALS.keys()):
        rows = conn.execute("""
            SELECT reporting_period_end, active_loans, total_balance,
                   period_chargeoffs, period_recoveries, weighted_avg_coupon,
                   dq_30_balance, dq_60_balance, dq_90_balance, dq_120_plus_balance,
                   total_dq_balance
            FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end
        """, (deal,)).fetchall()
        if not rows:
            continue
        issues = []
        for r in rows:
            period = r["reporting_period_end"]
            # Balance should be positive
            if r["total_balance"] is not None and r["total_balance"] <= 0:
                issues.append(f"{period}: total_balance={r['total_balance']}")
            # Active loans should be positive
            if r["active_loans"] is not None and r["active_loans"] <= 0:
                issues.append(f"{period}: active_loans={r['active_loans']}")
            # Chargeoffs should be non-negative
            if r["period_chargeoffs"] is not None and r["period_chargeoffs"] < 0:
                issues.append(f"{period}: negative chargeoffs={r['period_chargeoffs']}")
            # WAC should be 0.1% to 30%
            wac = r["weighted_avg_coupon"]
            if wac is not None and (wac < 0.001 or wac > 0.30):
                issues.append(f"{period}: wac={wac:.4%} outside 0.1-30%")
            # DQ buckets should sum to total
            if r["total_dq_balance"] is not None:
                parts = sum(x or 0 for x in [r["dq_30_balance"], r["dq_60_balance"],
                                              r["dq_90_balance"], r["dq_120_plus_balance"]])
                if abs(parts - r["total_dq_balance"]) > 1.0:  # Allow $1 rounding
                    issues.append(f"{period}: DQ buckets sum={parts:.0f} != total={r['total_dq_balance']:.0f}")
        if issues:
            lines.append(f"  ISSUES {deal}: {len(issues)} problems")
            for iss in issues[:5]:
                lines.append(f"    - {iss}")
            if len(issues) > 5:
                lines.append(f"    ... and {len(issues)-5} more")
            warnings += len(issues)
        else:
            lines.append(f"  OK     {deal}: {len(rows)} periods checked")

    # ── 4. Pool performance sanity checks ──
    lines.append("")
    lines.append("=== Pool Performance Sanity Checks ===")
    for deal in sorted(DEALS.keys()):
        rows = conn.execute("""
            SELECT distribution_date, beginning_pool_balance, ending_pool_balance,
                   aggregate_note_balance, weighted_avg_apr,
                   note_balance_a1, note_balance_a2, note_balance_a3, note_balance_a4,
                   note_balance_b, note_balance_c, note_balance_d, note_balance_n,
                   total_note_interest, overcollateralization_amount
            FROM pool_performance WHERE deal=? ORDER BY distribution_date
        """, (deal,)).fetchall()
        if not rows:
            continue
        issues = []
        for r in rows:
            dt = r["distribution_date"]
            # Note balances should sum to aggregate (if both exist)
            note_cols = [r["note_balance_a1"], r["note_balance_a2"], r["note_balance_a3"],
                        r["note_balance_a4"], r["note_balance_b"], r["note_balance_c"],
                        r["note_balance_d"], r["note_balance_n"]]
            note_sum = sum(x or 0 for x in note_cols)
            agg = r["aggregate_note_balance"]
            if agg and note_sum > 0 and abs(note_sum - agg) > agg * 0.01:  # >1% diff
                issues.append(f"{dt}: note sum={note_sum:,.0f} vs aggregate={agg:,.0f}")
            # WAC should be reasonable
            wac = r["weighted_avg_apr"]
            if wac is not None and (wac < 0.001 or wac > 0.30):
                issues.append(f"{dt}: weighted_avg_apr={wac:.4%} outside range")
            # Pool balance should be > note balance (OC > 0)
            pool = r["ending_pool_balance"]
            if pool and agg and pool < agg * 0.9:  # Pool < 90% of notes = suspicious
                issues.append(f"{dt}: pool_bal={pool:,.0f} < note_bal={agg:,.0f}")
        if issues:
            lines.append(f"  ISSUES {deal}: {len(issues)} problems")
            for iss in issues[:5]:
                lines.append(f"    - {iss}")
            if len(issues) > 5:
                lines.append(f"    ... and {len(issues)-5} more")
            warnings += len(issues)
        else:
            lines.append(f"  OK     {deal}: {len(rows)} periods checked")

    # ── 5. Cross-reference: monthly_summary vs pool_performance ──
    lines.append("")
    lines.append("=== Cross-Reference: monthly_summary vs pool_performance ===")
    for deal in sorted(DEALS.keys()):
        ms_rows = conn.execute("""
            SELECT reporting_period_end, total_balance FROM monthly_summary
            WHERE deal=? ORDER BY reporting_period_end
        """, (deal,)).fetchall()
        pp_rows = conn.execute("""
            SELECT distribution_date, ending_pool_balance FROM pool_performance
            WHERE deal=? AND ending_pool_balance IS NOT NULL ORDER BY distribution_date
        """, (deal,)).fetchall()
        if not ms_rows or not pp_rows:
            continue
        # Compare period counts
        lines.append(f"  {deal:12s} monthly_summary={len(ms_rows)} pool_performance={len(pp_rows)}")

    # ── 6. Notes table validation ──
    lines.append("")
    lines.append("=== Notes Table (Coupon Rates) ===")
    try:
        for deal in sorted(DEALS.keys()):
            notes = conn.execute("""
                SELECT class, coupon_rate, rate_type FROM notes
                WHERE deal=? ORDER BY class
            """, (deal,)).fetchall()
            if notes:
                rates_str = ", ".join(f"{n['class']}={n['coupon_rate']:.2%}" for n in notes if n['coupon_rate'])
                lines.append(f"  OK     {deal:12s} {len(notes)} classes: {rates_str}")
            else:
                lines.append(f"  EMPTY  {deal:12s} no note rates")
                warnings += 1
    except Exception:
        lines.append("  TABLE MISSING — notes table not created yet")

    # ── 7. Cost of Debt computation check ──
    lines.append("")
    lines.append("=== Cost of Debt (from notes × balances) ===")
    try:
        for deal in sorted(DEALS.keys()):
            notes = conn.execute("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,)).fetchall()
            if not notes:
                continue
            rate_lookup = {n["class"]: n["coupon_rate"] for n in notes}
            bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                        "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                        "D": "note_balance_d", "N": "note_balance_n"}
            # First and last period
            for label, order in [("INIT", "ASC"), ("CURR", "DESC")]:
                pp = conn.execute(f"SELECT * FROM pool_performance WHERE deal=? ORDER BY distribution_date {order} LIMIT 1", (deal,)).fetchone()
                if pp:
                    w_sum, t_bal = 0, 0
                    for cls, col in bal_cols.items():
                        if cls in rate_lookup:
                            bal = pp[col] if pp[col] else 0
                            if bal > 0:
                                w_sum += rate_lookup[cls] * bal
                                t_bal += bal
                    if t_bal > 0:
                        cod = w_sum / t_bal
                        lines.append(f"  {deal:12s} {label}: CoD={cod:.4%} (weighted avg of {len(rate_lookup)} classes, bal=${t_bal:,.0f})")
    except Exception as e:
        lines.append(f"  ERROR: {e}")

    # ── Summary ──
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"TOTAL: {errors} errors, {warnings} warnings")
    if errors > 0:
        lines.append("STATUS: FAILED")
    elif warnings > 0:
        lines.append("STATUS: PASSED with warnings")
    else:
        lines.append("STATUS: PASSED")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(report + "\n")
    print(report)

    conn.close()
    return report


if __name__ == "__main__":
    validate()
