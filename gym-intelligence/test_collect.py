"""Robust Overpass collection: checks server status, waits for available slot, uses proper headers."""
import json
import os
import sys
import time
import re

sys.path.insert(0, os.path.dirname(__file__))
import httpx

result_file = os.path.join(os.path.dirname(__file__), "test_results.json")
WEB_COPY = "/var/www/landing/gym-test.json"

results = {"status": "starting", "steps": [], "gyms": []}

def save():
    with open(result_file, "w") as f:
        json.dump(results, f, indent=2)
    try:
        import shutil
        shutil.copy(result_file, WEB_COPY)
    except Exception:
        pass

def step(msg):
    print(msg)
    results["steps"].append(msg)
    save()

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

HEADERS = {
    "User-Agent": "GymIntelligenceTool/1.0 (competitive-analysis; contact@example.com)",
    "Accept": "application/json",
}

# Step 1: Check Overpass API status
step("Step 1: Checking Overpass API status...")
for mirror in MIRRORS:
    status_url = mirror.replace("/interpreter", "/status")
    try:
        with httpx.Client(timeout=10, headers=HEADERS) as client:
            r = client.get(status_url)
            if r.status_code == 200:
                text = r.text
                step(f"  {mirror}: {r.status_code}")
                # Parse available slots
                slots_match = re.search(r'(\d+) slots available', text)
                rate_match = re.search(r'Rate limit: (\d+)', text)
                if slots_match:
                    slots = int(slots_match.group(1))
                    step(f"    Available slots: {slots}")
                    if slots > 0:
                        results["best_mirror"] = mirror
                        results["available_slots"] = slots
                else:
                    step(f"    Status text: {text[:200]}")
                    # If we can reach it, it might still work
                    if "available" in text.lower() or "Connected" in text:
                        results["best_mirror"] = mirror
            else:
                step(f"  {mirror}: HTTP {r.status_code}")
    except Exception as e:
        step(f"  {mirror}: {str(e)[:80]}")

save()

# Step 2: Try to query with the best mirror (or try all)
step("")
step("Step 2: Attempting data query...")

# Ultra-minimal query: just 3 fitness centres near Luxembourg City center
MICRO_QUERY = '[out:json][timeout:15];node["leisure"="fitness_centre"](49.58,6.10,49.62,6.15);out body;'

working_mirror = None

mirrors_to_try = []
if results.get("best_mirror"):
    mirrors_to_try.append(results["best_mirror"])
mirrors_to_try.extend([m for m in MIRRORS if m not in mirrors_to_try])

for mirror in mirrors_to_try:
    step(f"  Trying {mirror.split('//')[1].split('/')[0]}...")
    try:
        with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            resp = client.post(mirror, data={"data": MICRO_QUERY})
            step(f"    HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                els = data.get("elements", [])
                step(f"    Got {len(els)} elements!")
                if els or resp.status_code == 200:
                    working_mirror = mirror
                    break
            elif resp.status_code == 429:
                step("    Rate limited — waiting 30s...")
                time.sleep(30)
                # Retry once
                resp = client.post(mirror, data={"data": MICRO_QUERY})
                if resp.status_code == 200:
                    data = resp.json()
                    step(f"    Retry got {len(data.get('elements', []))} elements")
                    working_mirror = mirror
                    break
            elif resp.status_code == 504:
                step("    Server overloaded (504) — trying next mirror...")
            else:
                step(f"    Unexpected: {resp.text[:150]}")
    except httpx.TimeoutException:
        step("    Timed out")
    except Exception as e:
        step(f"    Error: {str(e)[:100]}")
    time.sleep(5)

if not working_mirror:
    step("")
    step("All mirrors failed. Trying GET method as fallback...")
    import urllib.parse
    encoded = urllib.parse.quote(MICRO_QUERY)
    for mirror in MIRRORS[:3]:
        url = f"{mirror}?data={encoded}"
        try:
            with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
                resp = client.get(url)
                step(f"  GET {mirror.split('//')[1].split('/')[0]}: HTTP {resp.status_code}")
                if resp.status_code == 200:
                    working_mirror = mirror
                    results["method"] = "GET"
                    break
        except Exception as e:
            step(f"  GET failed: {str(e)[:80]}")
        time.sleep(5)

if not working_mirror:
    results["status"] = "all_mirrors_failed"
    step("")
    step("FAILED: Cannot reach any Overpass API mirror.")
    step("The Overpass API may be globally overloaded.")
    step("Will retry on next deploy (5-minute fallback timer).")
    save()
    sys.exit(0)

# Step 3: We have a working mirror! Run full collection.
step("")
step(f"Step 3: Mirror works! Using {working_mirror}")
step("Running full 6-country collection pipeline...")
step("")

try:
    import collect
    collect.OVERPASS_URL = working_mirror

    def progress(msg):
        step(msg)

    collect.run_collection(progress_cb=progress)
    results["pipeline_status"] = "complete"

    # Count results
    from db import get_connection
    conn = get_connection()
    loc_count = conn.execute("SELECT COUNT(*) as c FROM locations WHERE active=1").fetchone()["c"]
    chain_count = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count>0").fetchone()["c"]
    conn.close()

    results["total_locations"] = loc_count
    results["total_chains"] = chain_count
    results["status"] = "success"
    step("")
    step(f"SUCCESS: {loc_count} locations, {chain_count} chains in database!")

except Exception as e:
    import traceback
    results["pipeline_status"] = f"failed"
    results["error"] = str(e)
    results["traceback"] = traceback.format_exc()
    step(f"Pipeline error: {e}")
    step(traceback.format_exc())

save()
