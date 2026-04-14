"""Unit tests for /api/snapshot-dates and /api/chain-history.

Uses a throwaway SQLite file as the DB and monkeypatches db.DB_PATH before
importing app. We avoid in-memory ":memory:" because the app opens its own
connections per request, each of which would get a fresh empty memory DB.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


class HistoryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Redirect the DB to a fresh temp file before importing db/app.
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls._tmpdir.name) / "test.db"

        import db  # noqa: E402
        db.DB_PATH = cls.db_path
        db.init_db(cls.db_path)

        # Seed two chains and multi-date snapshots for 'Basic-Fit' so YoY can
        # be computed. 'SoloChain' gets a single snapshot to exercise the
        # <2-point branch.
        with db.get_db(cls.db_path) as conn:
            conn.execute(
                "INSERT INTO chains (id, canonical_name, competitive_classification) "
                "VALUES (1, 'Basic-Fit', 'direct_competitor')"
            )
            conn.execute(
                "INSERT INTO chains (id, canonical_name, competitive_classification) "
                "VALUES (2, 'SoloChain', 'direct_competitor')"
            )
            # Basic-Fit: NL + BE across two quarterly snapshots roughly a year
            # apart, plus a present-day snapshot.
            rows = [
                ("2025-03-31", "NL", 1, 500),
                ("2025-03-31", "BE", 1, 200),  # total 700
                ("2026-03-31", "NL", 1, 550),
                ("2026-03-31", "BE", 1, 230),  # total 780 — +80 / +11.4%
                ("2026-04-12", "NL", 1, 560),
                ("2026-04-12", "BE", 1, 235),  # total 795 (latest)
                ("2026-04-12", "NL", 2, 10),   # SoloChain: single snapshot
            ]
            conn.executemany(
                "INSERT INTO snapshots (snapshot_date, country, chain_id, location_count) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )

        # Import app after DB_PATH is set so its `from db import ...` picks up
        # the patched module.
        import app  # noqa: E402
        app.app.config["TESTING"] = True
        # URL prefix defaults to /gym-intelligence via the blueprint; ensure
        # the env var matches so request paths below are predictable.
        cls.prefix = os.environ.get("URL_PREFIX", "/gym-intelligence")
        cls.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    # ---- /api/snapshot-dates ----
    def test_snapshot_dates_shape(self):
        r = self.client.get(f"{self.prefix}/api/snapshot-dates")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("dates", body)
        self.assertIn("count", body)
        self.assertEqual(body["count"], 3)
        # Ascending
        self.assertEqual(body["dates"], sorted(body["dates"]))
        self.assertEqual(body["dates"][0], "2025-03-31")
        self.assertEqual(body["dates"][-1], "2026-04-12")

    # ---- /api/chain-history ----
    def test_chain_history_missing_name(self):
        r = self.client.get(f"{self.prefix}/api/chain-history")
        self.assertEqual(r.status_code, 400)

    def test_chain_history_unknown_chain_404(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=Nope")
        self.assertEqual(r.status_code, 404)

    def test_chain_history_all_europe_sums_countries(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=Basic-Fit")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["canonical_name"], "Basic-Fit")
        self.assertEqual(body["country"], "All Europe")
        # Three distinct dates, summed across NL+BE.
        totals = {p["snapshot_date"]: p["location_count"] for p in body["series"]}
        self.assertEqual(totals["2025-03-31"], 700)
        self.assertEqual(totals["2026-03-31"], 780)
        self.assertEqual(totals["2026-04-12"], 795)

    def test_chain_history_yoy_uses_closest_to_365_days(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=Basic-Fit")
        body = r.get_json()
        # Latest 2026-04-12 (795). 2026-03-31 is ~12 days earlier (gap-from-365
        # ~353); 2025-03-31 is ~378 days earlier (gap ~13). So 2025-03-31 wins.
        # delta = 795 - 700 = 95. pct = 95/700 = 13.6%.
        self.assertEqual(body["yoy_delta"], 95)
        self.assertAlmostEqual(body["yoy_pct"], 13.6, places=1)

    def test_chain_history_country_filter(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=Basic-Fit&country=NL")
        body = r.get_json()
        self.assertEqual(body["country"], "NL")
        totals = {p["snapshot_date"]: p["location_count"] for p in body["series"]}
        self.assertEqual(totals["2025-03-31"], 500)
        self.assertEqual(totals["2026-04-12"], 560)
        # YoY: 560 - 500 = 60 (2025-03-31 closest to 365 days before latest).
        self.assertEqual(body["yoy_delta"], 60)

    def test_chain_history_single_point_null_yoy(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=SoloChain")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(len(body["series"]), 1)
        self.assertIsNone(body["yoy_delta"])
        self.assertIsNone(body["yoy_pct"])

    def test_chain_history_blank_country_is_all_europe(self):
        r = self.client.get(f"{self.prefix}/api/chain-history?name=Basic-Fit&country=")
        body = r.get_json()
        self.assertEqual(body["country"], "All Europe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
