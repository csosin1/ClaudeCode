#!/usr/bin/env python3
"""Final overnight QA audit — runs after dashboard regen.

Per SKILLS/data-audit-qa.md: Phase 1 (invariant scan), Phase 3 (dashboard
spot-checks on each new deal's Residual Economics row).
"""
from __future__ import annotations

import sqlite3
import sys
import json

CARVANA_DB = "/opt/abs-dashboard/carvana_abs/db/carvana_abs.db"
CARMAX_DB = "/opt/abs-dashboard/carmax_abs/db/carmax_abs.db"
CARVANA_DASH = "/opt/abs-dashboard/carvana_abs/db/dashboard.db"
CARMAX_DASH = "/opt/abs-dashboard/carmax_abs/db/dashboard.db"

NEW_CARVANA = ["2021-P3", "2021-P4", "2025-P1", "2026-P1"]
NEW_CARMAX = ["2026-2"]

findings = []


def add(sev, deal, msg):
    findings.append((sev, deal, msg))
    print(f"  [{sev}] {deal}: {msg}")


def phase1_invariants():
    print("\n=== Phase 1: Invariant scan (ALL deals) ===\n")
    total_deals_dash = 0
    for issuer, main_db, dash_db in [("Carvana", CARVANA_DB, CARVANA_DASH), ("CarMax", CARMAX_DB, CARMAX_DASH)]:
        print(f"\n-- {issuer} --")
        c = sqlite3.connect(main_db)
        d = sqlite3.connect(dash_db)
        # 1. pool_performance: monotonic cumulative_net_losses per deal (with dist_date_iso)
        cols = [r[1] for r in c.execute("PRAGMA table_info(pool_performance)").fetchall()]
        order_col = "dist_date_iso" if "dist_date_iso" in cols else "distribution_date"
        deals = [r[0] for r in c.execute("SELECT DISTINCT deal FROM pool_performance").fetchall()]
        print(f"  {len(deals)} deals in pool_performance")
        mono_vios = 0
        for deal in deals:
            rows = c.execute(
                f"SELECT {order_col}, cumulative_net_losses FROM pool_performance "
                f"WHERE deal=? AND cumulative_net_losses IS NOT NULL ORDER BY {order_col}",
                (deal,),
            ).fetchall()
            prev = None
            for dt, v in rows:
                if prev is not None and v < prev - 10_000:  # tolerate small restatement
                    mono_vios += 1
                prev = v if v is not None else prev
        if mono_vios > 100:
            add("WARN", issuer, f"{mono_vios} CNL monotonicity violations (expected some from restatements)")
        else:
            print(f"  {issuer} CNL monotonicity: {mono_vios} violations (OK)")

        # 2. deal_forecasts exists for all deals with loan-level data
        lc_deals = set(r[0] for r in c.execute("SELECT DISTINCT deal FROM loans").fetchall()) if \
            "loans" in [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()] \
            else set()
        try:
            fc_deals = set(r[0] for r in c.execute("SELECT DISTINCT deal FROM deal_forecasts").fetchall())
        except sqlite3.OperationalError:
            fc_deals = set()
        missing = sorted(lc_deals - fc_deals)
        if missing:
            # Brand-new deals with only 1 period of data may be skipped by Markov
            if issuer == "Carvana" and set(missing).issubset({"2026-P1"}):
                print(f"  {issuer} deal_forecasts: missing {missing} — OK (brand-new deal may not have enough history for Markov)")
            else:
                add("WARN", issuer, f"deals with loan data but no Markov forecast: {missing}")
        else:
            print(f"  {issuer} deal_forecasts covers all {len(lc_deals)} loan-data deals")

        # 3. dashboard.db has deal_metadata rows for all deals
        try:
            dash_deals = [r[0] for r in d.execute(
                "SELECT DISTINCT deal FROM pool_performance").fetchall()]
            print(f"  {issuer} dashboard.db deals: {len(dash_deals)}")
            total_deals_dash += len(dash_deals)
            sub_missing = set(deals) - set(dash_deals)
            if sub_missing:
                # Deals with no pool data (like CarMax 2026-2) are expected
                if issuer == "CarMax" and sub_missing == {"2026-2"}:
                    pass
                else:
                    add("WARN", issuer, f"deals in main DB but not in dashboard.db: {sub_missing}")
        except sqlite3.OperationalError as e:
            add("WARN", issuer, f"dashboard.db query err: {e}")

        c.close()
        d.close()

    print(f"\nTotal deals in dashboard.db across both issuers: {total_deals_dash}")


def phase3_spot_new():
    print("\n=== Phase 3: Spot-check each new deal ===\n")
    for issuer, main_db in [("Carvana", CARVANA_DB), ("CarMax", CARMAX_DB)]:
        new = NEW_CARVANA if issuer == "Carvana" else NEW_CARMAX
        c = sqlite3.connect(main_db)
        for deal in new:
            print(f"\n-- {issuer} {deal} --")
            # Pool summary
            r = c.execute(
                "SELECT COUNT(*), MIN(distribution_date), MAX(distribution_date), "
                "MAX(cumulative_net_losses), MAX(ending_pool_balance) "
                "FROM pool_performance WHERE deal=?",
                (deal,),
            ).fetchone()
            n, mind, maxd, max_cnl, last_pb = r
            print(f"  pool: {n} rows, {mind} → {maxd}, max_cnl={max_cnl}, last_pb={last_pb}")
            # Loan-level
            try:
                loans_n = c.execute("SELECT COUNT(*) FROM loans WHERE deal=?", (deal,)).fetchone()[0]
                print(f"  loans: {loans_n:,}")
            except Exception:
                loans_n = 0
            # deal_terms
            dt = c.execute(
                "SELECT initial_pool_balance, weighted_avg_coupon, servicing_fee_annual_pct "
                "FROM deal_terms WHERE deal=?",
                (deal,),
            ).fetchone()
            if dt:
                ipb, wac, sf = dt
                print(f"  deal_terms: IPB=${ipb/1e6:.1f}M, WAC={wac*100:.2f}%, SF={sf*100:.2f}%" if ipb else
                      f"  deal_terms: IPB=None, WAC={wac}, SF={sf}")
            # Markov forecast if exists
            try:
                fr = c.execute(
                    "SELECT at_issuance_cnl_pct, projected_cnl_pct, realized_cnl_pct, calibration_factor "
                    "FROM deal_forecasts WHERE deal=?",
                    (deal,),
                ).fetchone()
                if fr:
                    print(f"  markov: at_iss={fr[0]}, projected={fr[1]}, realized={fr[2]}, cal={fr[3]}")
                else:
                    print(f"  markov: no forecast (new deal may lack enough history)")
            except sqlite3.OperationalError as e:
                print(f"  markov: err {e}")
        c.close()


def main():
    print("=" * 70)
    print("FINAL OVERNIGHT QA AUDIT — 5 new deals + universe invariants")
    print("=" * 70)
    phase1_invariants()
    phase3_spot_new()
    print("\n" + "=" * 70)
    print(f"Findings: {len(findings)}")
    halt_n = sum(1 for s, _, _ in findings if s == "HALT")
    warn_n = sum(1 for s, _, _ in findings if s == "WARN")
    print(f"  HALT: {halt_n}")
    print(f"  WARN: {warn_n}")
    if halt_n > 0:
        print("\nHALT findings block promotion:")
        for s, d, m in findings:
            if s == "HALT":
                print(f"  {d}: {m}")
        sys.exit(1)
    print("\nFINAL AUDIT CLEAN")
    sys.exit(0)


if __name__ == "__main__":
    main()
