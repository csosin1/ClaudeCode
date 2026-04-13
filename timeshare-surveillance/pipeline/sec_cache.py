"""Disk-backed cache for SEC EDGAR responses.

Rationale: a 25-filing 5-year backfill over three tickers hits EDGAR ~75
times for primary-doc HTML plus 3 companyfacts JSONs plus 3 submissions
indexes. Every re-run without a cache re-downloads and re-tokenizes the
exact same bytes. This module persists the raw responses under
settings.SEC_CACHE_DIR so subsequent re-extractions read from disk.

Layout:
    sec_cache/
      filings/<TICKER>/<accession>.html   primary-doc bytes, immutable
      xbrl/CIK<cik>.json                  companyfacts JSON, TTL-gated
      submissions/CIK<cik>.json           submissions index, TTL-gated

Atomic writes: every file is written to a .tmp sibling and os.replace()d.
Errors never poison the cache — non-2xx responses are not persisted, and
parse failures at the call site never delete the cached bytes.

Stale reads on network failure: xbrl + submissions return the stale cached
copy if the network call fails, logging a warning.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

log = logging.getLogger("sec_cache")


def _cache_root() -> Path:
    root = Path(settings.SEC_CACHE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _filings_dir(ticker: str) -> Path:
    d = _cache_root() / "filings" / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _xbrl_path(cik: str) -> Path:
    d = _cache_root() / "xbrl"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"CIK{_normalise_cik(cik)}.json"


def _submissions_path(cik: str) -> Path:
    d = _cache_root() / "submissions"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"CIK{_normalise_cik(cik)}.json"


def _normalise_cik(cik: str | int) -> str:
    s = str(cik).strip().lstrip("0") or "0"
    return s.zfill(10)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _is_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age_sec = time.time() - path.stat().st_mtime
    return age_sec < (ttl_hours * 3600)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_filing_html(
    client: Any,
    ticker: str,
    accession: str,
    url: str,
    refresh: bool = False,
) -> str:
    """Return the primary-doc HTML decoded as str. Cache-first.

    SEC primary-doc responses for an accession are immutable so we never
    TTL-expire these; the cache is permanent until the file is deleted.
    `refresh=True` forces a re-fetch and overwrites.
    """
    path = _filings_dir(ticker) / f"{accession}.html"
    if path.exists() and not refresh:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.warning("sec_cache: read failed for %s: %s; refetching", path, e)

    resp = client.get(url)
    status = getattr(resp, "status_code", 200)
    if not (200 <= int(status) < 300):
        # Do NOT persist errors. Let caller decide how to surface.
        raise RuntimeError(f"sec_cache: refusing to cache non-2xx {status} for {url}")
    text = resp.text
    try:
        _atomic_write_text(path, text)
    except OSError as e:
        log.warning("sec_cache: write failed for %s: %s", path, e)
    return text


def get_xbrl_facts(
    client: Any,
    cik: str,
    fetcher: Callable[[str], dict] | None = None,
    refresh: bool = False,
) -> dict:
    """Return companyfacts JSON for `cik`. TTL-gated.

    `fetcher` is a callable taking cik -> dict, used to fetch when the cache
    is stale/absent. Default is pipeline.xbrl_fetch._fetch_network (late
    imported to avoid a circular dependency).
    """
    path = _xbrl_path(cik)
    ttl = int(getattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 168))

    if not refresh and _is_fresh(path, ttl):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("sec_cache: bad xbrl cache at %s: %s; refetching", path, e)

    if fetcher is None:
        from pipeline import xbrl_fetch as xf  # noqa: PLC0415

        fetcher = xf._fetch_network

    try:
        data = fetcher(cik)
    except Exception as e:
        # Network failure: serve stale if we have it.
        if path.exists():
            log.warning("sec_cache: xbrl fetch failed (%s); serving stale %s", e, path)
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        raise

    try:
        _atomic_write_text(path, json.dumps(data))
    except OSError as e:
        log.warning("sec_cache: xbrl write failed for %s: %s", path, e)
    return data


def get_submissions(
    client: Any,
    cik: str,
    refresh: bool = False,
) -> dict:
    """Return the submissions-index JSON for `cik`. TTL-gated.

    `client` must expose .get(url) returning an object with .json() and
    .status_code, like pipeline.fetch_and_parse._EdgarClient.
    """
    path = _submissions_path(cik)
    ttl = int(getattr(settings, "SEC_CACHE_XBRL_TTL_HOURS", 168))

    if not refresh and _is_fresh(path, ttl):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("sec_cache: bad submissions cache at %s: %s; refetching", path, e)

    url = f"https://data.sec.gov/submissions/CIK{_normalise_cik(cik)}.json"
    try:
        resp = client.get(url)
        status = getattr(resp, "status_code", 200)
        if not (200 <= int(status) < 300):
            raise RuntimeError(f"non-2xx {status} for {url}")
        data = resp.json()
    except Exception as e:
        if path.exists():
            log.warning("sec_cache: submissions fetch failed (%s); serving stale %s", e, path)
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        raise

    try:
        _atomic_write_text(path, json.dumps(data))
    except OSError as e:
        log.warning("sec_cache: submissions write failed for %s: %s", path, e)
    return data
