#!/usr/bin/env python3
"""Merge all per-filing raw extracts into combined.json.

- Sorts by (ticker, period_end) ascending.
- Computes derived fields (QoQ / YoY deltas) from the prior record for the
  same ticker.
- Optionally mirrors combined.json to the nginx-served dashboard dir.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402
from pipeline import db as pdb  # noqa: E402

log = logging.getLogger("merge")


def _load_records() -> list[dict]:
    """Pull every filing from SQLite. Legacy data/raw/*.json is ignored."""
    try:
        return pdb.export_combined(settings.SQLITE_DB_PATH)
    except Exception as e:
        log.error("failed to export from %s: %s", settings.SQLITE_DB_PATH, e)
        return []


def _as_date_key(rec: dict) -> str:
    return rec.get("period_end") or ""


def _derive(records: list[dict]) -> list[dict]:
    """Compute QoQ / YoY deltas per ticker. Mutates and returns records."""
    by_ticker: dict[str, list[dict]] = {}
    for r in records:
        by_ticker.setdefault(r.get("ticker", ""), []).append(r)

    for ticker, seq in by_ticker.items():
        seq.sort(key=_as_date_key)
        for i, r in enumerate(seq):
            prev_q = seq[i - 1] if i >= 1 else None
            prev_y = seq[i - 4] if i >= 4 else None

            r["allowance_coverage_pct_qoq_delta"] = _delta(
                r.get("allowance_coverage_pct"),
                prev_q.get("allowance_coverage_pct") if prev_q else None,
            )
            r["new_securitization_advance_rate_qoq"] = _delta(
                r.get("new_securitization_advance_rate_pct"),
                prev_q.get("new_securitization_advance_rate_pct") if prev_q else None,
            )
            r["originations_mm_yoy_change_pct"] = _pct_change(
                r.get("originations_mm"),
                prev_y.get("originations_mm") if prev_y else None,
            )
            r["provision_yoy_change_pct"] = _pct_change(
                r.get("provision_for_loan_losses_mm"),
                prev_y.get("provision_for_loan_losses_mm") if prev_y else None,
            )
    return records


def _delta(cur, prev):
    if cur is None or prev is None:
        return None
    try:
        return round(float(cur) - float(prev), 6)
    except (TypeError, ValueError):
        return None


def _pct_change(cur, prev):
    if cur is None or prev is None:
        return None
    try:
        prev_f = float(prev)
        cur_f = float(cur)
    except (TypeError, ValueError):
        return None
    if prev_f == 0:
        return None
    return round((cur_f - prev_f) / abs(prev_f), 6)


def _write_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def build_combined() -> list[dict]:
    records = _load_records()
    records = _derive(records)
    # Stable sort: ticker asc, period_end asc
    records.sort(key=lambda r: (r.get("ticker", ""), _as_date_key(r)))
    _write_atomic(settings.COMBINED_JSON, records)
    log.info("wrote %s (%d records)", settings.COMBINED_JSON, len(records))

    serve_dir = os.environ.get("DASHBOARD_SERVE_DIR") or settings.NGINX_SERVE_DIR
    if serve_dir:
        target = Path(serve_dir) / "data" / "combined.json"
        try:
            _write_atomic(target, records)
            log.info("mirrored combined.json -> %s", target)
        except OSError as e:
            log.warning("could not mirror to dashboard dir %s: %s", target, e)
    return records


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_combined()
    return 0


if __name__ == "__main__":
    sys.exit(main())
