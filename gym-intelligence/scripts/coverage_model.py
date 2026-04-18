#!/usr/bin/env python3
"""Build the coverage model from scraper outputs.

1. Load all per-bin outputs + remaining-file outputs, merge.
2. Filter bogus extractions (year-like numbers, extreme outliers).
3. Per bin: hit count, median/mean coverage ratio, interquartile range.
4. Extrapolate per-bin coverage to unscraped chains in that bin (MCAR assumption).
5. Weight bins by gym count → aggregate DB coverage estimate + honest uncertainty.

Per-chain filter rules:
- scraped_count between 5 and 5000 (already enforced during scrape)
- scraped_count NOT 2020-2030 (year-leak from date patterns)
- Hit must have method != 'no_pattern'
"""
import json
import os
import sqlite3
import statistics
from collections import defaultdict

BASE = "/opt/gym-intelligence-preview/writeup/data/coverage_output"
INPUT_BASE = "/opt/gym-intelligence-preview/writeup/data/coverage_input"
BINS = ["A_100plus", "B_20to99", "C_10to19", "D_4to9", "E_2to3"]
BIN_LABEL = {
    "A_100plus": "100+",
    "B_20to99": "20-99",
    "C_10to19": "10-19",
    "D_4to9": "4-9",
    "E_2to3": "2-3",
    "F_1": "1 (single-location)",
}


def load_bin(bin_name):
    """Merge the main output + the _rem output if present."""
    rows = []
    seen_ids = set()
    for path in [
        f"{BASE}/{bin_name}.json",
        f"/tmp/{bin_name}_rem_out.json",
        f"/tmp/{bin_name}_remaining_output.json",
    ]:
        if os.path.exists(path):
            try:
                for r in json.load(open(path)):
                    if r["chain_id"] not in seen_ids:
                        rows.append(r)
                        seen_ids.add(r["chain_id"])
            except Exception:
                pass
    return rows


def is_valid_hit(row):
    """Filter: does this row have a usable scraped_count?"""
    n = row.get("scraped_count")
    if not n or not isinstance(n, (int, float)):
        return False
    if n < 5 or n > 5000:
        return False
    # Year-leak filter: 2019-2030 is suspicious unless stated_total with clear context
    if 2019 <= n <= 2030:
        method = (row.get("method") or "").lower()
        if "stated:" in method and ("club" in method or "studio" in method or "salle" in method or "gym" in method):
            # Still suspicious but give it a chance if OHSOME count is in similar range
            oc = row.get("ohsome_2026q1") or 0
            if abs(n - oc) / max(oc, 1) > 5:  # wildly different, probably year
                return False
        else:
            return False
    # Coverage sanity: if scraped count is wildly different from OHSOME, maybe wrong page
    oc = row.get("ohsome_2026q1") or 0
    if oc > 0:
        ratio = n / oc
        if ratio > 20 or ratio < 0.05:
            return False
    return True


def load_all_bins(conn):
    """Return dict: bin -> list of rows (with validity flag)."""
    data = {}
    for b in BINS:
        rows = load_bin(b)
        # Load raw bin size (all chains we attempted OR intended to attempt in-scope)
        inp = json.load(open(f"{INPUT_BASE}/{b}.json"))
        inp_ids = {c["chain_id"] for c in inp}
        inp_total_gyms = sum(c["location_count"] for c in inp)
        # Also: count ALL chains in this size bin in DB (not just with websites)
        if b == "A_100plus":
            q = "location_count >= 100"
        elif b == "B_20to99":
            q = "location_count >= 20 AND location_count < 100"
        elif b == "C_10to19":
            q = "location_count >= 10 AND location_count < 20"
        elif b == "D_4to9":
            q = "location_count >= 4 AND location_count < 10"
        elif b == "E_2to3":
            q = "location_count >= 2 AND location_count < 4"
        db_chains, db_gyms = conn.execute(
            f"SELECT COUNT(*), SUM(location_count) FROM chains WHERE {q}"
        ).fetchone()
        for r in rows:
            r["_valid"] = is_valid_hit(r)
        data[b] = {
            "rows": rows,
            "scope_chain_ids_with_websites": inp_ids,
            "scope_total_gyms_with_websites": inp_total_gyms,
            "db_total_chains_in_bin": db_chains,
            "db_total_gyms_in_bin": db_gyms,
            "chains_attempted": len(rows),
            "valid_hits": sum(1 for r in rows if r["_valid"]),
            "invalid_hits": sum(1 for r in rows if r.get("scraped_count") and not r["_valid"]),
        }
    return data


def bin_metrics(bin_row):
    """Compute coverage metrics for a bin."""
    rows = [r for r in bin_row["rows"] if r["_valid"]]
    if not rows:
        return {"n_valid": 0}
    # Per-chain coverage: ohsome / scraped (capped to avoid infinities)
    ratios = []
    for r in rows:
        oc = r.get("ohsome_2026q1") or 0
        sc = r["scraped_count"]
        if sc > 0:
            ratios.append(oc / sc)
    if not ratios:
        return {"n_valid": 0}
    ratios.sort()
    n = len(ratios)
    mean = statistics.mean(ratios)
    median = ratios[n // 2]
    return {
        "n_valid": n,
        "mean_coverage_pct": round(mean * 100, 1),
        "median_coverage_pct": round(median * 100, 1),
        "p10": round(ratios[max(0, n // 10)] * 100, 1),
        "p25": round(ratios[max(0, n // 4)] * 100, 1),
        "p75": round(ratios[min(n - 1, 3 * n // 4)] * 100, 1),
        "p90": round(ratios[min(n - 1, 9 * n // 10)] * 100, 1),
        # Aggregate (gym-weighted) for scraped chains
        "aggregate_live_sum": sum(r["scraped_count"] for r in rows),
        "aggregate_ohsome_sum": sum(r.get("ohsome_2026q1") or 0 for r in rows),
    }


def main():
    conn = sqlite3.connect("/opt/gym-intelligence-preview/gyms.db")
    conn.row_factory = sqlite3.Row

    data = load_all_bins(conn)
    results = {"bins": {}}

    total_db_gyms = 0
    total_estimated_true_gyms = 0
    for b, bd in data.items():
        m = bin_metrics(bd)
        # Extrapolate
        db_gyms_in_bin = bd["db_total_gyms_in_bin"] or 0
        if m["n_valid"] > 0:
            # Method: aggregate coverage from scraped chains = ohsome_total_scraped / live_total_scraped
            agg_cov = m["aggregate_ohsome_sum"] / m["aggregate_live_sum"]
            # Median per-chain coverage (more robust)
            med_cov = m["median_coverage_pct"] / 100
            # True gyms in bin estimated: ohsome_total_bin / coverage_ratio
            # Use median to reduce outlier skew
            estimated_true_bin_gyms = db_gyms_in_bin / max(med_cov, 0.01)
            # Also expose aggregate-method estimate for comparison
            agg_estimated_true_bin_gyms = db_gyms_in_bin / max(agg_cov, 0.01)
        else:
            med_cov = None
            agg_cov = None
            estimated_true_bin_gyms = None
            agg_estimated_true_bin_gyms = None

        results["bins"][b] = {
            "label": BIN_LABEL[b],
            "db_total_chains_in_bin": bd["db_total_chains_in_bin"],
            "db_total_gyms_in_bin": db_gyms_in_bin,
            "chains_with_website": len(bd["scope_chain_ids_with_websites"]),
            "chains_attempted": bd["chains_attempted"],
            "valid_hits": bd["valid_hits"],
            "invalid_hits": bd["invalid_hits"],
            "metrics": m,
            "estimated_true_gyms_in_bin_median_method": int(estimated_true_bin_gyms) if estimated_true_bin_gyms else None,
            "estimated_true_gyms_in_bin_aggregate_method": int(agg_estimated_true_bin_gyms) if agg_estimated_true_bin_gyms else None,
        }

        total_db_gyms += db_gyms_in_bin
        if estimated_true_bin_gyms:
            total_estimated_true_gyms += estimated_true_bin_gyms

    # F_1 bin: user's assumption = 2-chain coverage applies to single-location
    e_cov_median = results["bins"]["E_2to3"]["metrics"].get("median_coverage_pct", 100) / 100
    f_db_chains, f_db_gyms = conn.execute(
        "SELECT COUNT(*), SUM(location_count) FROM chains WHERE location_count = 1"
    ).fetchone()
    f_estimated_true = f_db_gyms / max(e_cov_median, 0.01)
    results["bins"]["F_1"] = {
        "label": BIN_LABEL["F_1"],
        "db_total_chains_in_bin": f_db_chains,
        "db_total_gyms_in_bin": f_db_gyms,
        "note": "Single-location entries: user directive applies E_2to3 (2-3 chain) coverage as the estimate for single-location completeness. No direct measurement.",
        "applied_coverage_from": "E_2to3 median",
        "applied_coverage_pct": round(e_cov_median * 100, 1),
        "estimated_true_gyms_in_bin_median_method": int(f_estimated_true),
    }
    total_db_gyms += f_db_gyms
    total_estimated_true_gyms += f_estimated_true

    results["aggregate"] = {
        "total_db_gyms_all_bins": int(total_db_gyms),
        "total_estimated_true_gyms_all_bins": int(total_estimated_true_gyms),
        "overall_coverage_pct": round(100 * total_db_gyms / total_estimated_true_gyms, 1),
    }

    results["methodology"] = {
        "primary_method": "Per chain: scrape chain's store-locator page, extract stated count or count structured data entries. Compare to OHSOME 2026-03-31 snapshot total.",
        "bin_extrapolation": "For each size bin: use median per-chain coverage ratio of scraped chains as the bin's coverage estimate. Extrapolate to unscraped chains (MCAR assumption).",
        "single_location_assumption": "Single-location entries (29997 chains / 29997 gyms) cannot be directly validated (no multi-gym list to compare). Per user directive, apply 2-3 chain bin coverage as the estimate — weakest link, flagged.",
        "filters": "scraped_count filtered to [5,5000], year-range numbers (2019-2030) excluded unless context is unambiguous, coverage ratio outliers >20x or <0.05x rejected as extraction bugs.",
        "caveats": [
            "Hit rate is low (~15-25%) because many chain websites are bot-protected or SPA-rendered, and Playwright fallback didn't materially improve extraction. Estimates are MCAR-extrapolated from the scrapable subset within each bin.",
            "The 2-3 chain bin is treated as the proxy for single-location coverage per user directive. This is an assumption, not a measurement; real single-gym completeness may be materially different.",
            "OHSOME 2026-03-31 has its own documented accuracy issues (F-006 through F-010 in AUDIT_FINDINGS.md) — those biases are baked into the numerator here.",
            "Chain-matcher false positives (F-010: Fitness Park overcount) can produce coverage ratios > 100%. Not filtered out — reflects real data quality.",
        ],
    }

    out_path = "/opt/gym-intelligence-preview/writeup/data/coverage-model.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"wrote {out_path}")
    # Print summary table
    print("\n=== Coverage by chain-size bin ===")
    print(f"{'bin':10} {'chains':>8} {'gyms':>8} {'hits':>6} {'median%':>9} {'agg%':>8} {'est_true':>10}")
    for b in ["A_100plus", "B_20to99", "C_10to19", "D_4to9", "E_2to3", "F_1"]:
        r = results["bins"][b]
        m = r.get("metrics", {}) or {}
        print(f"{r['label']:10} {r['db_total_chains_in_bin']:>8} {r['db_total_gyms_in_bin']:>8} "
              f"{m.get('n_valid','-'):>6} {m.get('median_coverage_pct','-')!s:>9} "
              f"{round(m.get('aggregate_ohsome_sum',0)/max(m.get('aggregate_live_sum',1),1)*100,1) if m.get('n_valid') else '-'!s:>8} "
              f"{r.get('estimated_true_gyms_in_bin_median_method','-')!s:>10}")
    print(f"\nOverall DB coverage (weighted): {results['aggregate']['overall_coverage_pct']}%")
    print(f"DB has {results['aggregate']['total_db_gyms_all_bins']} gyms; estimated true population ~{results['aggregate']['total_estimated_true_gyms_all_bins']}")


if __name__ == "__main__":
    main()
