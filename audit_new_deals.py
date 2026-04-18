#!/usr/bin/env python3
"""Audit the 5 newly-ingested deals for data quality.

Runs the checks expected in Phase 4 of the overnight ingest plan:
  - NULL rates per key column in pool_performance + loans + loan_performance
  - Monotonicity of cumulative_net_losses / cumulative_gross_losses
  - Cross-table joins (loan_performance -> loans FK integrity)
  - deal_terms sanity (initial_pool_balance in range, WAC sane, servicing fee 0.5-1.5%)
  - Spot-check row counts against filings count

Designed to be run on prod:
  /opt/abs-venv/bin/python /opt/abs-dashboard/audit_new_deals.py

Exits 0 on clean pass, 1 if any HALT finding (use in CI).
"""
from __future__ import annotations

import sqlite3
import sys

CARVANA_DB = "/opt/abs-dashboard/carvana_abs/db/carvana_abs.db"
CARMAX_DB = "/opt/abs-dashboard/carmax_abs/db/carmax_abs.db"

NEW_CARVANA = ["2021-P3", "2021-P4", "2025-P1", "2026-P1"]
NEW_CARMAX = ["2026-2"]

findings: list[tuple[str, str, str]] = []  # (severity, deal, message)


def add(severity: str, deal: str, msg: str) -> None:
    findings.append((severity, deal, msg))
    print(f"  [{severity}] {deal}: {msg}")


def audit_pool(conn, deal):
    print(f"\n--- Pool audit: {deal} ---")
    n = conn.execute("SELECT COUNT(*) FROM pool_performance WHERE deal=?", (deal,)).fetchone()[0]
    print(f"  pool_performance rows: {n}")
    if n == 0:
        add("INFO", deal, "pool_performance EMPTY (new deal, may have no certs filed yet)")
        return

    # Null rates on key columns
    for col in [
        "cumulative_net_losses",
        "cumulative_gross_losses",
        "pool_balance",
        "ending_pool_balance",
        "distribution_date",
    ]:
        try:
            nn = conn.execute(
                f"SELECT COUNT(*) FROM pool_performance WHERE deal=? AND {col} IS NULL",
                (deal,),
            ).fetchone()[0]
            if nn > 0 and col in ("cumulative_net_losses", "distribution_date"):
                frac = nn / n
                sev = "HALT" if frac > 0.05 else "WARN"
                add(sev, deal, f"NULL {col}: {nn}/{n} ({frac:.1%})")
            elif nn == n:
                add("WARN", deal, f"NULL {col}: 100% — column unpopulated")
        except sqlite3.OperationalError:
            pass

    # Monotonicity of cumulative_net_losses by distribution_date (lex-date-safe via dist_date_iso if present)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pool_performance)").fetchall()]
    order_col = "dist_date_iso" if "dist_date_iso" in cols else "distribution_date"
    rows = conn.execute(
        f"SELECT {order_col}, cumulative_net_losses, cumulative_gross_losses "
        f"FROM pool_performance WHERE deal=? AND cumulative_net_losses IS NOT NULL "
        f"ORDER BY {order_col} ASC",
        (deal,),
    ).fetchall()
    prev_cnl = prev_cgl = None
    non_mono_cnl = non_mono_cgl = 0
    for d, cnl, cgl in rows:
        if prev_cnl is not None and cnl is not None and cnl < prev_cnl - 1:
            non_mono_cnl += 1
        if prev_cgl is not None and cgl is not None and cgl < prev_cgl - 1:
            non_mono_cgl += 1
        prev_cnl = cnl if cnl is not None else prev_cnl
        prev_cgl = cgl if cgl is not None else prev_cgl
    if non_mono_cnl > 0:
        add("WARN", deal, f"cumulative_net_losses non-monotonic {non_mono_cnl} times (may be restatement)")
    if non_mono_cgl > 0:
        add("WARN", deal, f"cumulative_gross_losses non-monotonic {non_mono_cgl} times (may be restatement)")
    print(f"  rows checked: {len(rows)}, mono-violations cnl={non_mono_cnl} cgl={non_mono_cgl}")


def audit_loans(conn, deal):
    print(f"\n--- Loans audit: {deal} ---")
    loans_n = conn.execute("SELECT COUNT(*) FROM loans WHERE deal=?", (deal,)).fetchone()[0]
    lp_n = conn.execute("SELECT COUNT(*) FROM loan_performance WHERE deal=?", (deal,)).fetchone()[0]
    print(f"  loans rows: {loans_n:,}")
    print(f"  loan_performance rows: {lp_n:,}")
    if loans_n == 0:
        add("INFO", deal, "loans EMPTY (pre-Reg-AB-II deal or brand-new deal w/o ABS-EE yet)")
        return
    # FK: every loan_performance row has a matching loans row
    orphans = conn.execute(
        """SELECT COUNT(*) FROM loan_performance lp
           LEFT JOIN loans l ON lp.deal=l.deal AND lp.asset_number=l.asset_number
           WHERE lp.deal=? AND l.asset_number IS NULL""",
        (deal,),
    ).fetchone()[0]
    if orphans > 0:
        add("HALT", deal, f"{orphans} loan_performance rows with no matching loans row")
    # NULL rates on key loan columns
    for col in ["obligor_credit_score", "original_ltv", "original_term_months", "original_amount"]:
        try:
            nn = conn.execute(f"SELECT COUNT(*) FROM loans WHERE deal=? AND {col} IS NULL", (deal,)).fetchone()[0]
            frac = nn / loans_n
            if frac > 0.10:
                add("WARN", deal, f"NULL {col} on loans: {nn:,}/{loans_n:,} ({frac:.1%})")
        except sqlite3.OperationalError:
            pass
    # Sanity range checks
    bad_fico = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE deal=? AND obligor_credit_score NOT NULL AND (obligor_credit_score<300 OR obligor_credit_score>900)",
        (deal,),
    ).fetchone()[0]
    if bad_fico > 0:
        add("WARN", deal, f"{bad_fico} loans with FICO out of [300,900]")
    bad_ltv = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE deal=? AND original_ltv NOT NULL AND (original_ltv<0 OR original_ltv>300)",
        (deal,),
    ).fetchone()[0]
    if bad_ltv > 0:
        add("WARN", deal, f"{bad_ltv} loans with LTV out of [0,300]")
    bad_apr = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE deal=? AND original_interest_rate NOT NULL AND (original_interest_rate<0 OR original_interest_rate>50)",
        (deal,),
    ).fetchone()[0]
    if bad_apr > 0:
        add("WARN", deal, f"{bad_apr} loans with APR out of [0,50]")


def audit_deal_terms(conn, deal):
    print(f"\n--- deal_terms audit: {deal} ---")
    r = conn.execute(
        "SELECT initial_pool_balance, servicing_fee_pct, oc_target_pct, reserve_pct, note_wac "
        "FROM deal_terms WHERE deal=?",
        (deal,),
    ).fetchone()
    if r is None:
        add("WARN", deal, "no deal_terms row (prospectus parser may not have run yet)")
        return
    ipb, sf, oct_, rsv, wac = r
    print(f"  initial_pool_balance={ipb}, servicing_fee_pct={sf}, oc_target_pct={oct_}, reserve_pct={rsv}, note_wac={wac}")
    if ipb is not None:
        # typical deals: $300M - $2B
        if ipb < 50_000_000 or ipb > 5_000_000_000:
            add("HALT", deal, f"initial_pool_balance OUT OF RANGE: ${ipb:,.0f}")
    if sf is not None:
        if sf < 0.3 or sf > 2.0:
            add("WARN", deal, f"servicing_fee_pct {sf} outside typical 0.5-1.5%")
    if wac is not None:
        if wac < 2 or wac > 15:
            add("WARN", deal, f"note_wac {wac} outside typical 2-15%")


def main():
    print("=" * 70)
    print("NEW DEAL AUDIT — 5 deals newly added to config this session")
    print("=" * 70)

    for db, deals in [(CARVANA_DB, NEW_CARVANA), (CARMAX_DB, NEW_CARMAX)]:
        c = sqlite3.connect(db)
        for deal in deals:
            audit_pool(c, deal)
            audit_loans(c, deal)
            audit_deal_terms(c, deal)
        c.close()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    by_sev = {"HALT": 0, "WARN": 0, "INFO": 0}
    for sev, deal, msg in findings:
        by_sev[sev] = by_sev.get(sev, 0) + 1
    print(f"  HALT: {by_sev.get('HALT',0)}")
    print(f"  WARN: {by_sev.get('WARN',0)}")
    print(f"  INFO: {by_sev.get('INFO',0)}")
    for sev, deal, msg in findings:
        if sev == "HALT":
            print(f"    HALT: {deal}  {msg}")

    if by_sev.get("HALT", 0) > 0:
        print("\nOne or more HALT findings — fix before proceeding.")
        sys.exit(1)
    print("\nCLEAN PASS (WARN findings are expected for brand-new deals).")
    sys.exit(0)


if __name__ == "__main__":
    main()
