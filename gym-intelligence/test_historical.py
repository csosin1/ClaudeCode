"""Unit tests for the historical backfill (collect.py + historical_backfill.py).

All tests run offline — `query_overpass` and `collect_snapshot` are
monkeypatched where relevant. No real HTTP traffic is generated.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# Tests live next to collect.py/db.py/historical_backfill.py. Make sure the
# package dir is importable when unittest is invoked from any cwd.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import collect  # noqa: E402
import db as db_mod  # noqa: E402
import historical_backfill as hb  # noqa: E402


class QuarterEndDatesTest(unittest.TestCase):
    def test_count_endpoints_and_ordering(self):
        # Fix "today" to 2026-04-13 (today in repo) so output is deterministic.
        fixed = datetime(2026, 4, 13)
        dates = hb.quarter_end_dates(years_back=4, today=fixed)
        # years_back=4 → 4*4 = 16 completed quarters (2022-06-30 .. 2026-03-31).
        self.assertEqual(len(dates), 16)
        self.assertEqual(dates[-1], "2026-03-31")
        self.assertEqual(dates[0], "2022-06-30")
        # Oldest first, strictly increasing, no duplicates.
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(set(dates)), len(dates))

    def test_all_dates_are_quarter_ends(self):
        fixed = datetime(2026, 4, 13)
        dates = hb.quarter_end_dates(years_back=4, today=fixed)
        valid_endings = {"-03-31", "-06-30", "-09-30", "-12-31"}
        for d in dates:
            self.assertTrue(
                any(d.endswith(e) for e in valid_endings),
                f"{d} is not a quarter-end",
            )


class AtticDateRegexTest(unittest.TestCase):
    def test_accepts_iso_date(self):
        self.assertIsNotNone(collect.ATTIC_DATE_RE.match("2024-06-30"))

    def test_rejects_variants(self):
        for bad in ("2024-6-30", "24-06-30", "2024-06-30T00:00:00Z", "", "not-a-date"):
            self.assertIsNone(
                collect.ATTIC_DATE_RE.match(bad),
                f"regex should reject {bad!r}",
            )


class BuildOverpassQueriesTest(unittest.TestCase):
    def test_with_as_of_injects_date_header_once(self):
        queries = collect.build_overpass_queries("NL", as_of="2023-03-31")
        self.assertEqual(len(queries), 3)
        for label, q in queries:
            self.assertEqual(q.count('[date:"2023-03-31T00:00:00Z"]'), 1,
                             f"{label}: date header not present exactly once in {q!r}")
            # Header must live in the settings block (before the first `;`),
            # not in the query body.
            settings, _, _body = q.partition(";")
            self.assertIn('[date:"2023-03-31T00:00:00Z"]', settings)

    def test_without_as_of_has_no_date_header(self):
        queries = collect.build_overpass_queries("NL", as_of=None)
        for label, q in queries:
            self.assertNotIn("[date:", q, f"{label}: unexpected date header in {q!r}")

    def test_invalid_as_of_rejected(self):
        with self.assertRaises(ValueError):
            collect.build_overpass_queries("NL", as_of="2024-6-30")


# --- query_overpass mirror failover ------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.request = mock.MagicMock()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise collect.httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self,
            )

    def json(self):
        return self._json


class _FakeClient:
    """Context-manager-compatible fake of httpx.Client for query_overpass."""

    def __init__(self, responses_by_url):
        # responses_by_url: dict[url, list[_FakeResponse]] — popped left-to-right
        self.responses_by_url = {k: list(v) for k, v in responses_by_url.items()}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def post(self, url, data=None):
        self.calls.append(url)
        queue = self.responses_by_url.get(url)
        if not queue:
            raise AssertionError(f"No fake response queued for {url}")
        return queue.pop(0)


class QueryOverpassMirrorsTest(unittest.TestCase):
    def test_falls_over_from_504_to_success(self):
        m1, m2 = "https://mirror1/api", "https://mirror2/api"
        fake = _FakeClient({
            m1: [_FakeResponse(504, text="Gateway Timeout")],
            m2: [_FakeResponse(200, json_data={"elements": [{"id": 1}]})],
        })
        with mock.patch.object(collect.httpx, "Client", return_value=fake):
            # max_retries=1 so mirror1 exhausts immediately and we advance.
            data = collect.query_overpass(
                "dummy", max_retries=1, mirrors=[m1, m2]
            )
        self.assertEqual(data, {"elements": [{"id": 1}]})
        self.assertEqual(fake.calls, [m1, m2])

    def test_attic_unsupported_skips_without_retry(self):
        m1, m2 = "https://mirror1/api", "https://mirror2/api"
        # If the helper retried mirror1, the queue would be empty and the
        # fake would raise — so this single queued response proves no retry.
        fake = _FakeClient({
            m1: [_FakeResponse(
                400,
                text="Bad Request: attic query with [date:...] not supported",
            )],
            m2: [_FakeResponse(200, json_data={"elements": []})],
        })
        with mock.patch.object(collect.httpx, "Client", return_value=fake):
            data = collect.query_overpass(
                "dummy", max_retries=5, mirrors=[m1, m2]
            )
        self.assertEqual(data, {"elements": []})
        # Exactly one call to mirror1 (no retry), one to mirror2.
        self.assertEqual(fake.calls, [m1, m2])


# --- collect_snapshot + DB idempotency ---------------------------------------

class CollectSnapshotTest(unittest.TestCase):
    def setUp(self):
        # Isolate the DB to a tmp file so we don't pollute the real gyms.db.
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        # Monkeypatch the module-level DB_PATH used by get_connection.
        self._orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path

        db_mod.init_db()
        with db_mod.get_db() as conn:
            for name in ("Basic-Fit", "Anytime Fitness", "PureGym"):
                conn.execute(
                    "INSERT INTO chains (canonical_name) VALUES (?)", (name,)
                )

    def tearDown(self):
        db_mod.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def _fake_records(self, country_code: str):
        """Return records in the shape ohsome_fetch_country produces.

        Two records: one Basic-Fit, one Anytime Fitness. Independent of
        country — we return the same pair for every country the snapshot
        collector iterates over.
        """
        return [
            {
                "osm_id": f"node/100-{country_code}",
                "name": "Basic-Fit Amsterdam",
                "brand": "Basic-Fit",
                "operator": None,
                "country": country_code,
                "city": None,
                "lat": 52.0,
                "lon": 4.0,
                "address_full": None,
                "addr_street": None,
                "addr_housenumber": None,
                "addr_postcode": None,
                "addr_city": None,
                "addr_country": None,
                "website": None,
                "osm_tags": json.dumps({"name": "Basic-Fit Amsterdam", "brand": "Basic-Fit"}),
            },
            {
                "osm_id": f"node/101-{country_code}",
                "name": "Anytime Fitness Rotterdam",
                "brand": "Anytime Fitness",
                "operator": None,
                "country": country_code,
                "city": None,
                "lat": 52.1,
                "lon": 4.1,
                "address_full": None,
                "addr_street": None,
                "addr_housenumber": None,
                "addr_postcode": None,
                "addr_city": None,
                "addr_country": None,
                "website": None,
                "osm_tags": json.dumps({"name": "Anytime Fitness Rotterdam", "brand": "Anytime Fitness"}),
            },
        ]

    def test_idempotent_overwrite_and_multi_date(self):
        def fake_ohsome_fetch(country_code, as_of, progress_cb=None):
            return self._fake_records(country_code)

        with mock.patch.object(collect, "ohsome_fetch_country", fake_ohsome_fetch):
            stats1 = collect.collect_snapshot(
                "2023-03-31",
                sleep_between_countries=0.0,
                sleep_between_queries=0.0,
            )
            self.assertEqual(stats1["snapshot_date"], "2023-03-31")
            self.assertGreater(stats1["chains_matched"], 0)

            # Snapshot row count after first run.
            with db_mod.get_db() as conn:
                n1 = conn.execute(
                    "SELECT COUNT(*) AS c FROM snapshots WHERE snapshot_date=?",
                    ("2023-03-31",),
                ).fetchone()["c"]

            # Run again for SAME date → DELETE-then-INSERT keeps row set identical.
            collect.collect_snapshot(
                "2023-03-31",
                sleep_between_countries=0.0,
                sleep_between_queries=0.0,
            )
            with db_mod.get_db() as conn:
                n2 = conn.execute(
                    "SELECT COUNT(*) AS c FROM snapshots WHERE snapshot_date=?",
                    ("2023-03-31",),
                ).fetchone()["c"]
            self.assertEqual(n1, n2, "idempotent re-run should produce same row count")

            # Run for a DIFFERENT date → both dates coexist.
            collect.collect_snapshot(
                "2024-03-31",
                sleep_between_countries=0.0,
                sleep_between_queries=0.0,
            )
            with db_mod.get_db() as conn:
                dates = {
                    r["snapshot_date"]
                    for r in conn.execute(
                        "SELECT DISTINCT snapshot_date FROM snapshots"
                    ).fetchall()
                }
        self.assertEqual(dates, {"2023-03-31", "2024-03-31"})

    def test_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            collect.collect_snapshot("not-a-date")

    def test_lookup_only_skips_unknown_chains_and_doesnt_create_rows(self):
        """An OSM element whose normalized name isn't in `chains` must be
        SKIPPED: no new chain row created, no snapshot row written, skip
        counter incremented. This prevents historical OSM pollution from
        feeding the expensive classify.py --reclassify-unknown path."""
        # Count chains seeded by setUp (Basic-Fit, Anytime Fitness, PureGym).
        with db_mod.get_db() as conn:
            chains_before = conn.execute(
                "SELECT COUNT(*) AS c FROM chains"
            ).fetchone()["c"]

        def _rec(country, osm_id, name, brand=None, lat=52.0, lon=4.0):
            return {
                "osm_id": osm_id,
                "name": name,
                "brand": brand,
                "operator": None,
                "country": country,
                "city": None,
                "lat": lat,
                "lon": lon,
                "address_full": None,
                "addr_street": None,
                "addr_housenumber": None,
                "addr_postcode": None,
                "addr_city": None,
                "addr_country": None,
                "website": None,
                "osm_tags": json.dumps({"name": name, **({"brand": brand} if brand else {})}),
            }

        def fake_ohsome_fetch(country_code, as_of, progress_cb=None):
            return [
                # Known chain — matches "Basic-Fit" in seeded chains table.
                _rec(country_code, f"node/200-{country_code}",
                     "Basic-Fit Utrecht", brand="Basic-Fit"),
                # Unknown one-off gym — must be skipped.
                _rec(country_code, f"node/201-{country_code}",
                     "Gertjan's Garage Gym", lat=52.1, lon=4.1),
                # Another unknown — also skipped.
                _rec(country_code, f"node/202-{country_code}",
                     "Sportschool De Randweg", lat=52.2, lon=4.2),
            ]

        with mock.patch.object(collect, "ohsome_fetch_country", fake_ohsome_fetch):
            stats = collect.collect_snapshot(
                "2024-06-30",
                sleep_between_countries=0.0,
                sleep_between_queries=0.0,
            )

        # Stats include the new skip counter and locations_seen includes both
        # matched and skipped OSM elements.
        self.assertIn("locations_skipped_no_chain_match", stats)
        self.assertGreater(stats["locations_skipped_no_chain_match"], 0)
        # Per-country: 1 matched + 2 skipped = 3 seen per country, times 6
        # countries (all serve the same fake response).
        self.assertEqual(stats["locations_seen"], 3 * 6)
        self.assertEqual(stats["locations_skipped_no_chain_match"], 2 * 6)

        # Crucially: NO new chain rows were created by the snapshot run.
        with db_mod.get_db() as conn:
            chains_after = conn.execute(
                "SELECT COUNT(*) AS c FROM chains"
            ).fetchone()["c"]
            # The unknown canonical names must not have been inserted.
            for bad in ("Gertjan's Garage Gym", "Sportschool De Randweg"):
                row = conn.execute(
                    "SELECT id FROM chains WHERE canonical_name = ?", (bad,)
                ).fetchone()
                self.assertIsNone(row, f"{bad!r} must not be inserted into chains")

            # Snapshot rows reference only the matched chain.
            snap_chains = {
                r["chain_id"] for r in conn.execute(
                    "SELECT DISTINCT chain_id FROM snapshots WHERE snapshot_date = ?",
                    ("2024-06-30",),
                ).fetchall()
            }
            bf_id = conn.execute(
                "SELECT id FROM chains WHERE canonical_name = ?", ("Basic-Fit",)
            ).fetchone()["id"]
            self.assertEqual(snap_chains, {bf_id})

        self.assertEqual(chains_after, chains_before)


# --- snapshot_runs table migration ------------------------------------------

class InitDbSnapshotRunsTest(unittest.TestCase):
    def test_table_created_and_idempotent(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            db_mod.init_db(tmp.name)
            # Re-run init_db — should not error.
            db_mod.init_db(tmp.name)
            conn = sqlite3.connect(tmp.name)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name='snapshot_runs'"
                ).fetchall()
                self.assertEqual(len(rows), 1)
                # Insert a row and confirm the schema matches.
                conn.execute(
                    "INSERT INTO snapshot_runs (snapshot_date, status, error,"
                    " wall_seconds, completed_at) VALUES (?, ?, ?, ?, ?)",
                    ("2024-06-30", "ok", None, 12.5, "2026-04-13T00:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()
        finally:
            os.unlink(tmp.name)


# --- Runner: --skip-existing ------------------------------------------------

class RunnerSkipExistingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self._orig_db_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        # Seed a chain and one snapshot row for 2023-03-31 so the runner
        # will see that date as "already present".
        with db_mod.get_db() as conn:
            cur = conn.execute(
                "INSERT INTO chains (canonical_name) VALUES (?)", ("Basic-Fit",)
            )
            chain_id = cur.lastrowid
            conn.execute(
                "INSERT INTO snapshots (snapshot_date, country, chain_id,"
                " location_count) VALUES (?, ?, ?, ?)",
                ("2023-03-31", "NL", chain_id, 42),
            )

    def tearDown(self):
        db_mod.DB_PATH = self._orig_db_path
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def test_skip_existing_does_not_call_collector(self):
        calls = []

        def fake_collector(d):
            calls.append(d)
            if d == "2023-03-31":
                raise AssertionError(
                    "collector must not be called for already-present date"
                )
            return {
                "snapshot_date": d, "countries": [], "chains_matched": 0,
                "locations_seen": 0, "wall_seconds": 0.1,
            }

        summary = hb.run_backfill(
            single_date=None,
            dry_run=False,
            skip_existing=True,
            collect_fn=fake_collector,
        )

        self.assertIn("2023-03-31", summary["skipped"])
        self.assertNotIn("2023-03-31", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
