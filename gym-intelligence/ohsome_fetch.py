"""OHSOME API fetcher for historical OSM snapshots.

The OHSOME API (https://api.ohsome.org/v1/) is HeiGIT's purpose-built service
for time-travel queries over OSM history. We use it instead of Overpass attic
queries because the public Overpass mirrors silently return 0 elements for
bbox+tag attic queries at any historical date — confirmed broken as of
2026-04, see LESSONS.md. OHSOME's ``/elements/centroid`` endpoint returns
GeoJSON Point features for every matching OSM object as-of a given date,
with full tag dicts we can translate 1:1 into the schema ``collect_country``
already produces.

Key endpoint contract:
  * POST ``{OHSOME_BASE}/elements/centroid``
  * ``bboxes`` — ``lon_min,lat_min,lon_max,lat_max`` (OHSOME's order)
  * ``time`` — ``YYYY-MM-DD``
  * ``filter`` — OHSOME filter DSL; we use one combined expression for all
    three gym-like tags so we need a single request per country instead of
    three (Overpass can't express ``or`` across different tag keys cleanly).
  * ``properties=tags`` — include the full tag dict per feature.

Rate limits:
  * OHSOME asks for <=1 req/s per IP. We sleep 1.2s between country requests.
  * On 5xx / 429 / ReadTimeout we retry with exponential backoff (2s, 4s, 8s).
  * 404 with the "not within timeframe" body means `as_of` is out of range —
    raised as ``ValueError`` so callers can surface it cleanly.
"""

import json
import time

import httpx

from db import COUNTRY_BBOXES, setup_logging

logger = setup_logging("ohsome_fetch")

OHSOME_BASE = "https://api.ohsome.org/v1"

# OHSOME snapshot horizon. The server 404s for `time` values past this date.
# We clamp silently so a caller passing "today" still gets data (the most
# recent OHSOME snapshot) instead of an error.
OHSOME_DATA_CUTOFF = "2026-02-19"

# Single filter covers the three tag types Overpass queries separately.
# OHSOME's filter DSL is richer than Overpass QL; `or` across keys is native.
OHSOME_FILTER = (
    "(leisure=fitness_centre or leisure=sports_centre or amenity=gym) "
    "and (type:node or type:way or type:relation)"
)

# Per-request timeout. France/Spain/Germany bboxes are large and OHSOME's
# centroid endpoint routinely needs 2-4 minutes for those; 120s was too
# tight and timed out every retry. 360s is generous enough that a single
# attempt succeeds for DE (the worst case at ~3 min) even at peak load.
_REQUEST_TIMEOUT_S = 360.0

# Retry schedule (5xx, 429, ReadTimeout). 4 attempts total.
_RETRY_BACKOFFS_S = (2.0, 4.0, 8.0)

# Polite pause between country requests (OHSOME docs: 1 req/s per IP).
_INTER_COUNTRY_SLEEP_S = 1.2


def _clamp_as_of(as_of: str) -> str:
    """Clamp `as_of` to OHSOME's snapshot horizon.

    OHSOME 404s on any date past its data cutoff. For this project we'd rather
    silently return the newest available snapshot than blow up on the user,
    since present-day data is produced by the Overpass path anyway.
    """
    return OHSOME_DATA_CUTOFF if as_of > OHSOME_DATA_CUTOFF else as_of


def _bbox_string(country_code: str) -> str:
    """Format a country bbox for OHSOME (lon_min,lat_min,lon_max,lat_max).

    ``COUNTRY_BBOXES`` stores (south, west, north, east) = (lat_min, lon_min,
    lat_max, lon_max). OHSOME expects (lon_min, lat_min, lon_max, lat_max).
    """
    lat_min, lon_min, lat_max, lon_max = COUNTRY_BBOXES[country_code]
    return f"{lon_min},{lat_min},{lon_max},{lat_max}"


def _is_out_of_range_404(resp: httpx.Response) -> bool:
    body = (resp.text or "").lower()
    return (
        resp.status_code == 404
        and ("not completely within the timeframe" in body
             or "not within the timeframe" in body)
    )


def _features_to_records(
    features: list[dict],
    country_code: str,
) -> list[dict]:
    """Translate OHSOME GeoJSON features into collect_country's output shape."""
    out: list[dict] = []
    seen_osm_ids: set[str] = set()

    for feat in features:
        props = feat.get("properties", {}) or {}
        osm_id = props.get("@osmId")
        if not osm_id:
            continue
        # OHSOME occasionally returns duplicates across geometry types
        # (e.g. a building way and the same way as part of a multipolygon
        # relation). Keep the first occurrence.
        if osm_id in seen_osm_ids:
            continue
        seen_osm_ids.add(osm_id)

        geom = feat.get("geometry", {}) or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]

        # Extract the OSM tag subset. OHSOME-internal keys (prefixed with `@`)
        # are metadata, not tags — strip them before storing.
        tags = {k: v for k, v in props.items() if not k.startswith("@")}

        name = (tags.get("name") or "").strip()
        brand = (tags.get("brand") or "").strip()
        operator = (tags.get("operator") or "").strip()

        # Skip features with no identifying name whatsoever. collect_country
        # does the same check in extract_location — keeps parity.
        if not name and not brand and not operator:
            continue

        addr_street = tags.get("addr:street", "") or ""
        addr_housenumber = tags.get("addr:housenumber", "") or ""
        addr_postcode = tags.get("addr:postcode", "") or ""
        addr_city = tags.get("addr:city", "") or ""
        addr_country = tags.get("addr:country", "") or ""
        website = tags.get("website", tags.get("contact:website", "")) or ""

        parts = [p for p in [addr_street, addr_housenumber, addr_postcode, addr_city] if p]
        address_full = ", ".join(parts) if parts else ""

        out.append({
            "osm_id": osm_id,
            "name": name or None,
            "brand": brand or None,
            "operator": operator or None,
            "country": country_code,
            "city": addr_city or None,
            "lat": lat,
            "lon": lon,
            "address_full": address_full or None,
            "addr_street": addr_street or None,
            "addr_housenumber": addr_housenumber or None,
            "addr_postcode": addr_postcode or None,
            "addr_city": addr_city or None,
            "addr_country": addr_country or None,
            "website": website or None,
            "osm_tags": json.dumps(tags),
        })

    return out


def _post_with_retries(
    url: str,
    payload: dict,
    progress_cb=None,
) -> httpx.Response:
    """POST to OHSOME with 4-try retry on 5xx/429/ReadTimeout.

    Returns the Response. Raises the last exception / HTTPStatusError on
    final failure. 404s pass through immediately (they're semantic, not
    transient) so the caller can distinguish "out of timeframe" from
    real server errors.
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    attempts = len(_RETRY_BACKOFFS_S) + 1
    last_exc: Exception | None = None

    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                resp = client.post(url, data=payload)
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            # 5xx or 429 — retry unless we're on the last attempt.
            log(f"  OHSOME {resp.status_code} on attempt {attempt + 1}/{attempts}")
            last_exc = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            log(f"  OHSOME timeout/transport on attempt {attempt + 1}/{attempts}: {e}")

        if attempt < attempts - 1:
            backoff = _RETRY_BACKOFFS_S[attempt]
            log(f"  Waiting {backoff}s before retry...")
            time.sleep(backoff)

    # All attempts exhausted.
    assert last_exc is not None
    raise last_exc


def ohsome_fetch_country(
    country_code: str,
    as_of: str,
    progress_cb=None,
) -> list[dict]:
    """Fetch all gym-like OSM features in a country's bbox as of `as_of`.

    Returns a list of dicts in the same shape ``collect_country`` produces,
    so ``collect_snapshot`` doesn't need to know which fetcher ran.

    Args:
        country_code: Key into ``COUNTRY_BBOXES`` (e.g. "NL").
        as_of: Historical date as YYYY-MM-DD. Clamped to
            ``OHSOME_DATA_CUTOFF`` if in the future.
        progress_cb: Optional callable(str) for live progress updates.

    Raises:
        ValueError: if OHSOME 404s with a "time out of timeframe" message
            (e.g. `as_of` before 2007-10-08, OSM's earliest snapshot).
        httpx.HTTPError: on non-retryable HTTP failures or retries exhausted.
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    effective_as_of = _clamp_as_of(as_of)
    if effective_as_of != as_of:
        log(f"  OHSOME: clamped as_of {as_of} → {effective_as_of} (past data cutoff)")

    bbox = _bbox_string(country_code)
    url = f"{OHSOME_BASE}/elements/centroid"
    payload = {
        "bboxes": bbox,
        "time": effective_as_of,
        "filter": OHSOME_FILTER,
        "properties": "tags",
    }

    log(f"  OHSOME fetch {country_code} @ {effective_as_of} bbox={bbox}")
    resp = _post_with_retries(url, payload, progress_cb=progress_cb)

    if _is_out_of_range_404(resp):
        raise ValueError(
            f"OHSOME: as_of={as_of!r} is outside the OSM-history timeframe "
            f"({resp.text[:200]})"
        )
    if resp.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"OHSOME HTTP {resp.status_code}: {(resp.text or '')[:300]}",
            request=resp.request,
            response=resp,
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise httpx.HTTPError(f"OHSOME returned non-JSON: {e}") from e

    features = data.get("features", []) or []
    log(f"  OHSOME returned {len(features)} raw features for {country_code}")

    records = _features_to_records(features, country_code)
    log(
        f"  OHSOME {country_code}: {len(records)} usable records "
        f"(after name/dedup filtering)"
    )

    # Rate-limit cooldown so the next country call is polite.
    time.sleep(_INTER_COUNTRY_SLEEP_S)
    return records
