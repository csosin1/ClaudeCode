"""Test Overpass API from droplet — tries multiple mirrors and query strategies."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import httpx

result_file = os.path.join(os.path.dirname(__file__), "test_results.json")
WEB_COPY = "/var/www/landing/gym-test.json"

results = {"status": "starting", "attempts": [], "gyms": []}

def save():
    with open(result_file, "w") as f:
        json.dump(results, f, indent=2)
    try:
        import shutil
        shutil.copy(result_file, WEB_COPY)
    except Exception:
        pass

# Multiple Overpass API mirrors
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Very small test query: just fitness centres in Luxembourg City area
TINY_QUERY = '[out:json][timeout:25];node["leisure"="fitness_centre"](49.55,6.08,49.65,6.18);out body;'

# Slightly bigger: all of Luxembourg fitness centres (nodes only)
SMALL_QUERY = '[out:json][timeout:25];node["leisure"="fitness_centre"](49.45,5.73,50.18,6.53);out body;'

def try_query(mirror, query, label, timeout=30):
    attempt = {"mirror": mirror, "label": label, "status": "trying"}
    results["attempts"].append(attempt)
    save()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(mirror, data={"data": query})
            attempt["http_status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                els = data.get("elements", [])
                attempt["status"] = "success"
                attempt["elements"] = len(els)
                save()
                return els
            elif resp.status_code == 429:
                attempt["status"] = "rate_limited"
                save()
                return None
            else:
                attempt["status"] = f"http_{resp.status_code}"
                attempt["body_preview"] = resp.text[:200]
                save()
                return None
    except Exception as e:
        attempt["status"] = f"error"
        attempt["error"] = str(e)
        save()
        return None

# Strategy 1: Try tiny query on each mirror
print("=== Strategy 1: Tiny query (Luxembourg City only) ===")
for mirror in MIRRORS:
    print(f"Trying {mirror}...")
    els = try_query(mirror, TINY_QUERY, "tiny_lux_city")
    if els is not None:
        print(f"  SUCCESS: {len(els)} elements")
        if els:
            # Got data! Now try the slightly bigger query on same mirror
            print(f"  Trying full Luxembourg on same mirror...")
            time.sleep(2)
            full_els = try_query(mirror, SMALL_QUERY, "full_lux_nodes")
            if full_els:
                els = full_els
                print(f"  Full Luxembourg: {len(els)} elements")

        # Extract gym data
        seen = set()
        for el in els:
            eid = el.get("id")
            if eid in seen:
                continue
            seen.add(eid)
            tags = el.get("tags", {})
            results["gyms"].append({
                "name": tags.get("name", "unnamed"),
                "brand": tags.get("brand", ""),
                "lat": el.get("lat"),
                "lon": el.get("lon"),
                "city": tags.get("addr:city", ""),
            })

        results["status"] = "success"
        results["working_mirror"] = mirror
        results["unique_gyms"] = len(results["gyms"])
        save()

        # Now run the actual collection pipeline if we found a working mirror
        if results["gyms"]:
            print(f"\n=== Mirror works! Running full collection pipeline... ===")
            # Update the OVERPASS_URL in collect.py's module
            try:
                import collect
                collect.OVERPASS_URL = mirror
                print("Starting full 6-country collection...")

                def progress(msg):
                    print(msg)
                    results["pipeline_log"] = results.get("pipeline_log", [])
                    results["pipeline_log"].append(msg)
                    save()

                collect.run_collection(progress_cb=progress)
                results["pipeline_status"] = "complete"

                # Count what we got
                from db import get_connection
                conn = get_connection()
                loc_count = conn.execute("SELECT COUNT(*) as c FROM locations WHERE active=1").fetchone()["c"]
                chain_count = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count>0").fetchone()["c"]
                conn.close()
                results["total_locations"] = loc_count
                results["total_chains"] = chain_count
                print(f"\nPipeline complete: {loc_count} locations, {chain_count} chains")
            except Exception as e:
                import traceback
                results["pipeline_status"] = f"failed: {e}"
                results["pipeline_traceback"] = traceback.format_exc()
                print(f"Pipeline failed: {e}")
            save()
        break

    print(f"  Failed, trying next mirror...")
    time.sleep(3)

if results["status"] != "success":
    # Strategy 2: Try GET instead of POST
    print("\n=== Strategy 2: GET request ===")
    import urllib.parse
    encoded = urllib.parse.quote(TINY_QUERY)
    for mirror in MIRRORS[:3]:
        url = f"{mirror}?data={encoded}"
        attempt = {"mirror": mirror, "label": "GET_tiny", "status": "trying"}
        results["attempts"].append(attempt)
        save()
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(url)
                attempt["http_status"] = resp.status_code
                if resp.status_code == 200:
                    data = resp.json()
                    els = data.get("elements", [])
                    attempt["status"] = "success"
                    attempt["elements"] = len(els)
                    results["status"] = "success_via_get"
                    results["working_mirror"] = mirror
                    for el in els:
                        tags = el.get("tags", {})
                        results["gyms"].append({
                            "name": tags.get("name", "unnamed"),
                            "brand": tags.get("brand", ""),
                            "lat": el.get("lat"),
                            "lon": el.get("lon"),
                        })
                    save()
                    print(f"  GET worked: {len(els)} elements")
                    break
                else:
                    attempt["status"] = f"http_{resp.status_code}"
        except Exception as e:
            attempt["status"] = f"error: {e}"
        save()
        time.sleep(3)

save()
print(f"\nFinal status: {results['status']}")
print(f"Total gyms found: {len(results['gyms'])}")
