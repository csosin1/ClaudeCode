#!/usr/bin/env python3
"""Evaluate CRITICAL / WARNING thresholds against latest metrics per ticker.

Prints a JSON diff summary to stdout.

Exit codes:
    0 — no changes vs. prior flag state.
    1 — changes detected (NEW, ESCALATED, RESOLVED).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

log = logging.getLogger("red_flag_diff")


SEVERITY_RANK = {None: 0, "WARNING": 1, "CRITICAL": 2}


def _cmp(op: str, value, threshold) -> bool:
    if value is None:
        return False
    try:
        if op == "==":
            return value == threshold
        v = float(value)
        t = float(threshold) if not isinstance(threshold, bool) else threshold
    except (TypeError, ValueError):
        return False
    if op == ">":
        return v > t
    if op == ">=":
        return v >= t
    if op == "<":
        return v < t
    if op == "<=":
        return v <= t
    return False


def evaluate(record: dict) -> dict[str, dict]:
    """Return {metric_key: {"severity": "CRITICAL"|"WARNING", "value":..., "threshold":...}}"""
    flags: dict[str, dict] = {}
    # Evaluate CRITICAL first, then fall through to WARNING where CRITICAL not tripped.
    for severity in ("CRITICAL", "WARNING"):
        for metric, (op, threshold) in settings.THRESHOLDS[severity].items():
            if metric in flags:  # already CRITICAL, skip WARNING
                continue
            value = record.get(metric)
            if _cmp(op, value, threshold):
                flags[metric] = {
                    "severity": severity,
                    "value": value,
                    "threshold": threshold,
                    "op": op,
                }
    return flags


def _latest_per_ticker(records: list[dict]) -> dict[str, dict]:
    by_ticker: dict[str, dict] = {}
    for r in records:
        t = r.get("ticker")
        if not t:
            continue
        if t not in by_ticker or (r.get("period_end") or "") > (by_ticker[t].get("period_end") or ""):
            by_ticker[t] = r
    return by_ticker


def _diff(prev_state: dict, new_state: dict) -> dict:
    """Compare {ticker: {metric: flag}} vs prior; return categorized diff."""
    out = {"NEW": [], "ESCALATED": [], "RESOLVED": [], "UNCHANGED": []}
    tickers = set(prev_state) | set(new_state)
    for ticker in sorted(tickers):
        prev_flags = prev_state.get(ticker, {})
        new_flags = new_state.get(ticker, {})
        metrics = set(prev_flags) | set(new_flags)
        for m in sorted(metrics):
            before = prev_flags.get(m)
            after = new_flags.get(m)
            if after and not before:
                out["NEW"].append({"ticker": ticker, "metric": m, **after})
            elif before and not after:
                out["RESOLVED"].append({
                    "ticker": ticker,
                    "metric": m,
                    "previous_severity": before.get("severity"),
                    "previous_value": before.get("value"),
                })
            elif before and after:
                if SEVERITY_RANK[after.get("severity")] > SEVERITY_RANK[before.get("severity")]:
                    out["ESCALATED"].append({
                        "ticker": ticker,
                        "metric": m,
                        "from_severity": before.get("severity"),
                        "to_severity": after.get("severity"),
                        "value": after.get("value"),
                        "threshold": after.get("threshold"),
                    })
                else:
                    out["UNCHANGED"].append({"ticker": ticker, "metric": m, **after})
    return out


def _load_json(path: Path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def run(force_email: bool = False) -> tuple[dict, bool]:
    combined = _load_json(settings.COMBINED_JSON, [])
    latest = _latest_per_ticker(combined)
    new_state = {ticker: evaluate(rec) for ticker, rec in latest.items()}

    prev_state = _load_json(settings.FLAG_STATE_JSON, {})
    diff = _diff(prev_state, new_state)

    has_changes = bool(diff["NEW"] or diff["ESCALATED"] or diff["RESOLVED"])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": sorted(new_state.keys()),
        "new": diff["NEW"],
        "escalated": diff["ESCALATED"],
        "resolved": diff["RESOLVED"],
        "active": [
            {"ticker": t, "metric": m, **f}
            for t, flags in new_state.items()
            for m, f in flags.items()
        ],
        "latest_by_ticker": {
            t: {
                "period_end": r.get("period_end"),
                "filing_type": r.get("filing_type"),
                "accession": r.get("accession"),
            }
            for t, r in latest.items()
        },
        "has_changes": has_changes,
    }

    if force_email:
        summary["weekly"] = True
        summary["forced"] = True

    _write_atomic(settings.FLAG_STATE_JSON, new_state)
    return summary, (has_changes or force_email)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-email", action="store_true",
                    help="Always emit a diff summary with weekly:true; exit 1 so callers alert.")
    args = ap.parse_args()

    summary, changed = run(force_email=args.force_email)
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
