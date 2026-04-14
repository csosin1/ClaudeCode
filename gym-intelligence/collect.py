"""Data collection from OpenStreetMap Overpass API for gym locations."""

import json
import re
import time
from datetime import date

import httpx
from thefuzz import fuzz, process

from db import (
    COUNTRY_BBOXES,
    COUNTRY_NAMES,
    get_db,
    get_or_create_chain,
    init_db,
    setup_logging,
    update_chain_location_counts,
)

logger = setup_logging("collect")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass attic-query mirrors. Primary Overpass supports attic/[date:] queries
# reliably; some mirrors do not. query_overpass skips mirrors that return a
# 400 mentioning "date"/"attic" (see historical_backfill use).
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

# Attic queries only accept dates as YYYY-MM-DD.
ATTIC_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Known chain name normalization mappings
KNOWN_CHAINS = {
    "basic-fit": "Basic-Fit",
    "basic fit": "Basic-Fit",
    "basicfit": "Basic-Fit",
    "anytime fitness": "Anytime Fitness",
    "fit for free": "Fit For Free",
    "fitforfree": "Fit For Free",
    "pure gym": "PureGym",
    "puregym": "PureGym",
    "fitness park": "Fitness Park",
    "fitnesspark": "Fitness Park",
    "mcfit": "McFit",
    "mc fit": "McFit",
    "john reed": "John Reed",
    "clever fit": "clever fit",
    "cleverfit": "clever fit",
    "fitness world": "Fitness World",
    "snap fitness": "Snap Fitness",
    "orangetheory": "Orangetheory Fitness",
    "orange theory": "Orangetheory Fitness",
    "crossfit": "CrossFit",
    "the gym group": "The Gym Group",
    "gymgroup": "The Gym Group",
    "sportcity": "SportCity",
    "sport city": "SportCity",
    "trainmore": "TrainMore",
    "david lloyd": "David Lloyd",
    "virgin active": "Virgin Active",
    "keep cool": "Keep Cool",
    "neoness": "Neoness",
    "movida": "Movida",
    "l'appart fitness": "L'Appart Fitness",
    "l'orange bleue": "L'Orange Bleue",
    "orange bleue": "L'Orange Bleue",
    "viva fitness": "Viva Fitness",
    "altafit": "Altafit",
    "go fit": "GO fit",
    "gofit": "GO fit",
    "dir": "DIR",
    "holiday gym": "Holiday Gym",
    "fit7": "Fit7",
    "fico fitness": "Fico Fitness",
}


def build_overpass_queries(
    country_code: str,
    as_of: str | None = None,
) -> list[tuple[str, str]]:
    """Build separate Overpass queries per tag type to avoid 504 timeouts.

    If `as_of` is a YYYY-MM-DD string, each query is turned into an attic query
    by prepending `[date:"{as_of}T00:00:00Z"]` to the settings header, giving
    OSM state as of midnight UTC on that date. `as_of=None` yields present-day
    queries (original behaviour).
    """
    bbox = COUNTRY_BBOXES[country_code]
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

    if as_of is not None and not ATTIC_DATE_RE.match(as_of):
        raise ValueError(f"as_of must match YYYY-MM-DD, got {as_of!r}")

    date_prefix = f'[date:"{as_of}T00:00:00Z"]' if as_of else ""
    # Settings header order: [out:json][timeout:N][date:"..."]; . All three are
    # valid Overpass QL settings and must precede the query body.
    header = f"[out:json][timeout:90]{date_prefix};"

    return [
        ("fitness_centre", f'{header}(node["leisure"="fitness_centre"]({bbox_str});way["leisure"="fitness_centre"]({bbox_str}););out center body;'),
        ("sports_centre", f'{header}(node["leisure"="sports_centre"]["name"]({bbox_str});way["leisure"="sports_centre"]["name"]({bbox_str}););out center body;'),
        ("amenity=gym", f'{header}(node["amenity"="gym"]({bbox_str});way["amenity"="gym"]({bbox_str}););out center body;'),
    ]


def _is_attic_unsupported_error(exc: Exception) -> bool:
    """True when a 400 response indicates the mirror doesn't support attic queries."""
    msg = str(exc).lower()
    if "400" not in msg and "bad request" not in msg:
        return False
    return "date" in msg or "attic" in msg


def query_overpass(
    query: str,
    max_retries: int = 5,
    progress_cb=None,
    mirrors: list[str] | None = None,
) -> dict:
    """Query Overpass API with retry, exponential backoff, and mirror failover.

    `mirrors` is a list of endpoint URLs tried in order. On 504/429/529 the
    next attempt retries the same mirror after a backoff; on 400 responses
    whose message mentions "date" or "attic", the mirror is skipped
    immediately (it doesn't support attic queries — no point retrying).
    Returns the JSON dict of the first mirror that responds successfully.
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    endpoints = mirrors if mirrors else [OVERPASS_URL]
    last_error: Exception | None = None

    for mirror_idx, endpoint in enumerate(endpoints):
        log(f"  Using Overpass mirror {mirror_idx + 1}/{len(endpoints)}: {endpoint}")
        for attempt in range(max_retries):
            try:
                log(f"  Querying Overpass (mirror {mirror_idx + 1}, attempt {attempt + 1}/{max_retries})...")
                with httpx.Client(timeout=120) as client:
                    resp = client.post(endpoint, data={"data": query})
                    # Capture body on HTTP errors so callers can detect attic-
                    # not-supported responses via the exception message.
                    if resp.status_code >= 400:
                        body_snippet = (resp.text or "")[:400]
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code} from {endpoint}: {body_snippet}",
                            request=resp.request,
                            response=resp,
                        )
                    data = resp.json()
                    element_count = len(data.get("elements", []))
                    log(f"  Mirror {mirror_idx + 1} served {element_count} raw elements")
                    return data
            except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
                last_error = e
                # Mirror doesn't support attic queries — skip to next mirror
                # without burning retries.
                if _is_attic_unsupported_error(e):
                    log(f"  Mirror {mirror_idx + 1} rejected attic query ({e}); trying next mirror.")
                    break
                is_rate_limit = "429" in str(e)
                wait = (30 if is_rate_limit else 10) * (attempt + 1)
                log(f"  Attempt {attempt + 1} failed: {'rate limited' if is_rate_limit else e}. Waiting {wait}s...")
                if attempt < max_retries - 1:
                    time.sleep(wait)
        # Exhausted retries on this mirror — fall through to next mirror.
        log(f"  Mirror {mirror_idx + 1} exhausted after {max_retries} attempts; trying next mirror.")

    raise RuntimeError(
        f"Overpass API failed across {len(endpoints)} mirror(s): {last_error}"
    )


def compute_centroid(element: dict) -> tuple[float, float]:
    """Extract lat/lon from an OSM element (node or way with center)."""
    if element["type"] == "node":
        return element["lat"], element["lon"]
    # For ways, Overpass 'out center' gives a center field
    if "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    # Fallback: compute from geometry if available
    if "geometry" in element:
        lats = [p["lat"] for p in element["geometry"]]
        lons = [p["lon"] for p in element["geometry"]]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    return None, None


def extract_location(element: dict, country_code: str) -> dict | None:
    """Extract a location record from an OSM element."""
    tags = element.get("tags", {})
    name = tags.get("name", "").strip()
    brand = tags.get("brand", "").strip()
    operator = tags.get("operator", "").strip()

    # Skip if no identifying name at all
    if not name and not brand and not operator:
        return None

    lat, lon = compute_centroid(element)
    if lat is None:
        return None

    osm_id = f"{element['type']}/{element['id']}"

    addr_street = tags.get("addr:street", "")
    addr_housenumber = tags.get("addr:housenumber", "")
    addr_postcode = tags.get("addr:postcode", "")
    addr_city = tags.get("addr:city", "")
    addr_country = tags.get("addr:country", "")
    website = tags.get("website", tags.get("contact:website", ""))

    parts = [p for p in [addr_street, addr_housenumber, addr_postcode, addr_city] if p]
    address_full = ", ".join(parts) if parts else ""

    return {
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
    }


def normalize_chain_name(name: str, brand: str | None, operator: str | None) -> str:
    """Normalize a gym name/brand/operator to a canonical chain name."""
    # Prefer brand, then name, then operator
    raw = brand or name or operator or "Unknown"
    raw = raw.strip()

    # Check known chains (case-insensitive)
    raw_lower = raw.lower()
    for pattern, canonical in KNOWN_CHAINS.items():
        if pattern in raw_lower:
            return canonical

    # Strip common suffixes: city names, location numbers, franchise IDs
    # e.g., "Basic-Fit Amsterdam" -> "Basic-Fit", "Anytime Fitness #1234" -> "Anytime Fitness"
    cleaned = re.sub(r'\s*[#\-]\s*\d+\s*$', '', raw)
    cleaned = re.sub(r'\s*\(.+?\)\s*$', '', cleaned)

    # Try fuzzy match against known chains
    known_names = list(set(KNOWN_CHAINS.values()))
    match = process.extractOne(cleaned, known_names, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= 80:
        return match[0]

    # Return cleaned name as-is (will become its own chain)
    return cleaned


def collect_country(
    country_code: str,
    progress_cb=None,
    as_of: str | None = None,
    mirrors: list[str] | None = None,
    sleep_between_queries: float = 15.0,
) -> list[dict]:
    """Collect all gym locations for a country using split queries.

    When `as_of` is given, queries are attic-style (state as of that date) and
    `mirrors` (if provided) is used for failover across Overpass endpoints.
    `sleep_between_queries` lets tests drop the inter-query cooldown to 0.
    """
    logger.info("Collecting gyms for %s (as_of=%s)", country_code, as_of)
    queries = build_overpass_queries(country_code, as_of=as_of)
    all_elements = []
    seen_ids = set()

    for tag_label, query in queries:
        try:
            data = query_overpass(query, progress_cb=progress_cb, mirrors=mirrors)
            elements = data.get("elements", [])
            # Deduplicate
            new = 0
            for el in elements:
                eid = el.get("id")
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    all_elements.append(el)
                    new += 1
            if progress_cb:
                progress_cb(f"    {tag_label}: {new} new elements")
            if sleep_between_queries > 0:
                time.sleep(sleep_between_queries)  # Wait between queries to avoid rate limiting
        except Exception as e:
            if progress_cb:
                progress_cb(f"    {tag_label}: FAILED — {e}")
            logger.error("Query %s failed for %s: %s", tag_label, country_code, e)

    logger.info("Got %d total elements for %s", len(all_elements), country_code)

    locations = []
    for el in all_elements:
        loc = extract_location(el, country_code)
        if loc:
            locations.append(loc)

    logger.info("Extracted %d valid locations for %s", len(locations), country_code)
    return locations


def upsert_locations(conn, locations: list[dict], today: str):
    """Upsert locations into the database."""
    seen_osm_ids = set()

    for loc in locations:
        seen_osm_ids.add(loc["osm_id"])

        existing = conn.execute(
            "SELECT id FROM locations WHERE osm_id = ?", (loc["osm_id"],)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE locations SET
                    name = ?, brand = ?, operator = ?, country = ?, city = ?,
                    lat = ?, lon = ?, address_full = ?,
                    addr_street = ?, addr_housenumber = ?, addr_postcode = ?,
                    addr_city = ?, addr_country = ?,
                    website = ?, osm_tags = ?, last_seen_date = ?, active = 1
                WHERE osm_id = ?
            """, (
                loc["name"], loc["brand"], loc["operator"], loc["country"],
                loc["city"], loc["lat"], loc["lon"], loc["address_full"],
                loc["addr_street"], loc["addr_housenumber"], loc["addr_postcode"],
                loc["addr_city"], loc["addr_country"],
                loc["website"], loc["osm_tags"], today, loc["osm_id"],
            ))
        else:
            conn.execute("""
                INSERT INTO locations (
                    osm_id, name, brand, operator, country, city, lat, lon,
                    address_full, addr_street, addr_housenumber, addr_postcode,
                    addr_city, addr_country, website, osm_tags,
                    first_seen_date, last_seen_date, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                loc["osm_id"], loc["name"], loc["brand"], loc["operator"],
                loc["country"], loc["city"], loc["lat"], loc["lon"],
                loc["address_full"], loc["addr_street"], loc["addr_housenumber"],
                loc["addr_postcode"], loc["addr_city"], loc["addr_country"],
                loc["website"], loc["osm_tags"], today, today,
            ))

    return seen_osm_ids


def assign_chains(conn):
    """Assign chain_id to all locations based on normalized names."""
    rows = conn.execute(
        "SELECT id, name, brand, operator FROM locations WHERE active = 1"
    ).fetchall()

    for row in rows:
        canonical = normalize_chain_name(row["name"], row["brand"], row["operator"])
        chain_id = get_or_create_chain(conn, canonical)
        conn.execute(
            "UPDATE locations SET chain_id = ? WHERE id = ?", (chain_id, row["id"])
        )


def write_snapshots(conn, today: str):
    """Write snapshot rows for today."""
    # Delete any existing snapshots for today to allow re-runs
    conn.execute("DELETE FROM snapshots WHERE snapshot_date = ?", (today,))

    rows = conn.execute("""
        SELECT country, chain_id, COUNT(*) as cnt
        FROM locations
        WHERE active = 1
        GROUP BY country, chain_id
    """).fetchall()

    for row in rows:
        conn.execute(
            "INSERT INTO snapshots (snapshot_date, country, chain_id, location_count) VALUES (?, ?, ?, ?)",
            (today, row["country"], row["chain_id"], row["cnt"]),
        )

    logger.info("Wrote %d snapshot rows for %s", len(rows), today)


def run_collection(progress_cb=None):
    """Run the full data collection pipeline.

    progress_cb: optional callable(msg: str) for live progress updates.
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    init_db()
    today = date.today().isoformat()
    all_seen = set()
    total_locations = 0
    collected_countries = set()

    with get_db() as conn:
        country_names = {
            "NL": "Netherlands", "BE": "Belgium", "FR": "France",
            "ES": "Spain", "LU": "Luxembourg", "DE": "Germany",
        }
        country_list = list(COUNTRY_BBOXES.keys())
        for i, country_code in enumerate(country_list, 1):
            cname = country_names.get(country_code, country_code)
            log(f"Collecting {cname} ({i}/{len(country_list)})...")
            try:
                locations = collect_country(country_code, progress_cb=progress_cb)
                seen = upsert_locations(conn, locations, today)
                all_seen.update(seen)
                total_locations += len(locations)
                log(f"  {cname}: {len(locations)} gyms found ({total_locations} total)")

                # Assign chains after each country so partial runs still work
                assign_chains(conn)
                update_chain_location_counts(conn)
                conn.commit()
                log(f"  Chains linked and committed.")

                collected_countries.add(country_code)

                # Pause between countries to avoid rate limiting
                if i < len(country_list):
                    time.sleep(30)
            except Exception as e:
                log(f"  {cname}: FAILED — {e}")
                logger.error("Failed to collect %s: %s", country_code, e)

        # Only mark inactive for countries we actually collected
        # This prevents wiping data from countries that were rate-limited
        if collected_countries:
            for cc in collected_countries:
                country_osm_ids = [oid for oid in all_seen]
                # Get OSM IDs we saw for this country
                seen_for_country = conn.execute(
                    "SELECT osm_id FROM locations WHERE country = ? AND osm_id IN ({})".format(
                        ",".join(["?"] * len(all_seen))
                    ),
                    [cc] + list(all_seen),
                ).fetchall()
                seen_ids_country = {r["osm_id"] for r in seen_for_country}

                if seen_ids_country:
                    # Mark locations in this country that we didn't see as inactive
                    placeholders = ",".join(["?"] * len(seen_ids_country))
                    conn.execute(
                        f"UPDATE locations SET active = 0 WHERE country = ? AND osm_id NOT IN ({placeholders}) AND active = 1",
                        [cc] + list(seen_ids_country),
                    )
            log(f"Updated active status for {len(collected_countries)} countries")

        # Final chain assignment (catches any stragglers)
        log("Final chain normalization...")
        assign_chains(conn)
        update_chain_location_counts(conn)

        chain_count = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count > 0").fetchone()["c"]
        log(f"Identified {chain_count} distinct chains")

        log("Writing snapshots...")
        write_snapshots(conn, today)

    log(f"Collection complete: {total_locations} gyms across {len(country_list)} countries")


def collect_snapshot(
    as_of: str,
    progress_cb=None,
    mirrors: list[str] | None = None,
    sleep_between_countries: float = 30.0,
    sleep_between_queries: float = 15.0,
) -> dict:
    """Collect a single historical snapshot for `as_of` (YYYY-MM-DD).

    Writes directly into the `snapshots` table keyed on `snapshot_date=as_of`
    WITHOUT touching the `locations` table (which represents the present-day
    canonical set). Chain matching uses the *current-day* `chains` table so
    historical counts roll up into today's canonical chain set.

    Idempotent: re-running for the same `as_of` deletes existing rows for
    that date before inserting. Running for a *different* date leaves prior
    snapshots intact.

    Returns a stats dict:
        {"snapshot_date", "countries", "chains_matched",
         "locations_seen", "locations_skipped_no_chain_match",
         "wall_seconds"}

    Chain matching is LOOKUP-ONLY: an OSM element whose normalized name does
    not exist in the `chains` table is SKIPPED (not inserted, not snapshotted,
    not used to create a new chain). This protects the chain set from
    historical pollution and stops `classify.py --reclassify-unknown` from
    burning $$ on retired/misspelled OSM names.
    """
    if not ATTIC_DATE_RE.match(as_of):
        raise ValueError(f"as_of must match YYYY-MM-DD, got {as_of!r}")

    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    mirror_list = mirrors if mirrors is not None else OVERPASS_MIRRORS
    start = time.monotonic()
    init_db()

    # Aggregate (chain_id, country) -> count across all countries. We match
    # OSM elements to chain_id via the *current-day* chains table so
    # historical trend data is anchored to today's canonical chain set.
    per_country_locations: dict[str, list[dict]] = {}
    countries_collected: list[str] = []
    total_elements_seen = 0

    country_list = list(COUNTRY_BBOXES.keys())
    for i, country_code in enumerate(country_list, 1):
        cname = COUNTRY_NAMES.get(country_code, country_code)
        log(f"[{as_of}] Collecting {cname} ({i}/{len(country_list)})...")
        try:
            locations = collect_country(
                country_code,
                progress_cb=progress_cb,
                as_of=as_of,
                mirrors=mirror_list,
                sleep_between_queries=sleep_between_queries,
            )
            per_country_locations[country_code] = locations
            countries_collected.append(country_code)
            total_elements_seen += len(locations)
            log(f"  [{as_of}] {cname}: {len(locations)} gyms")

            if i < len(country_list) and sleep_between_countries > 0:
                time.sleep(sleep_between_countries)
        except Exception as e:
            log(f"  [{as_of}] {cname}: FAILED — {e}")
            logger.error("Snapshot %s country %s failed: %s", as_of, country_code, e)

    # Resolve each location to a chain_id via LOOKUP-ONLY against the
    # current-day canonical `chains` table. An OSM element whose normalized
    # name isn't already a known chain is SKIPPED — we don't create new
    # chain rows from historical OSM data (spec: no chain-set pollution, no
    # downstream classification cost hazard).
    chain_ids_matched: set[int] = set()
    pending_snapshot_rows: list[tuple[str, int, int]] = []  # (country, chain_id, count)
    locations_skipped = 0

    with get_db() as conn:
        # Cache the canonical->id map once per snapshot run (chains table is
        # small; this avoids an SQL round-trip per OSM element).
        chain_lookup = {
            row["canonical_name"]: row["id"]
            for row in conn.execute(
                "SELECT id, canonical_name FROM chains"
            ).fetchall()
        }

        for country_code, locations in per_country_locations.items():
            counts: dict[int, int] = {}
            for loc in locations:
                canonical = normalize_chain_name(
                    loc.get("name") or "",
                    loc.get("brand"),
                    loc.get("operator"),
                )
                chain_id = chain_lookup.get(canonical)
                if chain_id is None:
                    locations_skipped += 1
                    continue
                counts[chain_id] = counts.get(chain_id, 0) + 1
                chain_ids_matched.add(chain_id)
            for chain_id, cnt in counts.items():
                pending_snapshot_rows.append((country_code, chain_id, cnt))

        # Idempotent overwrite of this snapshot date only.
        conn.execute(
            "DELETE FROM snapshots WHERE snapshot_date = ?", (as_of,)
        )
        conn.executemany(
            "INSERT INTO snapshots (snapshot_date, country, chain_id, location_count)"
            " VALUES (?, ?, ?, ?)",
            [(as_of, c, cid, cnt) for (c, cid, cnt) in pending_snapshot_rows],
        )
        log(
            f"[{as_of}] Wrote {len(pending_snapshot_rows)} snapshot rows "
            f"({len(chain_ids_matched)} chains, {total_elements_seen} locations "
            f"seen, {locations_skipped} skipped — no chain match)"
        )

    wall = time.monotonic() - start
    return {
        "snapshot_date": as_of,
        "countries": countries_collected,
        "chains_matched": len(chain_ids_matched),
        "locations_seen": total_elements_seen,
        "locations_skipped_no_chain_match": locations_skipped,
        "wall_seconds": round(wall, 2),
    }


if __name__ == "__main__":
    run_collection()
