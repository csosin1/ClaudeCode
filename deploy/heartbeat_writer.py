#!/usr/bin/env python3
"""Emit a heartbeat for the CarMax loan-level ingest by parsing the running log.

Intended to run as a background poller alongside the ingest. Writes
/var/log/abs-dashboard/heartbeat.json every 30 seconds.

For NEW jobs, embed heartbeat writes directly in the worker loop (see
SKILLS/long-running-jobs.md). This log-tail variant exists for the one
in-flight job we don't want to kill.
"""
import json
import os
import re
import time
from pathlib import Path

LOG = Path("/var/log/abs-dashboard/ingest_kmx_loanlevel.log")
HEARTBEAT = Path("/var/log/abs-dashboard/heartbeat.json")
TOTAL_DEALS = 33  # 2017-4 through 2026-1

DONE_RE = re.compile(r"=== Deal (\S+) done ===")
START_RE = re.compile(r"=== Deal (\S+) ===")


def scan_log():
    if not LOG.exists():
        return {"items_done": 0, "item_current": None}
    done = []
    last_start = None
    with LOG.open() as f:
        for line in f:
            m = DONE_RE.search(line)
            if m:
                done.append(m.group(1))
                continue
            m = START_RE.search(line)
            if m:
                last_start = m.group(1)
    current = None
    if last_start and last_start not in set(done):
        current = last_start
    return {
        "items_done": len(done),
        "item_current": current,
        "done_list": done[-5:],  # tail
    }


def ingest_is_running():
    # Any bash wrapper or python subprocess for run_ingestion?
    try:
        import subprocess
        out = subprocess.run(
            ["pgrep", "-af", "run_ingestion"],
            capture_output=True, text=True, timeout=5
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def main_loop():
    os.makedirs(HEARTBEAT.parent, exist_ok=True)
    while True:
        scan = scan_log()
        running = ingest_is_running()
        status = "running" if running else ("done" if scan["items_done"] >= TOTAL_DEALS else "failed")
        hb = {
            "job": "abs-dashboard-carmax-ingest",
            "started": int(time.time()),  # approx; true start at 01:50 UTC originally
            "last_tick": int(time.time()),
            "items_done": scan["items_done"],
            "items_total": TOTAL_DEALS,
            "item_current": scan["item_current"] or "(between deals)",
            "recent_done": scan["done_list"],
            "ingest_process_alive": running,
            "status": status,
            "stale_after_seconds": 1800,  # 30 min between deal-completions is suspicious
            "log_path": str(LOG),
        }
        with open(str(HEARTBEAT) + ".tmp", "w") as f:
            json.dump(hb, f, indent=2)
        os.replace(str(HEARTBEAT) + ".tmp", str(HEARTBEAT))
        time.sleep(30)


if __name__ == "__main__":
    main_loop()
