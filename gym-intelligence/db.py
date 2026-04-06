"""Shared database connection and helper functions for gym-intelligence."""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "gyms.db"

logger = logging.getLogger(__name__)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db(db_path: str | Path | None = None):
    """Context manager for database connections."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None):
    """Create all tables if they don't exist."""
    with get_db(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT UNIQUE NOT NULL,
                competitive_classification TEXT DEFAULT 'unknown'
                    CHECK(competitive_classification IN ('direct_competitor', 'non_competitor', 'unknown')),
                price_tier TEXT DEFAULT 'unknown'
                    CHECK(price_tier IN ('budget', 'mid_market', 'premium', 'unknown')),
                pricing_notes TEXT,
                normalized_18mo_cost REAL,
                membership_model TEXT DEFAULT 'unknown'
                    CHECK(membership_model IN ('commitment', 'flexible', 'mixed', 'unknown')),
                ai_classification_rationale TEXT,
                manually_reviewed INTEGER DEFAULT 0,
                location_count INTEGER DEFAULT 0,
                last_classified_date TEXT
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                osm_id TEXT UNIQUE NOT NULL,
                name TEXT,
                brand TEXT,
                operator TEXT,
                country TEXT,
                city TEXT,
                lat REAL,
                lon REAL,
                address_full TEXT,
                addr_street TEXT,
                addr_housenumber TEXT,
                addr_postcode TEXT,
                addr_city TEXT,
                addr_country TEXT,
                website TEXT,
                osm_tags TEXT,
                chain_id INTEGER REFERENCES chains(id),
                first_seen_date TEXT,
                last_seen_date TEXT,
                active INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_locations_osm_id ON locations(osm_id);
            CREATE INDEX IF NOT EXISTS idx_locations_chain_id ON locations(chain_id);
            CREATE INDEX IF NOT EXISTS idx_locations_country ON locations(country);

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                country TEXT NOT NULL,
                chain_id INTEGER NOT NULL REFERENCES chains(id),
                location_count INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_snapshots_chain ON snapshots(chain_id);

            CREATE TABLE IF NOT EXISTS quarterly_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date TEXT NOT NULL,
                analysis_text TEXT NOT NULL,
                model_used TEXT NOT NULL
            );
        """)
    logger.info("Database initialized at %s", db_path or DB_PATH)


def setup_logging(name: str) -> logging.Logger:
    """Configure logging to both console and date-stamped file."""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{name}_{date.today().isoformat()}.log"

    log = logging.getLogger(name)
    log.setLevel(logging.INFO)

    if not log.handlers:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(ch)

    return log


def get_or_create_chain(conn: sqlite3.Connection, canonical_name: str) -> int:
    """Get chain id by canonical name, creating if needed."""
    row = conn.execute(
        "SELECT id FROM chains WHERE canonical_name = ?", (canonical_name,)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO chains (canonical_name) VALUES (?)", (canonical_name,)
    )
    return cursor.lastrowid


def update_chain_location_counts(conn: sqlite3.Connection):
    """Recompute denormalized location_count for all chains."""
    conn.execute("""
        UPDATE chains SET location_count = (
            SELECT COUNT(*) FROM locations
            WHERE locations.chain_id = chains.id AND locations.active = 1
        )
    """)


# Country bounding boxes [south, west, north, east]
COUNTRY_BBOXES = {
    "NL": (50.75, 3.37, 53.47, 7.21),
    "BE": (49.50, 2.55, 51.50, 6.40),
    "FR": (41.33, -5.14, 51.09, 9.56),
    "ES": (36.00, -9.30, 43.79, 3.33),
    "LU": (49.45, 5.73, 50.18, 6.53),
    "DE": (47.27, 5.87, 55.06, 15.04),
}

COUNTRY_NAMES = {
    "NL": "Netherlands",
    "BE": "Belgium",
    "FR": "France",
    "ES": "Spain",
    "LU": "Luxembourg",
    "DE": "Germany",
}


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
