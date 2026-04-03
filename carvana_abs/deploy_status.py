#!/usr/bin/env python3
"""Write a status.json file with deploy state, validation results, and data stats.
Called by auto_deploy.sh after each deploy. Served at /status/status.json by nginx."""

import json
import os
import sys
import sqlite3
from datetime import datetime

STATUS_DIR = "/opt/abs-dashboard/carvana_abs/static_site/status"
os.makedirs(STATUS_DIR, exist_ok=True)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB

PREVIEW_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site", "preview", "index.html")
LIVE_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site", "live", "index.html")


def get_db_stats():
    if not os.path.exists(DB):
        return {"error": "no database"}
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    stats = {}
    for table in ["filings", "pool_performance", "monthly_summary", "loan_loss_summary", "loans"]:
        try:
            r = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = r[0]
        except:
            stats[table] = "missing"
    # Check waterfall fields
    try:
        r = c.execute("SELECT COUNT(*) FROM pool_performance WHERE residual_cash IS NOT NULL").fetchone()
        stats["pool_with_residual"] = r[0]
    except:
        stats["pool_with_residual"] = "column missing"
    # Check deals with data
    try:
        r = c.execute("SELECT deal, COUNT(*) as n FROM monthly_summary GROUP BY deal ORDER BY deal").fetchall()
        stats["deals"] = {row[0]: row[1] for row in r}
    except:
        stats["deals"] = {}
    conn.close()
    return stats


def get_file_info(path):
    if os.path.exists(path):
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
        # Check for key features
        with open(path) as f:
            html = f.read()
        return {
            "exists": True,
            "size_kb": round(size / 1024),
            "modified": mtime,
            "has_dropdown": "dealSelect" in html,
            "chart_count": html.count("Plotly.newPlot"),
            "deal_count": len(set(__import__("re").findall(r'id="deal-([^"]+)"', html))),
            "has_residual": "Residual" in html,
            "has_tables": html.count("<table"),
        }
    return {"exists": False}


def get_validation():
    """Run validation and capture output."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_dashboard.py")],
            capture_output=True, text=True, timeout=10
        )
        return {"output": result.stdout.strip(), "passed": result.returncode == 0}
    except Exception as e:
        return {"output": str(e), "passed": False}


def main():
    status = {
        "timestamp": datetime.now().isoformat(),
        "db_stats": get_db_stats(),
        "preview": get_file_info(PREVIEW_HTML),
        "live": get_file_info(LIVE_HTML),
        "validation": get_validation(),
        "reingest_version_done": None,
    }
    # Check reingest version
    try:
        with open("/opt/.reingest_done") as f:
            status["reingest_version_done"] = f.read().strip()
    except:
        pass

    out = os.path.join(STATUS_DIR, "status.json")
    with open(out, "w") as f:
        json.dump(status, f, indent=2)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
