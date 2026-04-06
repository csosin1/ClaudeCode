"""Check database state and write to /var/www/landing/gym-db-status.json"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db import get_connection, init_db

init_db()
conn = get_connection()

status = {}
status["total_locations"] = conn.execute("SELECT COUNT(*) as c FROM locations WHERE active=1").fetchone()["c"]
status["total_chains"] = conn.execute("SELECT COUNT(*) as c FROM chains WHERE location_count>0").fetchone()["c"]

# Per-country counts
rows = conn.execute("SELECT country, COUNT(*) as c FROM locations WHERE active=1 GROUP BY country").fetchall()
status["by_country"] = {r["country"]: r["c"] for r in rows}

# Top 10 chains
rows = conn.execute("SELECT canonical_name, location_count FROM chains ORDER BY location_count DESC LIMIT 10").fetchall()
status["top_chains"] = [{"name": r["canonical_name"], "count": r["location_count"]} for r in rows]

# Check test results
test_file = os.path.join(os.path.dirname(__file__), "test_results.json")
if os.path.exists(test_file):
    with open(test_file) as f:
        test = json.load(f)
    status["test_status"] = test.get("status")
    status["test_attempts"] = len(test.get("attempts", []))
    status["test_gyms_found"] = len(test.get("gyms", []))
    status["working_mirror"] = test.get("working_mirror")
    status["pipeline_status"] = test.get("pipeline_status")
    # Include last few pipeline log entries
    plog = test.get("pipeline_log", [])
    status["pipeline_log_tail"] = plog[-10:] if plog else []

conn.close()

out = json.dumps(status, indent=2)
print(out)

with open("/var/www/landing/gym-db-status.json", "w") as f:
    f.write(out)
