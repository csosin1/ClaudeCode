#!/usr/bin/env python3
"""Diagnostic: check what data each deal has in the database."""
import os, sqlite3, sys

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB

DEALS = [
    "2020-P1",
    "2021-N1", "2021-N2", "2021-N3", "2021-N4", "2021-P1", "2021-P2",
    "2022-P1", "2022-P2", "2022-P3",
    "2024-P2", "2024-P3", "2024-P4",
    "2025-P2", "2025-P3", "2025-P4",
]

def q(sql, params=()):
    conn = sqlite3.connect(ACTIVE_DB)
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    cols = [d[0] for d in c.description] if c.description else []
    conn.close()
    return rows, cols

print(f"Database: {ACTIVE_DB}")
print(f"Exists: {os.path.exists(ACTIVE_DB)}")
print(f"Size: {os.path.getsize(ACTIVE_DB) / 1e6:.1f} MB")
print()

# Check what tables exist
rows, _ = q("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in rows]
print(f"Tables: {', '.join(tables)}")
print()

# Check notes class naming
print("=" * 80)
print("NOTES TABLE — class names per deal")
print("=" * 80)
for deal in DEALS:
    rows, _ = q("SELECT class, coupon_rate, original_balance FROM notes WHERE deal=?", (deal,))
    if rows:
        classes = [(r[0], r[1], r[2]) for r in rows]
        print(f"  {deal}: {classes}")
    else:
        print(f"  {deal}: NO NOTES DATA")

print()
print("=" * 80)
print("POOL_PERFORMANCE — data availability per deal")
print("=" * 80)
for deal in DEALS:
    rows, _ = q("SELECT COUNT(*) FROM pool_performance WHERE deal=?", (deal,))
    count = rows[0][0] if rows else 0

    # Check key columns
    wac_rows, _ = q("SELECT COUNT(*) FROM pool_performance WHERE deal=? AND weighted_avg_apr IS NOT NULL", (deal,))
    wac_count = wac_rows[0][0] if wac_rows else 0

    ni_rows, _ = q("SELECT COUNT(*) FROM pool_performance WHERE deal=? AND total_note_interest IS NOT NULL", (deal,))
    ni_count = ni_rows[0][0] if ni_rows else 0

    nb_rows, _ = q("SELECT COUNT(*) FROM pool_performance WHERE deal=? AND aggregate_note_balance IS NOT NULL AND aggregate_note_balance > 0", (deal,))
    nb_count = nb_rows[0][0] if nb_rows else 0

    # Check note balance columns
    bal_cols = ["note_balance_a1", "note_balance_a2", "note_balance_a3", "note_balance_a4",
                "note_balance_b", "note_balance_c", "note_balance_d", "note_balance_n"]
    bal_avail = []
    for col in bal_cols:
        try:
            br, _ = q(f"SELECT COUNT(*) FROM pool_performance WHERE deal=? AND {col} IS NOT NULL AND {col} > 0", (deal,))
            if br[0][0] > 0:
                bal_avail.append(col.replace("note_balance_", "").upper())
        except:
            pass

    print(f"  {deal}: {count} rows | wac={wac_count} | note_int={ni_count} | note_bal={nb_count} | bal_cols={','.join(bal_avail) or 'NONE'}")

print()
print("=" * 80)
print("MONTHLY_SUMMARY — data availability per deal")
print("=" * 80)
for deal in DEALS:
    rows, _ = q("SELECT COUNT(*) FROM monthly_summary WHERE deal=?", (deal,))
    count = rows[0][0] if rows else 0

    wac_rows, _ = q("SELECT COUNT(*) FROM monthly_summary WHERE deal=? AND weighted_avg_coupon IS NOT NULL", (deal,))
    wac_count = wac_rows[0][0] if wac_rows else 0

    bal_rows, _ = q("SELECT total_balance FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end DESC LIMIT 1", (deal,))
    latest_bal = bal_rows[0][0] if bal_rows else None

    print(f"  {deal}: {count} rows | wac={wac_count} | latest_bal={latest_bal}")

print()
print("=" * 80)
print("LOANS — data availability per deal")
print("=" * 80)
for deal in DEALS:
    rows, _ = q("SELECT COUNT(*), AVG(obligor_credit_score), AVG(original_interest_rate) FROM loans WHERE deal=?", (deal,))
    count, avg_fico, avg_rate = rows[0] if rows else (0, None, None)
    print(f"  {deal}: {count} loans | avg_fico={avg_fico:.0f if avg_fico else 'NULL'} | avg_rate={avg_rate:.4f if avg_rate else 'NULL'}")

print()
print("=" * 80)
print("ORIG BALANCE DETECTION")
print("=" * 80)
for deal in DEALS:
    # Method 1: beginning_pool_balance
    bp, _ = q("SELECT beginning_pool_balance FROM pool_performance WHERE deal=? ORDER BY distribution_date LIMIT 1", (deal,))
    bp_val = bp[0][0] if bp else None
    # Method 2: SUM loans
    ls, _ = q("SELECT SUM(original_loan_amount) FROM loans WHERE deal=?", (deal,))
    ls_val = ls[0][0] if ls else None
    print(f"  {deal}: pool_perf_begin={bp_val} | loan_sum={ls_val}")
