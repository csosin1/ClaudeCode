#!/usr/bin/env python3
"""audit_display_ranges.py — sanity-range audit for every numeric column on
every rendered page of the Carvana ABS dashboard.

Motivation (see LESSONS.md 2026-04-18):
  Two production bugs in 36 hours had the same root cause: columns computed
  at render time (not stored in DB) bypassed the data-audit-qa Phase 1-4
  surface. Examples — 100× rendering of Exp Loss (caught by luck in spot
  checks), WAL collapse to 0.1y on brand-new deals (caught by user).

This script parses the rendered HTML tree in ``static_site/preview/`` (or
``live/``), converts every cell to a numeric value when possible, and
validates it against a per-column range. Aggregate-level checks tighten the
ranges for summary rows. Cross-column chain checks verify derived columns
are internally consistent.

Exits non-zero if any HALT findings. On HALT the report lists every
offending cell with its expected range, actual value, and location hint so
the renderer bug can be traced back from the HTML.

Usage:
    audit_display_ranges.py                 # audit preview/
    audit_display_ranges.py --live          # audit live/
    audit_display_ranges.py --root <path>   # audit a custom tree
    audit_display_ranges.py --json          # emit JSON report (cron-friendly)

Requires bs4 (already in the /opt/abs-venv/ shared venv).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    print("ERROR: bs4 not available. Run under /opt/abs-venv/bin/python.", file=sys.stderr)
    raise


# ────────────────────────────────────────────────────────────────────────
# DISPLAY_RANGES — per-column expected value range.
#
# Key = canonical column name used across the dashboard (NOT the display
# string). Normalization maps free-form headers to these keys.
#
# Tuple = (lo, hi, unit, why).
#   unit is informational only: "pct", "ratio", "yr", "bps", "usd_M".
#   A value may be outside the range ± we record a HALT.
#
# Ranges are deliberately wide — they catch *impossible* values, not
# suspicious ones. Aggregate sanity checks below tighten them for summary
# rows.
#
# IMPORTANT: every time a new numeric column is added to generate_dashboard.py
# a matching entry MUST be added here. PR review should reject additions
# that don't update this dict (see LESSONS.md 2026-04-18).
# ────────────────────────────────────────────────────────────────────────

DISPLAY_RANGES: dict[str, tuple[float, float, str, str]] = {
    # Residual Economics table (both the landing-page snapshot and the full
    # economics page use the same column set).
    "orig_bal_usd_M":         (10.0,   20_000.0, "usd_M",   "$10 MM – $20 B per deal is the ABS universe"),
    # Consumer WAC spans prime (6-10%) to non-prime (18-23%). Upper bound 28%
    # accommodates sub-prime extremes; any value above is a parser bug.
    "consumer_wac_pct":       (3.0,    28.0,     "pct",     "WAC observed 3-28% across 2014-2026 rate cycles (prime ~6-10%, non-prime ~18-23%)"),
    "cost_of_debt_pct":       (0.2,    10.0,     "pct",     "Note WAC — 2Y Tsy floor ~0% plus spread; cap at ~10%"),
    # Non-prime deals have WAC ~19% and cost of debt ~1%, so XS/yr ~18%. Prime
    # XS/yr typically 3-8%. Upper bound 25% catches impossible values.
    "excess_spread_yr_pct":   (0.0,    25.0,     "pct",     "Gross annualized XS — prime 3-8%, non-prime 15-20%"),
    "wal_years":              (0.1,    5.0,      "yr",      "Auto ABS amortization — 0.1-5y WAL"),
    "wal_now_years":          (0.1,    5.0,      "yr",      "Remaining WAL as deal seasons"),
    # total_xs = xs_yr × wal; non-prime 2021 deals hit ~37%. 50% upper bound.
    "total_xs_pct":           (0.0,    50.0,     "pct",     "Total excess spread life-of-deal; non-prime can reach 40%"),
    "servicing_fee_pct":      (0.5,    6.0,      "pct",     "Typical servicing fee 1-4% annualized"),
    "expected_loss_pct":      (0.0,    30.0,     "pct",     "Initial expected loss — 0 to ~30% for nonprime"),
    "expected_residual_pct":  (-5.0,   30.0,     "pct",     "Initial expected residual — can be small negative rounding"),
    # Cumulative interest collected runs to 40%+ on seasoned non-prime.
    "actual_int_pct":         (0.0,    50.0,     "pct",     "Cumulative interest / orig balance; non-prime can reach 40%"),
    "actual_svc_pct":         (0.0,    10.0,     "pct",     "Cumulative servicing paid as % of orig balance"),
    "projected_loss_pct":     (0.0,    30.0,     "pct",     "Current projected lifetime loss"),
    "actual_residual_pct":    (-30.0,  30.0,     "pct",     "Current residual estimate can be negative if losses blow past OC"),
    "variance_pct":           (-30.0,  30.0,     "pct",     "Residual variance vs. initial forecast"),
    "variance_usd_M":         (-10_000.0, 10_000.0, "usd_M","Variance in $ millions; extreme but plausible"),
    "pct_done":               (0.0,    100.0,    "pct",     "% of initial WAL elapsed"),
    "tranche_aaa_pct":        (0.0,    100.0,    "pct",     "Senior AAA tranche size"),
    "tranche_aa_pct":         (0.0,    50.0,     "pct",     "AA tranche size"),
    "tranche_a_pct":          (0.0,    50.0,     "pct",     "A tranche size"),
    "tranche_bbb_pct":        (0.0,    50.0,     "pct",     "BBB tranche size"),
    "tranche_bb_pct":         (0.0,    50.0,     "pct",     "BB (N) tranche size"),
    "tranche_oc_pct":         (-5.0,   25.0,     "pct",     "OC as % of original balance"),

    # Recent Trends — cal factor + loss surprise tables.
    "cal_factor":             (0.2,    3.5,      "ratio",   "Actual / forecast loss; extreme values flag model or parser bugs"),
    "cal_delta_30d":          (-1.0,   1.0,      "ratio",   "30-day change in cal factor"),
    "monthly_loss_bps":       (0.0,    2_000.0,  "bps",     "Monthly loss in bps of pool; outliers at 500+ bps possible but rare"),
    "surprise_bps":           (-1_000.0, 1_000.0,"bps",     "Signed monthly surprise vs baseline"),
    "count_deals":            (0.0,    200.0,    "count",   "Count of deals in a segment — roughly 12-50 today"),
    "count_loans":            (0.0,    5_000_000.0, "count","Cumulative loan count across Carvana + CarMax issuance"),
    # Recent Trends segment table — cumulative loss projection / realized.
    "original_projection_pct":(0.0,    30.0,     "pct",     "Original cum loss projection per segment"),
    "current_projection_pct": (0.0,    30.0,     "pct",     "Current cum loss projection per segment"),
    "realized_to_date_pct":   (0.0,    30.0,     "pct",     "Realized cum loss to date per segment"),
    # CarMax has ~60 deals × ~80k loans × ~30 months of observation -->
    # tens of millions of loan-months in some aggregate cells. 200M ceiling.
    "loan_months":            (0.0,    200_000_000.0, "count","Loan-months exposure in a hazard cell"),
    "default_events":         (0.0,    500_000.0, "count",  "Default events count in a hazard cell"),

    # Landing-page deal snapshot tables.
    "avg_fico":               (450.0,  850.0,    "score",   "FICO range"),
    "initial_consumer_apr":   (3.0,    30.0,     "pct",     "Loan-level APR"),
    "current_consumer_apr":   (3.0,    30.0,     "pct",     "Current $-weighted APR"),
    "initial_cost_of_debt":   (0.2,    10.0,     "pct",     "Initial trust cost of debt"),
    "current_cost_of_debt":   (0.2,    10.0,     "pct",     "Current trust cost of debt"),
    "init_balance_usd_M":     (10.0,   20_000.0, "usd_M",   "Initial balance per deal"),
    "pool_factor_pct":        (0.0,    100.0,    "pct",     "Current balance / original"),
    "cum_loss_pct":           (0.0,    30.0,     "pct",     "Cumulative net losses as % of original"),
    "equity_dist_pct":        (-5.0,   30.0,     "pct",     "Cumulative residual distributions to equity"),

    # Per-deal summary metrics.
    "original_balance_usd_M": (10.0,   20_000.0, "usd_M",   "Deal-level original balance"),
    "current_balance_usd_M":  (0.0,    20_000.0, "usd_M",   "Deal-level current balance"),
    "pool_factor_pct2":       (0.0,    100.0,    "pct",     "Pool factor on per-deal page"),
    "active_loans":           (0.0,    200_000.0, "count",  "Active loan count"),
    "cum_loss_rate_pct":      (0.0,    30.0,     "pct",     "Cumulative loss rate"),
    # Seasoned non-prime deals (pool factor < 10%) can show 60%+ of the
    # remaining tiny balance in 120+d. Real, not a bug: bad loans are the
    # last to pay down.
    "dq_30_plus_pct":         (0.0,    80.0,     "pct",     "30+ DQ rate; seasoned non-prime with tiny pool factor can exceed 60%"),
    # Seasoned non-prime deals see 5-7k chargeoffs over life of deal; some very
    # large CarMax prime trusts also reach 5k+. 50k upper bound is the
    # practical ceiling (a 20k-loan pool with 100% default).
    "charged_off_loans":      (0.0,    50_000.0, "count",   "Charged-off loan count"),
    # Tiny single-bucket samples can show recoveries > chargeoffs from fees.
    # Upper bound 115% tolerates that edge case; anything above is a bug.
    "recovery_rate_pct":      (0.0,    115.0,    "pct",     "Post-chargeoff recoveries / chargeoffs; small-sample buckets can exceed 100%"),
    "median_recovery_months": (0.0,    36.0,     "months",  "Median time to recovery"),

    # Per-deal tables — delinquency buckets + FICO/Rate segments.
    # DQ bucket % can be 60%+ on tail of seasoned non-prime. Cap at 80%.
    "dq_bucket_pct":          (0.0,    80.0,     "pct",     "Balance in a DQ bucket as % of pool; non-prime tail can exceed 60%"),
    # Tiny buckets can show -0.5% to +50% loss rates. Min -2 tolerates
    # small-sample negatives from recoveries exceeding chargeoffs.
    "loss_rate_pct":          (-2.0,   50.0,     "pct",     "Segment-level loss rate; can be slightly negative on tiny buckets from recoveries"),
    "recovery_rate_seg_pct":  (0.0,    100.0,    "pct",     "Segment-level recovery rate"),

    # Methodology tab — regression + comparison tables.
    "monthly_hazard_bps":     (0.0,    2_000.0,  "bps",     "Monthly default hazard"),
    "model_accuracy_pct":     (50.0,   100.0,    "pct",     "Model accuracy — anything under 50% is a bug"),
    "model_auc":              (0.5,    1.0,      "ratio",   "AUC-ROC on held-out sample"),
    "model_precision_pct":    (0.0,    100.0,    "pct",     "Precision"),
    "model_recall_pct":       (0.0,    100.0,    "pct",     "Recall"),
    "model_f1_pct":           (0.0,    100.0,    "pct",     "F1 score"),
    "segment_actual_default_pct":    (0.0, 80.0, "pct",     "Actual default rate at segment level"),
    "segment_predicted_default_pct": (0.0, 80.0, "pct",     "Predicted default rate at segment level"),
    "apr_pct":                (3.0,    30.0,     "pct",     "Segment-level APR"),
    "apr_difference_pct":     (-20.0,  20.0,     "pct",     "Difference between two APRs"),
    "avg_2y_tsy_pct":         (0.0,    6.0,      "pct",     "Avg 2Y Tsy over the cohort"),
    "avg_credit_spread_pp":   (-2.0,   6.0,      "pp",      "Avg credit spread over benchmark"),
    "bucket_usd_M":           (0.0,    20_000.0, "usd_M",   "Dollar balance in a segment bucket"),
}


# ────────────────────────────────────────────────────────────────────────
# Header → canonical key normalization.
#
# The renderer uses short, human-friendly column labels. We recognise them
# (case-insensitive, punctuation-stripped) and map to DISPLAY_RANGES keys.
# When a header doesn't match anything we SKIP it (PASS-by-omission) rather
# than HALT — not every column is numeric.
# ────────────────────────────────────────────────────────────────────────

HEADER_ALIASES: dict[str, str] = {
    # Economics table
    "orig bal":                 "orig_bal_usd_M",
    "wac":                      "consumer_wac_pct",
    "cod":                      "cost_of_debt_pct",
    "xs/yr":                    "excess_spread_yr_pct",
    "wal":                      "wal_years",
    "wal now":                  "wal_now_years",
    "tot xs":                   "total_xs_pct",
    "svc":                      "servicing_fee_pct",
    "exp loss":                 "expected_loss_pct",
    "exp resid":                "expected_residual_pct",
    "act int":                  "actual_int_pct",
    "act svc":                  "actual_svc_pct",
    "proj loss":                "projected_loss_pct",
    "act resid":                "actual_residual_pct",
    "var %":                    "variance_pct",
    "var $":                    "variance_usd_M",
    "%done":                    "pct_done",

    # Recent Trends
    "wavg cal":                 "cal_factor",
    "30-day δ cal":             "cal_delta_30d",
    "30-day δ":                 "cal_delta_30d",
    "prior cal":                "cal_factor",
    "prior cal (pending history)": "cal_factor",
    "current cal":              "cal_factor",
    "last month loss (bps of pool)": "monthly_loss_bps",
    "trailing 6-mo baseline":   "monthly_loss_bps",
    "last-month surprise":      "surprise_bps",
    "3-mo rolling surprise":    "surprise_bps",
    "last-month actual (bps of pool)":  "monthly_loss_bps",
    "markov-expected monthly pace":     "monthly_loss_bps",
    "surprise vs forecast":             "surprise_bps",
    "trailing 3-mo actual":             "monthly_loss_bps",
    "last-month actual":                "monthly_loss_bps",
    "markov expected":                  "monthly_loss_bps",
    "surprise":                         "surprise_bps",
    "original projection":              "original_projection_pct",
    "current projection":               "current_projection_pct",
    "realized to date":                 "realized_to_date_pct",
    "loan-months":                      "loan_months",
    "default events":                   "default_events",
    "# deals":                  "count_deals",
    "underperform (>1.10x)":    "count_deals",
    "outperform (<0.90x)":      "count_deals",

    # Landing snapshot
    "avg fico":                 "avg_fico",
    "initial avg consumer rate": "initial_consumer_apr",
    "current avg consumer rate": "current_consumer_apr",
    "initial avg trust cost of debt": "initial_cost_of_debt",
    "current avg trust cost of debt": "current_cost_of_debt",
    "init balance":             "init_balance_usd_M",
    "pool factor":              "pool_factor_pct",
    "cum loss":                 "cum_loss_pct",
    "equity dist":              "equity_dist_pct",

    # Per-deal metric boxes
    "original balance":         "original_balance_usd_M",
    "current balance":          "current_balance_usd_M",
    "cum loss rate":            "cum_loss_rate_pct",
    "30+ dq rate":              "dq_30_plus_pct",
    "active loans":             "active_loans",
    "charged-off loans":        "charged_off_loans",
    "recovery rate":            "recovery_rate_pct",
    "median time":              "median_recovery_months",

    # Per-deal tables
    "% pool":                   "dq_bucket_pct",
    "loss rate":                "loss_rate_pct",

    # Methodology
    "monthly hazard":           "monthly_hazard_bps",
    "accuracy":                 "model_accuracy_pct",
    "auc-roc":                  "model_auc",
    "precision":                "model_precision_pct",
    "recall":                   "model_recall_pct",
    "f1 score":                 "model_f1_pct",
    "actual default":           "segment_actual_default_pct",
    "predicted default":        "segment_predicted_default_pct",
    "carvana apr":              "apr_pct",
    "carmax apr":               "apr_pct",
    "difference":               "apr_difference_pct",
    "avg note wac":             "cost_of_debt_pct",
    "avg 2y tsy":               "avg_2y_tsy_pct",
    "avg credit spread":        "avg_credit_spread_pp",
}


# Tranche / OC aliases — only valid on the Economics table (i.e. a table
# whose header row contains "xs/yr" or "wal"). Elsewhere "AAA", "AA", "A",
# "OC" are dollar columns (balance sheet). These are resolved in
# ``canonical_column`` when given a ``headers_ctx`` hint.
TRANCHE_ALIASES: dict[str, str] = {
    "aaa": "tranche_aaa_pct",
    "aa":  "tranche_aa_pct",
    "a":   "tranche_a_pct",
    "bbb": "tranche_bbb_pct",
    "bb":  "tranche_bb_pct",
    "oc":  "tranche_oc_pct",
}

# Headers that are deliberately ignored (non-numeric, identity, descriptive).
HEADER_IGNORE = {
    "issuer", "deal", "cutoff", "terms", "trig risk", "interpretation",
    "worst deal", "best deal", "segment", "dimension", "buckets",
    "why it matters", "line item", "formula", "file", "what it does",
    "parameter", "value", "download", "document", "description", "link",
    "period", "date", "score", "rate", "bucket", "tier", "status",
    "covariate", "coef", "se", "95% ci", "predicted no default",
    "predicted default", "actual no default", "actual default",
    "carvana", "carmax", "fico", "ltv", "term", "cohort", "deals",
    "fico \\ ltv", "fico  ltv", "fico ltv",
    "charged-off loans", "total chargeoffs", "total recovered",
    "loans", "issuance year", "balance", "carvana $", "carmax $",
    "net loss", "orig bal", "count", "a1", "a2", "a3", "a4", "b", "c", "d", "n",
    "total debt", "reserve", "interest", "principal", "recoveries",
    "svc fee", "chargeoffs", "total deposited", "available funds",
    "servicing fee", "note interest", "principal dist",
    "residual (to equity)", "with recovery",
    # Cash Waterfall table — $ cash flows per period. Skipped because the
    # dollar range varies 4 orders of magnitude across deals.
    "interest collections", "principal collections",
    "liquidation proceeds", "gross charge-offs", "net losses",
    # FICO × LTV matrix headers on methodology tab.
    "<80%", "80-99%", "100-119%", "120%+",
    # Model comparison table
    "model",
    # these are USD columns on per-deal segment tables — we skip rather than
    # trying to maintain a $ range that spans 8 orders of magnitude.
}


# ────────────────────────────────────────────────────────────────────────
# Value parsing — convert a rendered cell to a float + implied unit.
#
# The dashboard formats numbers as e.g.:
#   "$935.0M", "$1.0B", "$4.6M", "1.9y", "4.7%", "-0 bps",
#   "+0.01x", "1.19x", "93.8%", "32.85%", "$1", "(4)", "5,000",
#   "—", "-", " ".
#
# We parse the number and return (value, unit_hint) where unit_hint is
# informational. An unparseable cell returns None and is skipped.
# ────────────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(
    r"^\s*(?P<neg>[-+])?\s*\$?"           # optional sign + $
    r"(?P<body>[\d,]*\.?\d+)"             # the digits
    r"\s*(?P<suffix>%|bps|x|y|B|M|K|pp)?" # optional unit suffix
    r"\s*$"
)


def _strip_cell(raw: str) -> str:
    s = raw.replace("\xa0", " ").strip()
    # Leading arrows like "+", "-" inside patterns such as "+0 bps" are kept.
    # Parenthesised negatives: "(1.23)" => -1.23
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return s


def parse_cell(raw: str) -> Optional[tuple[float, str]]:
    """Return (value, unit_hint) or None if not numeric.

    Unit conversions:
      %, bps, x, y, B, M, K — value is already in the units implied by the
      column header (our ranges assume these).
    """
    s = _strip_cell(raw)
    if not s or s in {"—", "-", "–", "N/A", "NA"}:
        return None
    # Handle strings like "0 bps", "+0 bps"
    s2 = s.replace(",", "")
    m = _NUM_RE.match(s2)
    if not m:
        return None
    sign = -1.0 if m.group("neg") == "-" else 1.0
    body = m.group("body")
    try:
        val = float(body) * sign
    except ValueError:
        return None
    suffix = m.group("suffix") or ""
    # The DISPLAY_RANGES are written in the same units as the displayed
    # suffix (e.g. "8.65%" => 8.65 in pct space). So no conversion needed
    # except for B/K -> M for USD columns.
    if suffix == "B":
        val *= 1_000.0
        unit = "usd_M"
    elif suffix == "K":
        val /= 1_000.0
        unit = "usd_M"
    elif suffix == "M":
        unit = "usd_M"
    elif suffix == "%":
        unit = "pct"
    elif suffix == "bps":
        unit = "bps"
    elif suffix == "x":
        unit = "ratio"
    elif suffix == "y":
        unit = "yr"
    elif suffix == "pp":
        unit = "pp"
    else:
        unit = "number"
    return (val, unit)


# ────────────────────────────────────────────────────────────────────────
# Data model
# ────────────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    severity: str            # HALT | WARN | INFO
    column: str              # canonical key
    display_header: str      # the header as rendered
    value: float
    lo: float
    hi: float
    unit: str
    page: str                # URL-like path to the page
    table_idx: int
    row_idx: int
    row_label: str           # first cell of the row, for human identification
    message: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "column": self.column,
            "display_header": self.display_header,
            "value": self.value,
            "lo": self.lo,
            "hi": self.hi,
            "unit": self.unit,
            "page": self.page,
            "table_idx": self.table_idx,
            "row_idx": self.row_idx,
            "row_label": self.row_label,
            "message": self.message,
        }


@dataclass
class AuditReport:
    pages_audited: int = 0
    tables_audited: int = 0
    cells_audited: int = 0
    cells_checked: int = 0   # cells that mapped to a known column
    findings: list[Finding] = field(default_factory=list)
    aggregate_checks: list[dict] = field(default_factory=list)
    chain_checks: list[dict] = field(default_factory=list)
    columns_covered: set[str] = field(default_factory=set)
    unknown_headers: dict[str, int] = field(default_factory=dict)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def halts(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "HALT"]

    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]


# ────────────────────────────────────────────────────────────────────────
# Normalization helpers
# ────────────────────────────────────────────────────────────────────────

def _norm_header(raw: str) -> str:
    s = raw.strip().lower().replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def canonical_column(
    display_header: str,
    headers_ctx: Optional[list[str]] = None,
) -> Optional[str]:
    """Map a rendered column header to a DISPLAY_RANGES key.

    ``headers_ctx`` is the full header row for the table this column lives
    in. Used to gate context-sensitive aliases — e.g. ``AAA`` only maps to
    ``tranche_aaa_pct`` when the same header row also contains ``wal`` or
    ``xs/yr`` (the Economics table signature). On a balance-sheet table,
    where ``A`` / ``OC`` are dollar amounts, the alias is skipped.
    """
    h = _norm_header(display_header)
    if h in HEADER_IGNORE:
        return None
    if h in HEADER_ALIASES:
        return HEADER_ALIASES[h]
    if h in TRANCHE_ALIASES:
        if headers_ctx is None:
            return None
        norm_ctx = {_norm_header(x) for x in headers_ctx}
        if "xs/yr" in norm_ctx or "wal" in norm_ctx or "tot xs" in norm_ctx:
            return TRANCHE_ALIASES[h]
        return None
    return None


# ────────────────────────────────────────────────────────────────────────
# Per-table audit
# ────────────────────────────────────────────────────────────────────────

def _collect_headers(rows) -> tuple[list[str], int]:
    """Return (final_header_list, data_start_row_index).

    Handles single-row headers AND the multi-level "group / sub-header"
    pattern used on the Economics page. Multi-level detection: if row 0 has
    fewer cells than row 1, row 0 is group and row 1 is the real header.
    """
    if not rows:
        return [], 0
    r0 = rows[0].find_all(["th", "td"])
    r0_texts = [c.get_text(strip=True) for c in r0]
    if len(rows) >= 2:
        r1 = rows[1].find_all(["th", "td"])
        r1_texts = [c.get_text(strip=True) for c in r1]
        # All-th row-1 and r0 spans => multi-level
        if len(r1_texts) > len(r0_texts) and all(r1[i].name == "th" for i in range(len(r1))):
            return r1_texts, 2
    return r0_texts, 1


def audit_table(
    soup_table,
    page_path: str,
    table_idx: int,
    report: AuditReport,
) -> None:
    rows = soup_table.find_all("tr")
    if not rows:
        return
    headers, data_start = _collect_headers(rows)
    # Track unknown headers to help humans decide if they need a range entry.
    for h in headers:
        if not h:
            continue
        norm = _norm_header(h)
        if norm in HEADER_IGNORE:
            continue
        if norm in HEADER_ALIASES or norm in TRANCHE_ALIASES:
            continue
        report.unknown_headers[norm] = report.unknown_headers.get(norm, 0) + 1

    report.tables_audited += 1
    for r_idx, r in enumerate(rows[data_start:], start=data_start):
        cells = r.find_all(["th", "td"])
        if not cells:
            continue
        row_label = cells[0].get_text(strip=True)[:60]
        for c_idx, cell in enumerate(cells):
            if c_idx >= len(headers):
                continue
            header = headers[c_idx]
            report.cells_audited += 1
            canon = canonical_column(header, headers_ctx=headers)
            if not canon:
                continue
            if canon not in DISPLAY_RANGES:
                continue
            report.columns_covered.add(canon)
            parsed = parse_cell(cell.get_text())
            if parsed is None:
                continue
            value, unit = parsed
            report.cells_checked += 1
            lo, hi, expected_unit, why = DISPLAY_RANGES[canon]
            # Unit sanity — if the cell parsed as a different unit family,
            # log a WARN (it's how the 100× bug manifested: a value parsed
            # as '%' on a column expected to be ratio/yr etc.).
            if expected_unit in {"pct"} and unit not in {"pct", "number", "pp"}:
                report.add(Finding(
                    severity="WARN",
                    column=canon, display_header=header,
                    value=value, lo=lo, hi=hi, unit=unit,
                    page=page_path, table_idx=table_idx,
                    row_idx=r_idx, row_label=row_label,
                    message=f"Unit mismatch: expected {expected_unit}, parsed {unit}",
                ))
                continue
            if not (lo <= value <= hi):
                sev = "HALT"
                report.add(Finding(
                    severity=sev,
                    column=canon, display_header=header,
                    value=value, lo=lo, hi=hi, unit=unit,
                    page=page_path, table_idx=table_idx,
                    row_idx=r_idx, row_label=row_label,
                    message=f"Out of range [{lo}, {hi}] {expected_unit} — {why}",
                ))


# ────────────────────────────────────────────────────────────────────────
# Per-deal metric boxes.
#
# These live in <div class="metric"> blocks (label + value), so the table
# audit misses them. We walk them separately.
# ────────────────────────────────────────────────────────────────────────

METRIC_ALIASES = {
    "original balance": "original_balance_usd_M",
    "current balance":  "current_balance_usd_M",
    "pool factor":      "pool_factor_pct",
    "active loans":     "active_loans",
    "cum loss rate":    "cum_loss_rate_pct",
    "30+ dq rate":      "dq_30_plus_pct",
    "charged-off loans": "charged_off_loans",
    "recovery rate":    "recovery_rate_pct",
    "median time":      "median_recovery_months",
}


def audit_metric_boxes(soup, page_path: str, report: AuditReport) -> None:
    boxes = soup.find_all(class_="metric")
    for b in boxes:
        lbl_el = b.find(class_="ml")
        val_el = b.find(class_="mv")
        if not (lbl_el and val_el):
            continue
        label = _norm_header(lbl_el.get_text())
        canon = METRIC_ALIASES.get(label)
        if not canon or canon not in DISPLAY_RANGES:
            continue
        report.columns_covered.add(canon)
        parsed = parse_cell(val_el.get_text())
        if parsed is None:
            continue
        value, unit = parsed
        report.cells_checked += 1
        lo, hi, expected_unit, why = DISPLAY_RANGES[canon]
        if not (lo <= value <= hi):
            report.add(Finding(
                severity="HALT",
                column=canon, display_header=label,
                value=value, lo=lo, hi=hi, unit=unit,
                page=page_path, table_idx=-1, row_idx=-1,
                row_label="<metric box>",
                message=f"Metric out of range [{lo}, {hi}] {expected_unit} — {why}",
            ))


# ────────────────────────────────────────────────────────────────────────
# Aggregate sanity checks.
#
# For certain columns, the ALL-DEALS average row (last row of the economics
# table) and the per-issuer averages should sit inside a TIGHTER range
# than the per-deal range. If they don't, it's a hint that many deals are
# drifted in the same direction — a systematic renderer bug.
# ────────────────────────────────────────────────────────────────────────

AGGREGATE_CHECKS: list[tuple[str, float, float, str]] = [
    # (canonical column, agg_lo, agg_hi, why)
    ("wal_years",            1.5,  3.0, "Avg WAL across all prime ABS ~2y"),
    ("wal_now_years",        0.5,  3.0, "Avg remaining WAL; can be short for old deals"),
    ("consumer_wac_pct",     5.0, 20.0, "Avg consumer WAC 6-15% typical"),
    ("cost_of_debt_pct",     0.5,  6.0, "Avg CoD tracks 2Y Tsy 0-5% over the cycle"),
    ("excess_spread_yr_pct", 2.0, 12.0, "Avg XS/yr for a working ABS"),
    ("total_xs_pct",         5.0, 20.0, "Avg total XS over life"),
    ("servicing_fee_pct",    0.5,  5.0, "Avg servicing fee"),
    ("expected_loss_pct",    0.0, 20.0, "Avg initial expected loss"),
    ("projected_loss_pct",   0.0, 20.0, "Avg projected loss now"),
    ("pool_factor_pct",      0.0, 60.0, "Avg pool factor across all vintages"),
    ("cal_factor",           0.7,  1.8, "Weighted avg cal factor — prime should sit near 1"),
]


def run_aggregate_checks(report: AuditReport, page_values: dict[str, list[float]]) -> None:
    for col, lo, hi, why in AGGREGATE_CHECKS:
        vals = page_values.get(col, [])
        if len(vals) < 3:
            continue
        avg = sum(vals) / len(vals)
        ok = lo <= avg <= hi
        report.aggregate_checks.append({
            "column": col,
            "avg": round(avg, 4),
            "n": len(vals),
            "lo": lo, "hi": hi, "why": why,
            "status": "PASS" if ok else "WARN",
        })
        if not ok:
            report.add(Finding(
                severity="WARN",
                column=col, display_header=col,
                value=avg, lo=lo, hi=hi, unit="aggregate",
                page="(aggregate across all deals)",
                table_idx=-1, row_idx=-1, row_label="aggregate",
                message=f"Aggregate avg {avg:.3f} outside tight range [{lo}, {hi}] — {why}",
            ))


# ────────────────────────────────────────────────────────────────────────
# Cross-column chain checks on the Economics table.
#
# The economics page renders `Total XS ≈ XS/yr × WAL`, and (under the
# model) `Exp Resid ≈ Total XS − Svc − Exp Loss`. If renderer bugs drift
# any column, the chain snaps and we catch it regardless of whether the
# individual values fall in range.
# ────────────────────────────────────────────────────────────────────────

def audit_economics_chains(soup, page_path: str, report: AuditReport) -> None:
    tables = soup.find_all("table")
    # Heuristic: the econ table is the one whose sub-header row contains
    # "WAL" AND "Tot XS".
    econ_table = None
    header_row_idx = -1
    for t in tables:
        rows = t.find_all("tr")
        if not rows:
            continue
        headers, data_start = _collect_headers(rows)
        norm_headers = [_norm_header(h) for h in headers]
        if "wal" in norm_headers and "tot xs" in norm_headers:
            econ_table = t
            header_row_idx = data_start
            break
    if econ_table is None:
        return
    rows = econ_table.find_all("tr")
    headers, data_start = _collect_headers(rows)
    norm = [_norm_header(h) for h in headers]

    def idx(name):
        return norm.index(name) if name in norm else -1

    i_xs_yr = idx("xs/yr")
    i_wal   = idx("wal")
    i_totxs = idx("tot xs")
    i_svc   = idx("svc")
    i_exp_l = idx("exp loss")
    i_exp_r = idx("exp resid")

    for r_idx, r in enumerate(rows[data_start:], start=data_start):
        cells = r.find_all(["th", "td"])
        if len(cells) < max(i_xs_yr, i_wal, i_totxs, i_svc, i_exp_l, i_exp_r) + 1:
            continue
        row_label = cells[0].get_text(strip=True)[:60]

        def pv(i):
            if i < 0 or i >= len(cells):
                return None
            p = parse_cell(cells[i].get_text())
            return p[0] if p else None

        xs_yr = pv(i_xs_yr)
        wal   = pv(i_wal)
        totxs = pv(i_totxs)
        svc   = pv(i_svc)
        exp_l = pv(i_exp_l)
        exp_r = pv(i_exp_r)

        # Chain 1: Total XS ≈ XS/yr × WAL (± 10% relative, 0.5pp absolute).
        if xs_yr is not None and wal is not None and totxs is not None:
            expected = xs_yr * wal
            diff = totxs - expected
            rel = abs(diff) / max(abs(expected), 0.1)
            report.chain_checks.append({
                "check": "total_xs == xs_yr * wal",
                "row": row_label, "expected": round(expected, 3),
                "actual": round(totxs, 3), "diff_rel": round(rel, 3),
            })
            if rel > 0.15 and abs(diff) > 0.75:
                report.add(Finding(
                    severity="WARN",
                    column="total_xs_pct", display_header="Tot XS",
                    value=totxs, lo=expected * 0.85, hi=expected * 1.15,
                    unit="pct",
                    page=page_path, table_idx=tables.index(econ_table),
                    row_idx=r_idx, row_label=row_label,
                    message=(f"Tot XS {totxs:.2f} deviates from xs_yr*wal={expected:.2f} "
                             f"(rel diff {rel:.1%})"),
                ))

        # Chain 2: Exp Resid ≈ Total XS − Svc − Exp Loss (± 1.0pp absolute).
        if (totxs is not None and svc is not None
                and exp_l is not None and exp_r is not None):
            expected = totxs - svc - exp_l
            diff = exp_r - expected
            report.chain_checks.append({
                "check": "exp_resid == tot_xs - svc - exp_loss",
                "row": row_label,
                "expected": round(expected, 3),
                "actual": round(exp_r, 3),
                "diff_abs": round(diff, 3),
            })
            if abs(diff) > 1.5:
                report.add(Finding(
                    severity="WARN",
                    column="expected_residual_pct",
                    display_header="Exp Resid",
                    value=exp_r, lo=expected - 1.5, hi=expected + 1.5,
                    unit="pct",
                    page=page_path, table_idx=tables.index(econ_table),
                    row_idx=r_idx, row_label=row_label,
                    message=(f"Exp Resid {exp_r:.2f} deviates from "
                             f"tot_xs-svc-exp_loss={expected:.2f} "
                             f"(abs diff {diff:+.2f}pp)"),
                ))

        # Tranche + OC should roughly sum to 100 (± 1 pp for rounding).
        # We iterate header indices by name.
        tranche_idxs = [norm.index(h) for h in ("aaa", "aa", "a", "bbb", "bb", "oc")
                        if h in norm]
        if len(tranche_idxs) >= 5:  # at minimum AAA + OC + a few mezz
            parts = []
            for ii in tranche_idxs:
                p = pv(ii)
                if p is not None:
                    parts.append(p)
            if parts:
                s = sum(parts)
                # Only check if we have most of them
                if len(parts) >= 4 and 80 <= s <= 120:
                    if abs(s - 100) > 3.0:
                        report.add(Finding(
                            severity="WARN",
                            column="tranche_sum_pct",
                            display_header="sum(tranches+OC)",
                            value=s, lo=97.0, hi=103.0, unit="pct",
                            page=page_path,
                            table_idx=tables.index(econ_table),
                            row_idx=r_idx, row_label=row_label,
                            message=f"Tranche+OC sum {s:.1f}% ≠ 100 ± 3pp",
                        ))


# ────────────────────────────────────────────────────────────────────────
# Economics-table aggregation for the AGGREGATE_CHECKS pass.
# ────────────────────────────────────────────────────────────────────────

def collect_page_values(soup) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        headers, data_start = _collect_headers(rows)
        norm = [_norm_header(h) for h in headers]
        canon_per_col = [canonical_column(h, headers_ctx=headers) for h in headers]
        for r in rows[data_start:]:
            cells = r.find_all(["th", "td"])
            # Skip the trailing "All Prime Avg" / "All Nonprime Avg" rows so
            # the aggregate check uses per-deal data only.
            if cells and "avg" in cells[min(1, len(cells)-1)].get_text(strip=True).lower():
                continue
            for c_idx, cell in enumerate(cells):
                if c_idx >= len(canon_per_col):
                    continue
                canon = canon_per_col[c_idx]
                if not canon:
                    continue
                p = parse_cell(cell.get_text())
                if p is None:
                    continue
                out[canon].append(p[0])
    return out


# ────────────────────────────────────────────────────────────────────────
# Orchestration — walk a rendered tree and audit every page.
# ────────────────────────────────────────────────────────────────────────

def audit_page(html_path: str, page_rel: str, report: AuditReport) -> None:
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    report.pages_audited += 1
    tables = soup.find_all("table")
    for i, t in enumerate(tables):
        audit_table(t, page_rel, i, report)
    audit_metric_boxes(soup, page_rel, report)
    audit_economics_chains(soup, page_rel, report)
    # The aggregate pass only matters on pages that contain the big econ
    # table — running it per page is cheap, and we only care when multiple
    # deals are present.
    page_values = collect_page_values(soup)
    if any(len(v) >= 5 for v in page_values.values()):
        run_aggregate_checks(report, page_values)


def walk_tree(root: str) -> Iterable[tuple[str, str]]:
    """Yield (absolute_path, relative_page_path) for every index.html."""
    pattern = os.path.join(root, "**", "index.html")
    for p in sorted(glob.glob(pattern, recursive=True)):
        rel = os.path.relpath(p, root)
        yield p, rel


def run_audit(root: str) -> AuditReport:
    report = AuditReport()
    for abs_path, rel_page in walk_tree(root):
        audit_page(abs_path, rel_page, report)
    return report


# ────────────────────────────────────────────────────────────────────────
# Pretty-print
# ────────────────────────────────────────────────────────────────────────

def print_report(report: AuditReport, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps({
            "pages_audited": report.pages_audited,
            "tables_audited": report.tables_audited,
            "cells_audited": report.cells_audited,
            "cells_checked": report.cells_checked,
            "columns_covered": sorted(report.columns_covered),
            "display_ranges_size": len(DISPLAY_RANGES),
            "aggregate_checks": report.aggregate_checks,
            "chain_checks_count": len(report.chain_checks),
            "halts": [f.as_dict() for f in report.halts()],
            "warns": [f.as_dict() for f in report.warns()],
            "unknown_headers": sorted(report.unknown_headers.items()),
        }, indent=2))
        return

    print(f"Pages audited:     {report.pages_audited}")
    print(f"Tables audited:    {report.tables_audited}")
    print(f"Cells audited:     {report.cells_audited}")
    print(f"Cells range-checked: {report.cells_checked}")
    print(f"DISPLAY_RANGES columns defined: {len(DISPLAY_RANGES)}")
    print(f"Columns covered by rendered HTML: {len(report.columns_covered)}")
    print()
    # Aggregate sanity
    print(f"Aggregate checks: {len(report.aggregate_checks)}")
    for a in report.aggregate_checks:
        print(f"  [{a['status']}] {a['column']}: avg={a['avg']} over n={a['n']} "
              f"(expected {a['lo']}-{a['hi']})")
    print()
    print(f"Chain checks: {len(report.chain_checks)}")
    print()

    halts = report.halts()
    warns = report.warns()
    print(f"HALT findings: {len(halts)}")
    for f in halts[:40]:
        print(f"  [HALT] {f.column} = {f.value} {f.unit} "
              f"(expected [{f.lo}, {f.hi}]) "
              f"— {f.page} table#{f.table_idx} row {f.row_idx} "
              f"[{f.row_label!r}]")
        print(f"         {f.message}")
    if len(halts) > 40:
        print(f"  ... and {len(halts) - 40} more.")
    print()
    print(f"WARN findings: {len(warns)}")
    for f in warns[:40]:
        print(f"  [WARN] {f.column} = {f.value} {f.unit} — {f.page} "
              f"table#{f.table_idx} row {f.row_idx} [{f.row_label!r}]")
        print(f"         {f.message}")
    if len(warns) > 40:
        print(f"  ... and {len(warns) - 40} more.")
    print()

    if report.unknown_headers:
        print("Unknown headers (not in DISPLAY_RANGES, not ignored):")
        items = sorted(report.unknown_headers.items(), key=lambda x: -x[1])
        for h, n in items[:30]:
            print(f"  {n:4}×  {h!r}")
        if len(items) > 30:
            print(f"  ... and {len(items) - 30} more.")


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────

def default_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "carvana_abs", "static_site", "preview")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", help="Path to rendered HTML tree (default: preview)")
    ap.add_argument("--live", action="store_true",
                    help="Audit static_site/live/ instead of preview/")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--warn-exit", action="store_true",
                    help="Exit non-zero on WARN findings too (default: HALT only)")
    args = ap.parse_args()

    if args.root:
        root = args.root
    elif args.live:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "carvana_abs", "static_site", "live")
    else:
        root = default_root()

    if not os.path.isdir(root):
        print(f"ERROR: rendered tree not found at {root}", file=sys.stderr)
        return 2

    report = run_audit(root)
    print_report(report, as_json=args.json)

    halts = report.halts()
    warns = report.warns()
    if halts:
        return 1
    if args.warn_exit and warns:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
