"""Data collection from OpenStreetMap Overpass API for gym locations."""

import json
import re
import time
from datetime import date

import httpx
from thefuzz import fuzz, process

from db import (
    COUNTRY_BBOXES,
    get_db,
    get_or_create_chain,
    init_db,
    setup_logging,
    update_chain_location_counts,
)

logger = setup_logging("collect")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

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


def build_overpass_queries(country_code: str) -> list[tuple[str, str]]:
    """Build separate Overpass queries per tag type to avoid 504 timeouts."""
    bbox = COUNTRY_BBOXES[country_code]
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    return [
        ("fitness_centre", f'[out:json][timeout:90];(node["leisure"="fitness_centre"]({bbox_str});way["leisure"="fitness_centre"]({bbox_str}););out center body;'),
        ("sports_centre", f'[out:json][timeout:90];(node["leisure"="sports_centre"]["name"]({bbox_str});way["leisure"="sports_centre"]["name"]({bbox_str}););out center body;'),
        ("amenity=gym", f'[out:json][timeout:90];(node["amenity"="gym"]({bbox_str});way["amenity"="gym"]({bbox_str}););out center body;'),
    ]


def query_overpass(query: str, max_retries: int = 3, progress_cb=None) -> dict:
    """Query Overpass API with retry and exponential backoff."""
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    for attempt in range(max_retries):
        try:
            log(f"  Querying Overpass API (attempt {attempt + 1}/{max_retries})...")
            with httpx.Client(timeout=120) as client:
                resp = client.post(OVERPASS_URL, data={"data": query})
                resp.raise_for_status()
                data = resp.json()
                element_count = len(data.get("elements", []))
                log(f"  Got {element_count} raw elements from Overpass")
                return data
        except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
            wait = 2 ** (attempt + 1)
            log(f"  Overpass attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
    raise RuntimeError(f"Overpass API failed after {max_retries} attempts")


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


def collect_country(country_code: str, progress_cb=None) -> list[dict]:
    """Collect all gym locations for a country using split queries."""
    logger.info("Collecting gyms for %s", country_code)
    queries = build_overpass_queries(country_code)
    all_elements = []
    seen_ids = set()

    for tag_label, query in queries:
        try:
            data = query_overpass(query, progress_cb=progress_cb)
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
            time.sleep(3)  # Be polite between queries
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

                # Pause between countries to be kind to Overpass
                if i < len(country_list):
                    time.sleep(10)
            except Exception as e:
                log(f"  {cname}: FAILED — {e}")
                logger.error("Failed to collect %s: %s", country_code, e)

        # Mark locations not seen in this pull as inactive
        if all_seen:
            placeholders = ",".join(["?"] * len(all_seen))
            conn.execute(
                f"UPDATE locations SET active = 0 WHERE osm_id NOT IN ({placeholders}) AND active = 1",
                list(all_seen),
            )

        # Assign chains and update counts
        log("Normalizing chain names...")
        assign_chains(conn)
        update_chain_location_counts(conn)

        chain_count = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count > 0").fetchone()["c"]
        log(f"Identified {chain_count} distinct chains")

        log("Writing snapshots...")
        write_snapshots(conn, today)

    log(f"Collection complete: {total_locations} gyms across {len(country_list)} countries")


if __name__ == "__main__":
    run_collection()
