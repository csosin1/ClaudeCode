"""Test: collect Luxembourg gyms with simpler queries to avoid Overpass 504s."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
result_file = os.path.join(os.path.dirname(__file__), "test_results.json")
results = {"status": "starting", "errors": [], "gyms": [], "queries_tried": []}

def save():
    with open(result_file, "w") as f:
        json.dump(results, f, indent=2)
    # Also copy to web-accessible location
    try:
        import shutil
        shutil.copy(result_file, "/var/www/landing/gym-test.json")
    except Exception:
        pass

def try_query(label, query, timeout=45):
    """Try a single Overpass query, return elements or None."""
    results["queries_tried"].append({"label": label, "status": "starting"})
    save()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(OVERPASS_URL, data={"data": query})
            entry = results["queries_tried"][-1]
            entry["http_status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                els = data.get("elements", [])
                entry["status"] = "success"
                entry["element_count"] = len(els)
                save()
                return els
            else:
                entry["status"] = f"http_{resp.status_code}"
                save()
                return None
    except Exception as e:
        results["queries_tried"][-1]["status"] = f"error: {e}"
        save()
        return None

# Strategy: query one tag at a time for Luxembourg to avoid overloading
LU_BBOX = "49.45,5.73,50.18,6.53"

queries = [
    ("LU fitness_centre nodes", f'[out:json][timeout:30];node["leisure"="fitness_centre"]({LU_BBOX});out body;'),
    ("LU fitness_centre ways", f'[out:json][timeout:30];way["leisure"="fitness_centre"]({LU_BBOX});out center body;'),
    ("LU amenity=gym nodes", f'[out:json][timeout:30];node["amenity"="gym"]({LU_BBOX});out body;'),
]

all_elements = []
for label, query in queries:
    print(f"Trying: {label}...")
    els = try_query(label, query)
    if els:
        all_elements.extend(els)
        print(f"  Got {len(els)} elements")
    else:
        print(f"  Failed, waiting 5s before retry...")
        time.sleep(5)
        els = try_query(label + " (retry)", query, timeout=60)
        if els:
            all_elements.extend(els)
            print(f"  Retry got {len(els)} elements")
    time.sleep(3)  # Be polite to the API

results["total_elements"] = len(all_elements)
results["status"] = "success" if all_elements else "no_data"

# Deduplicate by id
seen = set()
for el in all_elements:
    eid = el.get("id")
    if eid in seen:
        continue
    seen.add(eid)
    tags = el.get("tags", {})
    lat = el.get("lat") or (el.get("center", {}).get("lat"))
    lon = el.get("lon") or (el.get("center", {}).get("lon"))
    results["gyms"].append({
        "name": tags.get("name", "unnamed"),
        "brand": tags.get("brand", ""),
        "lat": lat,
        "lon": lon,
        "city": tags.get("addr:city", ""),
    })

results["unique_gyms"] = len(results["gyms"])
save()
print(f"\nDone: {len(results['gyms'])} unique gyms found")
print(json.dumps(results, indent=2))
