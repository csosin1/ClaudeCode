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


def build_overpass_query(country_code: str) -> str:
    """Build Overpass QL query for gym locations in a country."""
    bbox = COUNTRY_BBOXES[country_code]
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    return f"""
[out:json][timeout:300];
(
  node["leisure"="fitness_centre"]({bbox_str});
  way["leisure"="fitness_centre"]({bbox_str});
  node["leisure"="sports_centre"]["name"]({bbox_str});
  way["leisure"="sports_centre"]["name"]({bbox_str});
  node["amenity"="gym"]({bbox_str});
  way["amenity"="gym"]({bbox_str});
);
out center body;
"""


def query_overpass(query: str, max_retries: int = 5) -> dict:
    """Query Overpass API with retry and exponential backoff."""
    for attempt in range(max_retries):
        try:
            logger.info("Overpass query attempt %d/%d", attempt + 1, max_retries)
            with httpx.Client(timeout=360) as client:
                resp = client.post(OVERPASS_URL, data={"data": query})
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
            wait = 2 ** (attempt + 1)
            logger.warning("Overpass attempt %d failed: %s. Retrying in %ds", attempt + 1, e, wait)
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


def collect_country(country_code: str) -> list[dict]:
    """Collect all gym locations for a country."""
    logger.info("Collecting gyms for %s", country_code)
    query = build_overpass_query(country_code)
    data = query_overpass(query)
    elements = data.get("elements", [])
    logger.info("Got %d raw elements for %s", len(elements), country_code)

    locations = []
    for el in elements:
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


def run_collection():
    """Run the full data collection pipeline."""
    init_db()
    today = date.today().isoformat()
    all_seen = set()

    with get_db() as conn:
        for country_code in COUNTRY_BBOXES:
            try:
                locations = collect_country(country_code)
                seen = upsert_locations(conn, locations, today)
                all_seen.update(seen)
                logger.info("Upserted %d locations for %s", len(locations), country_code)

                # Pause between countries to be kind to Overpass
                time.sleep(10)
            except Exception as e:
                logger.error("Failed to collect %s: %s", country_code, e)

        # Mark locations not seen in this pull as inactive
        if all_seen:
            placeholders = ",".join(["?"] * len(all_seen))
            conn.execute(
                f"UPDATE locations SET active = 0 WHERE osm_id NOT IN ({placeholders}) AND active = 1",
                list(all_seen),
            )

        # Assign chains and update counts
        assign_chains(conn)
        update_chain_location_counts(conn)
        write_snapshots(conn, today)

    logger.info("Collection complete")


if __name__ == "__main__":
    run_collection()
