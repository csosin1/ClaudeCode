"""Unit coverage for pipeline/sec_cache.py."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from config import settings
from pipeline import sec_cache


class _FakeResp:
    def __init__(self, text: str = "", status: int = 200, body: dict | None = None):
        self.text = text
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class _FakeClient:
    """Minimal stand-in for pipeline.fetch_and_parse._EdgarClient.

    Tracks how many times .get() was called, so cache-hit tests can prove
    no network was issued.
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected extra call: {url}")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SEC_CACHE_DIR", tmp_path / "sec_cache")
    yield tmp_path


def test_filing_html_miss_then_hit(tmp_path):
    client = _FakeClient([_FakeResp(text="<html>body</html>")])
    out1 = sec_cache.get_filing_html(client, "HGV", "acc-1", "https://sec.gov/doc.html")
    assert out1 == "<html>body</html>"
    assert len(client.calls) == 1

    # Second call must not hit network at all.
    client2 = _FakeClient([])
    out2 = sec_cache.get_filing_html(client2, "HGV", "acc-1", "https://sec.gov/doc.html")
    assert out2 == "<html>body</html>"
    assert len(client2.calls) == 0

    # File is at the expected path (new writes are gzip-compressed).
    expected = Path(settings.SEC_CACHE_DIR) / "filings" / "HGV" / "acc-1.html.gz"
    assert expected.exists()


def test_filing_html_atomic_write_no_stale_tmp(tmp_path):
    import gzip
    client = _FakeClient([_FakeResp(text="hello")])
    sec_cache.get_filing_html(client, "HGV", "acc-atomic", "https://x/x.html")
    path = Path(settings.SEC_CACHE_DIR) / "filings" / "HGV" / "acc-atomic.html.gz"
    assert path.exists()
    with gzip.open(path, "rb") as f:
        assert f.read().decode("utf-8") == "hello"
    # No .tmp sibling left behind.
    assert list(path.parent.glob("*.tmp")) == []


def test_filing_html_refuses_non_2xx(tmp_path):
    client = _FakeClient([_FakeResp(text="nope", status=500)])
    with pytest.raises(RuntimeError):
        sec_cache.get_filing_html(client, "HGV", "acc-err", "https://x/y.html")
    # Nothing written (neither gzipped nor legacy).
    base = Path(settings.SEC_CACHE_DIR) / "filings" / "HGV"
    assert not (base / "acc-err.html.gz").exists()
    assert not (base / "acc-err.html").exists()


def test_filing_html_reads_legacy_uncompressed(tmp_path):
    """Backwards-compat: caches written before gzip landed still work."""
    base = Path(settings.SEC_CACHE_DIR) / "filings" / "HGV"
    base.mkdir(parents=True, exist_ok=True)
    legacy = base / "acc-legacy.html"
    legacy.write_text("<html>legacy body</html>", encoding="utf-8")
    # No .gz sibling — reader must fall back to the raw file.
    client = _FakeClient([])  # network should not be called
    out = sec_cache.get_filing_html(client, "HGV", "acc-legacy", "https://x.html")
    assert out == "<html>legacy body</html>"
    assert len(client.calls) == 0


def test_xbrl_ttl_hit_within_window(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(cik):
        calls["n"] += 1
        return {"cik": cik, "facts": {}}

    monkeypatch.setattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 168)
    a = sec_cache.get_xbrl_facts(client=None, cik="1674168", fetcher=fake_fetch)
    assert calls["n"] == 1
    b = sec_cache.get_xbrl_facts(client=None, cik="1674168", fetcher=fake_fetch)
    assert calls["n"] == 1  # cached, no new fetch
    assert a == b


def test_xbrl_ttl_expiry_refetches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(cik):
        calls["n"] += 1
        return {"cik": cik, "n": calls["n"]}

    # TTL of zero -> always stale.
    monkeypatch.setattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 0)
    sec_cache.get_xbrl_facts(client=None, cik="1674168", fetcher=fake_fetch)
    sec_cache.get_xbrl_facts(client=None, cik="1674168", fetcher=fake_fetch)
    assert calls["n"] == 2


def test_xbrl_serves_stale_on_network_failure(tmp_path, monkeypatch):
    # Seed the cache with fresh data.
    def ok(cik):
        return {"cik": cik, "ok": True}

    monkeypatch.setattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 0)
    first = sec_cache.get_xbrl_facts(client=None, cik="123", fetcher=ok)
    assert first["ok"] is True

    # Now simulate a network failure and confirm we still get the stale copy.
    def boom(cik):
        raise RuntimeError("network down")

    second = sec_cache.get_xbrl_facts(client=None, cik="123", fetcher=boom)
    assert second == first


def test_submissions_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 168)
    client = _FakeClient([_FakeResp(body={"cik": "123", "filings": {}})])
    sec_cache.get_submissions(client, "123")
    assert len(client.calls) == 1

    client2 = _FakeClient([])
    data = sec_cache.get_submissions(client2, "123")
    assert data["cik"] == "123"
    assert len(client2.calls) == 0
