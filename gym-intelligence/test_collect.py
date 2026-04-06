"""One-time test: collect Luxembourg gyms and save results to test_results.json.
Run on the droplet via the deploy pipeline to verify Overpass API works.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

results = {"status": "starting", "errors": [], "gyms": []}
result_file = os.path.join(os.path.dirname(__file__), "test_results.json")

try:
    results["status"] = "importing"
    import httpx
    results["httpx"] = "ok"
except ImportError as e:
    results["httpx"] = str(e)
    results["errors"].append(f"httpx import failed: {e}")

try:
    from thefuzz import fuzz
    results["thefuzz"] = "ok"
except ImportError as e:
    results["thefuzz"] = str(e)
    results["errors"].append(f"thefuzz import failed: {e}")

# Try a minimal Overpass query for Luxembourg (smallest country)
try:
    results["status"] = "querying_overpass"
    query = """
[out:json][timeout:60];
(
  node["leisure"="fitness_centre"](49.45,5.73,50.18,6.53);
  way["leisure"="fitness_centre"](49.45,5.73,50.18,6.53);
  node["amenity"="gym"](49.45,5.73,50.18,6.53);
  way["amenity"="gym"](49.45,5.73,50.18,6.53);
);
out center body;
"""
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
        )
        results["overpass_status"] = resp.status_code
        if resp.status_code == 200:
            data = resp.json()
            elements = data.get("elements", [])
            results["element_count"] = len(elements)
            results["status"] = "success"
            # Save first 10 gyms as proof
            for el in elements[:10]:
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
        else:
            results["status"] = "overpass_error"
            results["response_body"] = resp.text[:500]
except Exception as e:
    results["status"] = "failed"
    results["errors"].append(str(e))

with open(result_file, "w") as f:
    json.dump(results, f, indent=2)

print(json.dumps(results, indent=2))
