"""Historical Overpass attic-query backfill runner.

Iterates over quarter-end dates (default: last 4 years) and calls
`collect_snapshot` for each, recording stats to `snapshot_runs` in the DB.

Design notes:
  * Date generation is a pure function (`quarter_end_dates`) so it's trivial
    to unit test without touching the DB or network.
  * Failures on one date are recorded and do NOT abort the runner — the loop
    continues with the next date.
  * SIGTERM/SIGINT is caught: we finish the *current* date, record an
    'aborted' row, and stop. This lets long-running backfills be killed
    cleanly from systemd or the shell.
  * `--skip-existing` queries the `snapshots` table directly; it's the
    default because reruns are expected (network flakiness, rate limits).
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone

from collect import collect_snapshot
from db import get_db, init_db, setup_logging

logger = setup_logging("historical_backfill")

# Overpass attic queries (a single country at current volume) take roughly
# 2–5 minutes wall-clock plus inter-query cooldown. This estimate is used
# only by --dry-run so the operator knows roughly how long the real run takes.
EST_SECONDS_PER_DATE = 8 * 60  # 8 minutes per date is a pessimistic estimate


# --- Date generation ---------------------------------------------------------

# Fixed month-end days per quarter. Using a lookup table instead of
# calendar math keeps the function dead-simple and unambiguously correct.
_QUARTER_ENDS = [
    (3, 31),   # Q1
    (6, 30),   # Q2
    (9, 30),   # Q3
    (12, 31),  # Q4
]


def quarter_end_dates(years_back: int = 4, today: datetime | None = None) -> list[str]:
    """Return quarter-end dates for the last `years_back` years.

    Excludes the current (incomplete) quarter. Oldest date first, no
    duplicates. With today=2026-04-13 and years_back=4 this returns the
    16 dates from 2022-06-30 through 2026-03-31 inclusive (16 completed
    quarters: Q2 2022 through Q1 2026).
    """
    now = today or datetime.now(timezone.utc)
    current_q = (now.month - 1) // 3  # 0..3

    # Build all (year, quarter) pairs ending at the most recently completed
    # quarter, walking backwards `years_back * 4` quarters.
    if current_q == 0:
        # January/February/March: the most recent completed quarter is Q4 of
        # the previous year.
        last_completed_year = now.year - 1
        last_completed_q_idx = 3
    else:
        last_completed_year = now.year
        last_completed_q_idx = current_q - 1

    # Produce `years_back * 4` quarter-ends ending at the most recent
    # completed quarter. For years_back=4 with today in Q2 2026 this gives
    # 16 dates: 2022-06-30 … 2026-03-31 (inclusive on both ends).
    total_quarters = years_back * 4
    pairs: list[tuple[int, int]] = []
    y, q = last_completed_year, last_completed_q_idx
    for _ in range(total_quarters):
        pairs.append((y, q))
        q -= 1
        if q < 0:
            q = 3
            y -= 1

    pairs.reverse()  # oldest first
    result = []
    for (year, q_idx) in pairs:
        month, day = _QUARTER_ENDS[q_idx]
        result.append(f"{year:04d}-{month:02d}-{day:02d}")
    # Dedupe defensively (shouldn't happen, but cheap safety net).
    seen = set()
    deduped = []
    for d in result:
        if d not in seen:
            seen.add(d)
            deduped.append(d)
    return deduped


# --- Runner state + DB helpers -----------------------------------------------

_SHUTDOWN_REQUESTED = False


def _install_signal_handlers():
    """SIGTERM/SIGINT flip a flag checked between dates."""
    def _handler(signum, _frame):
        global _SHUTDOWN_REQUESTED
        _SHUTDOWN_REQUESTED = True
        logger.warning("Signal %s received; will stop after current date.", signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _existing_snapshot_dates() -> set[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT snapshot_date FROM snapshots"
        ).fetchall()
        return {r["snapshot_date"] for r in rows}


def _record_run(
    snapshot_date: str,
    status: str,
    error: str | None,
    wall_seconds: float,
):
    """Insert a row into snapshot_runs (audit log for this runner)."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO snapshot_runs (snapshot_date, status, error,"
            " wall_seconds, completed_at) VALUES (?, ?, ?, ?, ?)",
            (
                snapshot_date,
                status,
                error,
                wall_seconds,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )


# --- Main entrypoint ---------------------------------------------------------

def run_backfill(
    years: int = 4,
    dry_run: bool = False,
    skip_existing: bool = True,
    single_date: str | None = None,
    collect_fn=None,
) -> dict:
    """Execute the backfill. Returns a summary dict.

    `collect_fn` is injectable for testing — defaults to `collect_snapshot`.
    """
    collector = collect_fn or collect_snapshot
    init_db()

    if single_date:
        dates = [single_date]
    else:
        dates = quarter_end_dates(years_back=years)

    if dry_run:
        est = len(dates) * EST_SECONDS_PER_DATE
        summary = {
            "dry_run": True,
            "dates": dates,
            "count": len(dates),
            "estimated_wall_seconds": est,
            "estimated_wall_human": f"~{est // 60} min (~{est // 3600}h)",
        }
        print(json.dumps(summary))
        return summary

    existing = _existing_snapshot_dates() if skip_existing else set()
    skipped: list[str] = []
    completed: list[str] = []
    failed: list[str] = []
    aborted: list[str] = []

    _install_signal_handlers()

    for d in dates:
        if _SHUTDOWN_REQUESTED:
            logger.warning("Shutdown requested before %s; recording abort.", d)
            _record_run(d, "aborted", "shutdown requested", 0.0)
            aborted.append(d)
            continue

        if skip_existing and d in existing:
            logger.info("Skipping %s (already present in snapshots)", d)
            skipped.append(d)
            print(json.dumps({"snapshot_date": d, "status": "skipped"}))
            continue

        t0 = time.monotonic()
        try:
            stats = collector(d)
            wall = time.monotonic() - t0
            _record_run(d, "ok", None, wall)
            completed.append(d)
            line = {"status": "ok", **stats}
            print(json.dumps(line))
        except Exception as e:
            wall = time.monotonic() - t0
            logger.exception("Snapshot %s failed", d)
            _record_run(d, "failed", repr(e), wall)
            failed.append(d)
            print(json.dumps({
                "snapshot_date": d,
                "status": "failed",
                "error": repr(e),
                "wall_seconds": round(wall, 2),
            }))

    summary = {
        "completed": completed,
        "skipped": skipped,
        "failed": failed,
        "aborted": aborted,
        "total_dates": len(dates),
    }
    print(json.dumps({"summary": summary}))
    return summary


def _cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--years", type=int, default=4,
                   help="Years of history (default 4).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the date list and estimated wall-clock; no network.")
    p.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        default=True,
        help="Skip dates already present in snapshots (default).",
    )
    p.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-collect dates even if already present.",
    )
    p.add_argument("--date", type=str, default=None,
                   help="Collect a single YYYY-MM-DD snapshot and exit.")
    args = p.parse_args()

    summary = run_backfill(
        years=args.years,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
        single_date=args.date,
    )
    # Non-zero exit when anything failed so systemd/CI surfaces the problem.
    if summary.get("failed"):
        sys.exit(2)


if __name__ == "__main__":
    _cli()
