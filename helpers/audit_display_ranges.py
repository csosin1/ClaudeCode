"""
audit_display_ranges.py - shared helper for Phase 5 of SKILLS/data-audit-qa.md.

Validates every rendered cell of a user-facing tab/report against a
DISPLAY_RANGES dict defined per project. Supports two severity tiers
(HALT, WARN) and optional aggregate-sanity bounds.

Usage (from a project's regen / promote script):

    from audit_display_ranges import (
        audit_rendered_data, audit_aggregates, DisplayAuditHalt,
    )

    findings = audit_rendered_data(
        rendered_rows=[{...}, {...}],   # list of dicts keyed by column name
        ranges=DISPLAY_RANGES,           # schema per SKILLS/data-audit-qa.md
        row_key_field="deal",            # which field identifies the row
    )
    findings += audit_aggregates(rendered_rows, DISPLAY_RANGES)

    halt = [f for f in findings if f["severity"] == "HALT"]
    warn = [f for f in findings if f["severity"] == "WARN"]

    if halt:
        raise DisplayAuditHalt(halt)
    if warn:
        # fire notify.sh default priority, log, continue
        ...

No deps beyond stdlib. Handles None values by skipping them (missing
data is Phase 1's surface, not Phase 5's).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional


class DisplayAuditHalt(Exception):
    """Raised when HALT-severity findings are present. Callers catch + handle."""

    def __init__(self, findings: list[dict]):
        self.findings = findings
        super().__init__(
            f"{len(findings)} HALT finding(s) in display audit; "
            f"first: {findings[0] if findings else 'n/a'}"
        )


def _finding(severity, column, row_key, value, bounds, spec, kind="cell"):
    return {
        "severity": severity,
        "column": column,
        "row_key": row_key,
        "value": value,
        "bounds": bounds,
        "provenance": spec.get("provenance", ""),
        "rationale": spec.get("rationale", ""),
        "kind": kind,
    }


def audit_rendered_data(
    rendered_rows: Iterable[Mapping[str, Any]],
    ranges: Mapping[str, Mapping[str, Any]],
    row_key_field: str = "id",
) -> list[dict]:
    """Per-cell bounds check. Returns list of findings."""
    findings: list[dict] = []
    for row in rendered_rows:
        rk = row.get(row_key_field, "<unknown>")
        for column, spec in ranges.items():
            if column not in row:
                continue
            value = row[column]
            if value is None:
                continue  # missing data is Phase 1's job
            lo, hi = spec["bounds"]
            if not (lo <= value <= hi):
                findings.append(
                    _finding(spec["severity"], column, rk, value, (lo, hi), spec)
                )
    return findings


def audit_aggregates(
    rendered_rows: Iterable[Mapping[str, Any]],
    ranges: Mapping[str, Mapping[str, Any]],
    weight_field: Optional[str] = None,
) -> list[dict]:
    """For each column with agg_bounds, compute weighted-or-simple avg; flag if outside."""
    rows = list(rendered_rows)
    findings: list[dict] = []
    for column, spec in ranges.items():
        agg = spec.get("agg_bounds")
        if not agg:
            continue
        lo, hi = agg
        num = 0.0
        den = 0.0
        for row in rows:
            v = row.get(column)
            if v is None:
                continue
            w = row.get(weight_field, 1.0) if weight_field else 1.0
            if w is None:
                continue
            num += float(v) * float(w)
            den += float(w)
        if den == 0:
            continue  # no data to aggregate; not a Phase 5 finding
        avg = num / den
        if not (lo <= avg <= hi):
            findings.append(
                _finding(
                    spec["severity"], column, "<aggregate>", avg, (lo, hi), spec,
                    kind="aggregate",
                )
            )
    return findings


if __name__ == "__main__":
    # Self-test: demonstrate the helper on a dummy DISPLAY_RANGES + fake rows.
    DISPLAY_RANGES = {
        "wal_years": {
            "bounds": (0.5, 10.0),
            "severity": "HALT",
            "provenance": "Physical: auto-ABS amortize over <=10y.",
            "rationale": "WAL outside these bounds implies parser bug.",
            "agg_bounds": (1.8, 2.5),
        },
        "cum_net_loss_pct": {
            "bounds": (0.0, 30.0),
            "severity": "HALT",
            "provenance": "Domain: auto-ABS pools historically cap around 15-20%.",
            "rationale": "CNL > 30% indicates parser error.",
        },
        "excess_spread_yr": {
            "bounds": (-2.0, 15.0),
            "severity": "WARN",
            "provenance": "Historical: most deals run 4-8%.",
            "rationale": "Outside band possible but warrants inspection.",
        },
    }

    fake_rows = [
        {"deal": "CARMX 2024-1", "wal_years": 2.1, "cum_net_loss_pct": 4.5, "excess_spread_yr": 6.2},
        {"deal": "CARMX 2024-2", "wal_years": 0.1, "cum_net_loss_pct": 3.2, "excess_spread_yr": 5.9},   # HALT wal
        {"deal": "CARMX 2024-3", "wal_years": 2.3, "cum_net_loss_pct": 47.0, "excess_spread_yr": 7.1},  # HALT cnl
        {"deal": "CARMX 2024-4", "wal_years": 2.0, "cum_net_loss_pct": 3.9, "excess_spread_yr": -3.5},  # WARN excess
        {"deal": "CARMX 2024-5", "wal_years": None, "cum_net_loss_pct": 4.1, "excess_spread_yr": 6.8}, # None skipped
    ]

    cell_findings = audit_rendered_data(fake_rows, DISPLAY_RANGES, row_key_field="deal")
    agg_findings = audit_aggregates(fake_rows, DISPLAY_RANGES)
    all_findings = cell_findings + agg_findings

    print(f"Self-test: {len(fake_rows)} rows, {len(DISPLAY_RANGES)} ranges")
    print(f"  per-cell findings: {len(cell_findings)}")
    print(f"  aggregate findings: {len(agg_findings)}")
    for f in all_findings:
        print(
            f"  [{f['severity']:4s}] {f['kind']:9s} {f['column']:20s} "
            f"row={f['row_key']:15s} value={f['value']!r} bounds={f['bounds']}"
        )

    halt = [f for f in all_findings if f["severity"] == "HALT"]
    warn = [f for f in all_findings if f["severity"] == "WARN"]
    print(f"\nSummary: {len(halt)} HALT, {len(warn)} WARN")
    if halt:
        try:
            raise DisplayAuditHalt(halt)
        except DisplayAuditHalt as e:
            print(f"DisplayAuditHalt raised as expected: {e}")
