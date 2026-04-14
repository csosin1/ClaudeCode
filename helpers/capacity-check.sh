#!/usr/bin/env python3
"""
capacity-check.sh — writes /var/www/landing/capacity.json and fires notify.sh
when RAM / swap / disk / load cross thresholds.

Runs every 5 min via cron. Debounces alerts so the user isn't spammed.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("/var/www/landing/capacity.json")
STATE_DIR = Path("/var/run/claude-sessions")
REALERT_AFTER = 1800  # 30 min between same-severity re-alerts

# Thresholds: (warn, urgent) in %
RAM_WARN, RAM_URGENT = 75, 90
SWAP_WARN, SWAP_URGENT = 25, 75
DISK_WARN, DISK_URGENT = 70, 85
LOAD_WARN_MULT, LOAD_URGENT_MULT = 1.5, 3.0  # × cores

def read_meminfo():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        info[k.strip()] = int(v.strip().split()[0]) * 1024  # bytes
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    used = total - available
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = swap_total - swap_free
    return {
        "ram_total": total, "ram_used": used,
        "ram_pct": round(100 * used / total, 1) if total else 0,
        "swap_total": swap_total, "swap_used": swap_used,
        "swap_pct": round(100 * swap_used / swap_total, 1) if swap_total else 0,
    }

def read_disk():
    r = subprocess.run(["df", "-B1", "/"], capture_output=True, text=True)
    parts = r.stdout.splitlines()[1].split()
    total = int(parts[1]); used = int(parts[2])
    return {"disk_total": total, "disk_used": used,
            "disk_pct": round(100 * used / total, 1) if total else 0}

def read_load():
    load1, load5, load15 = os.getloadavg()
    cores = os.cpu_count() or 1
    return {"load_1m": load1, "load_5m": load5, "load_15m": load15,
            "cores": cores, "load_ratio": round(load15 / cores, 2)}

def severity(metric, value, warn, urgent):
    if value >= urgent: return "urgent"
    if value >= warn:   return "warn"
    return "ok"

def should_alert(key, sev):
    """Debounce: only alert if (a) we haven't alerted for this key at this severity
    in REALERT_AFTER seconds, or (b) the severity just escalated."""
    f = STATE_DIR / f"capacity-{key}.state"
    prev_sev, prev_ts = "ok", 0
    if f.exists():
        try:
            prev_sev, ts_str = f.read_text().strip().split("|")
            prev_ts = int(ts_str)
        except Exception:
            pass
    now = int(time.time())
    if sev == "ok" and prev_sev == "ok":
        return False
    # Write current state
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"{sev}|{now}")
    if sev == "ok":  # recovery
        return prev_sev != "ok"
    if sev != prev_sev:  # escalation (or first alert)
        return True
    # Same elevated sev — re-alert only if debounce expired
    return (now - prev_ts) >= REALERT_AFTER

def notify(msg, title, priority):
    subprocess.run(
        ["/usr/local/bin/notify.sh", msg, title, priority,
         "https://casinv.dev/capacity.html"],
        check=False, timeout=10,
    )

def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mem = read_meminfo()
    disk = read_disk()
    load = read_load()

    sev = {
        "ram":  severity("ram",  mem["ram_pct"],  RAM_WARN,  RAM_URGENT),
        "swap": severity("swap", mem["swap_pct"], SWAP_WARN, SWAP_URGENT),
        "disk": severity("disk", disk["disk_pct"], DISK_WARN, DISK_URGENT),
        "load": severity("load", load["load_ratio"],
                         LOAD_WARN_MULT, LOAD_URGENT_MULT),
    }
    overall = ("urgent" if "urgent" in sev.values()
               else "warn" if "warn" in sev.values()
               else "ok")

    # Fire notifications per-metric with debouncing
    alerts = []
    if should_alert("ram", sev["ram"]):
        if sev["ram"] == "ok":
            alerts.append(("RAM recovered", "default"))
        else:
            alerts.append((f"RAM {sev['ram']}: {mem['ram_pct']}% used", sev["ram"]))
    if should_alert("swap", sev["swap"]):
        if sev["swap"] == "ok":
            alerts.append(("Swap recovered", "default"))
        else:
            alerts.append((f"Swap {sev['swap']}: {mem['swap_pct']}% used", sev["swap"]))
    if should_alert("disk", sev["disk"]):
        if sev["disk"] == "ok":
            alerts.append(("Disk recovered", "default"))
        else:
            alerts.append((f"Disk {sev['disk']}: {disk['disk_pct']}% used", sev["disk"]))
    if should_alert("load", sev["load"]):
        if sev["load"] == "ok":
            alerts.append(("Load recovered", "default"))
        else:
            alerts.append((f"Load {sev['load']}: {load['load_ratio']}× cores", sev["load"]))

    for msg, prio in alerts:
        notify(msg, "Droplet capacity", prio)

    doc = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overall": overall,
        "ram":  {"pct": mem["ram_pct"],  "used_gb": round(mem["ram_used"]/1e9,2),
                 "total_gb": round(mem["ram_total"]/1e9,2), "severity": sev["ram"]},
        "swap": {"pct": mem["swap_pct"], "used_gb": round(mem["swap_used"]/1e9,2),
                 "total_gb": round(mem["swap_total"]/1e9,2), "severity": sev["swap"]},
        "disk": {"pct": disk["disk_pct"], "used_gb": round(disk["disk_used"]/1e9,2),
                 "total_gb": round(disk["disk_total"]/1e9,2), "severity": sev["disk"]},
        "load": {"load_1m": round(load["load_1m"],2),
                 "load_15m": round(load["load_15m"],2),
                 "cores": load["cores"],
                 "ratio": load["load_ratio"], "severity": sev["load"]},
        "thresholds": {
            "ram":  {"warn": RAM_WARN,  "urgent": RAM_URGENT},
            "swap": {"warn": SWAP_WARN, "urgent": SWAP_URGENT},
            "disk": {"warn": DISK_WARN, "urgent": DISK_URGENT},
            "load": {"warn": f"{LOAD_WARN_MULT}× cores",
                     "urgent": f"{LOAD_URGENT_MULT}× cores"},
        },
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(OUT)

if __name__ == "__main__":
    main()
