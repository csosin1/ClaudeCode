"""Collect gym data from Overpass API. Tries multiple mirrors, waits for available slots."""
import json
import os
import sys
import time
import re

sys.path.insert(0, os.path.dirname(__file__))
import httpx

RESULT_FILE = os.path.join(os.path.dirname(__file__), "test_results.json")

results = {"status": "starting", "log": [], "gyms_sample": []}

def save():
    with open(RESULT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    try:
        import shutil
        shutil.copy(RESULT_FILE, "/var/www/landing/gym-test.json")
    except Exception:
        pass

def log(msg):
    print(msg)
    results["log"].append(msg)
    save()

HEADERS = {"User-Agent": "GymIntelligence/1.0 (research tool)"}

MIRRORS = [
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

def check_status(mirror):
    """Check if mirror has available query slots. Returns slots count or -1."""
    url = mirror.replace("/interpreter", "/status")
    try:
        with httpx.Client(timeout=10, headers=HEADERS) as c:
            r = c.get(url)
            if r.status_code == 200:
                m = re.search(r'(\d+) slots? available', r.text)
                return int(m.group(1)) if m else 0
    except Exception:
        pass
    return -1

def query(mirror, overpass_ql, timeout=45):
    """Run a single Overpass query. Returns elements list or None."""
    try:
        with httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True) as c:
            r = c.post(mirror, data={"data": overpass_ql})
            if r.status_code == 200:
                return r.json().get("elements", [])
            log(f"    HTTP {r.status_code}")
            return None
    except httpx.TimeoutException:
        log(f"    Timeout after {timeout}s")
        return None
    except Exception as e:
        log(f"    Error: {e}")
        return None

# Step 1: Find a mirror with available slots
log("=== Finding available Overpass mirror ===")
working_mirror = None

for attempt in range(3):  # Try up to 3 rounds
    if attempt > 0:
        wait = 30 * attempt
        log(f"Waiting {wait}s before retry round {attempt+1}...")
        time.sleep(wait)

    for mirror in MIRRORS:
        short = mirror.split("//")[1].split("/")[0]
        slots = check_status(mirror)
        if slots > 0:
            log(f"  {short}: {slots} slots available — testing...")
            # Try a micro query
            test_q = '[out:json][timeout:10];node["leisure"="fitness_centre"](49.60,6.12,49.62,6.14);out body;'
            els = query(mirror, test_q, timeout=15)
            if els is not None:
                log(f"  SUCCESS: got {len(els)} test elements from {short}")
                working_mirror = mirror
                break
            else:
                log(f"  Query failed despite available slots")
        elif slots == 0:
            log(f"  {short}: 0 slots (busy)")
        else:
            log(f"  {short}: unreachable")

    if working_mirror:
        break

if not working_mirror:
    log("")
    log("No mirror available after all attempts.")
    log("Overpass API may be globally overloaded. Will retry next deploy cycle.")
    results["status"] = "all_mirrors_busy"
    save()
    sys.exit(0)

# Step 2: Collect data country by country using split queries
log("")
log(f"=== Collecting gym data via {working_mirror.split('//')[1].split('/')[0]} ===")

# Import collection module and override its URL
import collect
collect.OVERPASS_URL = working_mirror

def progress(msg):
    log(msg)

try:
    collect.run_collection(progress_cb=progress)

    from db import get_connection
    conn = get_connection()
    loc_count = conn.execute("SELECT COUNT(*) as c FROM locations WHERE active=1").fetchone()["c"]
    chain_count = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count>0").fetchone()["c"]

    # Sample of gyms for proof
    sample = conn.execute("""
        SELECT l.name, l.brand, l.country, l.city, c.canonical_name
        FROM locations l LEFT JOIN chains c ON l.chain_id = c.id
        WHERE l.active=1
        ORDER BY c.location_count DESC
        LIMIT 20
    """).fetchall()
    results["gyms_sample"] = [dict(r) for r in sample]
    conn.close()

    results["total_locations"] = loc_count
    results["total_chains"] = chain_count
    results["status"] = "success"
    log("")
    log(f"SUCCESS: {loc_count} locations, {chain_count} chains")
except Exception as e:
    import traceback
    results["status"] = "pipeline_failed"
    results["error"] = str(e)
    results["traceback"] = traceback.format_exc()
    log(f"FAILED: {e}")
    log(traceback.format_exc())

save()
