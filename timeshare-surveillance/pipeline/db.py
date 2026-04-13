"""SQLite persistence for the surveillance pipeline.

Replaces the v1 `data/raw/*.json` blob layout. One row per filing keyed by
(ticker, accession). `export_combined()` reshapes rows into the exact dict
shape the dashboard + merge.py expect — same keys as METRIC_SCHEMA plus the
bookkeeping fields (ticker/filing_type/period_end/accession/filed_date/
source_url/extracted_at).

SQLite is stdlib — no third-party dep.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from pipeline.metric_schema import METRIC_SCHEMA

log = logging.getLogger("db")

_HERE = Path(__file__).resolve().parent
_SCHEMA_SQL = _HERE / "schema.sql"

# Bookkeeping fields written alongside METRIC_SCHEMA on every record.
BOOKKEEPING_FIELDS = (
    "ticker",
    "filing_type",
    "period_end",
    "accession",
    "filed_date",
    "source_url",
    "extracted_at",
    "dry_run",
    "extraction_error",
)

# Columns in filings (metric columns + bookkeeping). Used for UPSERT.
_METRIC_COLS = [k for k in METRIC_SCHEMA.keys() if k != "vintage_pools"]
_ALL_COLS = list(BOOKKEEPING_FIELDS) + _METRIC_COLS + ["vintage_pools"]


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open (or create) a SQLite connection with sensible defaults."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str) -> None:
    """Create the filings table + indexes if they don't exist yet."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ddl = _SCHEMA_SQL.read_text()
    with connect(db_path) as conn:
        conn.executescript(ddl)
        conn.commit()


def _coerce_for_db(key: str, value):
    """Coerce a Python value into something SQLite can persist."""
    if value is None:
        return None
    if key == "vintage_pools":
        # Always store as JSON text; accept list-of-dicts or pre-serialised str.
        if isinstance(value, str):
            return value
        return json.dumps(value, default=str)
    if key == "management_flagged_credit_concerns":
        if isinstance(value, bool):
            return 1 if value else 0
        # tolerate "true"/"false" strings
        if isinstance(value, str):
            if value.lower() == "true":
                return 1
            if value.lower() == "false":
                return 0
        return value
    if key in ("dry_run", "extraction_error"):
        return 1 if value else 0
    return value


def upsert_filing(db_path: Path | str, record: dict) -> None:
    """Insert-or-replace a single filing row.

    `record` must contain at least `ticker` and `accession`. Missing metric
    keys are stored as NULL. Extra keys are ignored (this keeps us forward-
    compatible with derived fields added by merge.py).
    """
    ticker = record.get("ticker")
    accession = record.get("accession")
    if not ticker or not accession:
        raise ValueError("upsert_filing requires non-empty ticker and accession")

    cols = list(_ALL_COLS)
    values = [_coerce_for_db(c, record.get(c)) for c in cols]

    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    sql = (
        f"INSERT INTO filings ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(ticker, accession) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("ticker", "accession"))
    )
    with connect(db_path) as conn:
        conn.execute(sql, values)
        conn.commit()


def _row_to_record(row: sqlite3.Row) -> dict:
    d = dict(row)
    # vintage_pools stored as JSON TEXT — deserialise; default [] when missing.
    vp = d.get("vintage_pools")
    if isinstance(vp, str):
        try:
            d["vintage_pools"] = json.loads(vp)
        except (ValueError, TypeError):
            d["vintage_pools"] = []
    elif vp is None:
        d["vintage_pools"] = []
    # Cast bool-ish integer columns back to Python bool/None.
    for bkey in ("management_flagged_credit_concerns", "dry_run", "extraction_error"):
        if bkey in d and d[bkey] is not None:
            d[bkey] = bool(d[bkey])
    # Drop zero-valued bookkeeping sentinels the dashboard doesn't expect.
    if not d.get("dry_run"):
        d.pop("dry_run", None)
    if not d.get("extraction_error"):
        d.pop("extraction_error", None)
    return d


def export_combined(db_path: Path | str) -> list[dict]:
    """Return every filing as a dict, ordered by (ticker, period_end).

    Output shape matches v1 combined.json so the dashboard keeps working and
    merge._derive() can run unchanged.
    """
    if not Path(db_path).exists():
        return []
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM filings ORDER BY ticker ASC, period_end ASC"
        )
        return [_row_to_record(r) for r in cur.fetchall()]


def upsert_many(db_path: Path | str, records: Iterable[dict]) -> int:
    """Convenience batch wrapper. Returns count of rows written."""
    n = 0
    for rec in records:
        upsert_filing(db_path, rec)
        n += 1
    return n
