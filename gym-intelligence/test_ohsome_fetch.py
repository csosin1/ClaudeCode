"""Unit tests for ohsome_fetch.py.

Tests run offline: httpx.Client is monkeypatched with a fake that returns
pre-baked responses. No real HTTP traffic is generated.

A sample OHSOME response captured from a real NL 2022-04-01 query lives at
fixtures/ohsome_nl_2022-04-01_sample.json. Six features, one of which is an
intentional duplicate (``way/636824780`` twice) so the dedupe test has
something to exercise.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import httpx  # noqa: E402

import ohsome_fetch  # noqa: E402
from db import COUNTRY_BBOXES  # noqa: E402


FIXTURE = _HERE / "fixtures" / "ohsome_nl_2022-04-01_sample.json"


def _load_fixture() -> dict:
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return json.load(f)


class _FakeResponse:
    """Just enough of httpx.Response for ohsome_fetch to consume."""

    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.request = mock.MagicMock()

    def json(self):
        if self._json is None:
            raise json.JSONDecodeError("no body", "", 0)
        return self._json


class _FakeClient:
    """Context-manager-compatible fake of httpx.Client.

    Records every POST so tests can assert the outgoing payload.
    `responses` is popped left-to-right; responses must outnumber the calls
    the test expects.
    """

    def __init__(self, responses: list[_FakeResponse]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def post(self, url, data=None):
        self.calls.append((url, data or {}))
        if not self.responses:
            raise AssertionError(f"Unexpected POST {url} — no fake responses left")
        return self.responses.pop(0)


def _patch_client(fake: _FakeClient):
    """Patch httpx.Client so every instantiation returns the same fake.

    ohsome_fetch creates a fresh ``httpx.Client(timeout=...)`` inside the
    retry loop, so a plain return_value works: each call produces the same
    fake, and the fake queues responses across all calls.
    """
    return mock.patch.object(ohsome_fetch.httpx, "Client", return_value=fake)


class FetchShapeTest(unittest.TestCase):
    def test_fetch_returns_collect_country_shape(self):
        fake = _FakeClient([_FakeResponse(200, json_data=_load_fixture())])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            records = ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        self.assertGreater(len(records), 0)
        required_keys = {
            "osm_id", "name", "brand", "operator", "country",
            "lat", "lon", "osm_tags",
        }
        for r in records:
            self.assertTrue(required_keys.issubset(r.keys()),
                            f"missing keys in record: {r}")
            self.assertIsInstance(r["osm_id"], str)
            self.assertIsInstance(r["country"], str)
            self.assertIsInstance(r["lat"], (int, float))
            self.assertIsInstance(r["lon"], (int, float))
            # osm_tags must be valid JSON.
            tags = json.loads(r["osm_tags"])
            self.assertIsInstance(tags, dict)
            # OHSOME-internal metadata keys must be stripped.
            for k in tags:
                self.assertFalse(k.startswith("@"),
                                 f"ohsome-internal key leaked into osm_tags: {k}")

    def test_country_code_round_trips(self):
        fake = _FakeClient([_FakeResponse(200, json_data=_load_fixture())])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            records = ohsome_fetch.ohsome_fetch_country("BE", "2022-04-01")
        for r in records:
            self.assertEqual(r["country"], "BE")


class ClampFutureAsOfTest(unittest.TestCase):
    def test_clamp_future_as_of(self):
        """`as_of` past the OHSOME cutoff must be silently clamped."""
        fake = _FakeClient([_FakeResponse(200, json_data={"features": []})])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            ohsome_fetch.ohsome_fetch_country("NL", "2026-06-01")

        # Exactly one outgoing request with the clamped time.
        self.assertEqual(len(fake.calls), 1)
        _url, payload = fake.calls[0]
        self.assertEqual(payload["time"], ohsome_fetch.OHSOME_DATA_CUTOFF)

    def test_past_as_of_is_unchanged(self):
        fake = _FakeClient([_FakeResponse(200, json_data={"features": []})])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")
        _url, payload = fake.calls[0]
        self.assertEqual(payload["time"], "2022-04-01")


class TimeOutOfRangeTest(unittest.TestCase):
    def test_404_time_out_of_range_raises_value_error(self):
        body = json.dumps({
            "status": 404,
            "message": (
                "The given time parameter is not completely within the "
                "timeframe (2007-10-08T00:00:00Z to 2026-02-19T12:00Z) "
                "of the underlying osh-data."
            ),
        })
        fake = _FakeClient([_FakeResponse(404, text=body)])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            with self.assertRaises(ValueError) as ctx:
                ohsome_fetch.ohsome_fetch_country("NL", "1999-01-01")
        self.assertIn("timeframe", str(ctx.exception).lower())


class RetryTest(unittest.TestCase):
    def test_retry_on_5xx(self):
        fake = _FakeClient([
            _FakeResponse(500, text="boom"),
            _FakeResponse(500, text="boom"),
            _FakeResponse(200, json_data=_load_fixture()),
        ])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            records = ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        # 3 POSTs total: 2 failures + 1 success.
        self.assertEqual(len(fake.calls), 3)
        self.assertGreater(len(records), 0)

    def test_gives_up_after_four_attempts(self):
        fake = _FakeClient([_FakeResponse(500, text="boom") for _ in range(4)])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            with self.assertRaises(httpx.HTTPError):
                ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")
        self.assertEqual(len(fake.calls), 4)


class DedupeTest(unittest.TestCase):
    def test_dedupe_on_osm_id(self):
        # Fixture has way/636824780 appearing twice. Post-dedupe, one.
        fake = _FakeClient([_FakeResponse(200, json_data=_load_fixture())])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            records = ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        osm_ids = [r["osm_id"] for r in records]
        self.assertEqual(len(osm_ids), len(set(osm_ids)),
                         "duplicate osm_ids leaked into output")
        self.assertIn("way/636824780", osm_ids)
        self.assertEqual(osm_ids.count("way/636824780"), 1)


class BboxFormatTest(unittest.TestCase):
    def test_bbox_format(self):
        """bbox string must be lon_min,lat_min,lon_max,lat_max (OHSOME's order)."""
        fake = _FakeClient([_FakeResponse(200, json_data={"features": []})])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        _url, payload = fake.calls[0]
        nl_bbox = COUNTRY_BBOXES["NL"]  # (south, west, north, east)
        lat_min, lon_min, lat_max, lon_max = nl_bbox
        expected = f"{lon_min},{lat_min},{lon_max},{lat_max}"
        self.assertEqual(payload["bboxes"], expected)


class FilterCoverageTest(unittest.TestCase):
    def test_filter_covers_all_three_tag_types(self):
        fake = _FakeClient([_FakeResponse(200, json_data={"features": []})])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        _url, payload = fake.calls[0]
        f = payload["filter"]
        self.assertIn("leisure=fitness_centre", f)
        self.assertIn("leisure=sports_centre", f)
        self.assertIn("amenity=gym", f)


class PropertiesTagsTest(unittest.TestCase):
    def test_properties_tags_requested(self):
        fake = _FakeClient([_FakeResponse(200, json_data={"features": []})])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")
        _url, payload = fake.calls[0]
        self.assertEqual(payload["properties"], "tags")


class NamelessFeatureTest(unittest.TestCase):
    def test_nameless_feature_is_dropped(self):
        """A feature with no name/brand/operator is not identifiable and must be dropped (mirrors collect_country's extract_location behaviour)."""
        data = {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [4.0, 52.0]},
                    "properties": {
                        "@osmId": "way/1",
                        "leisure": "fitness_centre",
                        # No name, brand, or operator.
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [4.1, 52.1]},
                    "properties": {
                        "@osmId": "way/2",
                        "leisure": "fitness_centre",
                        "name": "Real Gym",
                    },
                },
            ]
        }
        fake = _FakeClient([_FakeResponse(200, json_data=data)])
        with _patch_client(fake), mock.patch.object(ohsome_fetch.time, "sleep"):
            records = ohsome_fetch.ohsome_fetch_country("NL", "2022-04-01")

        osm_ids = [r["osm_id"] for r in records]
        self.assertEqual(osm_ids, ["way/2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
