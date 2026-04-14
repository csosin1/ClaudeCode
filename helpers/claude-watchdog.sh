#!/usr/bin/env python3
"""
claude-watchdog.sh — scan tmux panes for each expected Claude project window.
Writes /var/www/landing/liveness.json and fires notify.sh when a session has
been working with no output for >= STUCK_THRESHOLD seconds.

Intended to run every minute via cron.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CONF = Path("/etc/claude-projects.conf")
STATE_DIR = Path("/var/run/claude-sessions")
LIVENESS_PATH = Path("/var/www/landing/liveness.json")
TMUX_SESSION = "claude"
STUCK_THRESHOLD = 600    # seconds of single-activity silence → stuck
REALERT_AFTER = 1200     # don't re-notify within this many seconds

ELAPSED_RE = re.compile(r"\((?:(\d+)h )?(?:(\d+)m )?(\d+)s")
ACTIVITY_RE = re.compile(r"([A-Z][a-zA-Z]+ing…|[A-Z][a-zA-Z]+ed for)")

def load_projects():
    if not CONF.exists():
        return []
    out = []
    for line in CONF.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out

def tmux_has_window(name):
    r = subprocess.run(
        ["tmux", "list-windows", "-t", TMUX_SESSION, "-F", "#W"],
        capture_output=True, text=True
    )
    return r.returncode == 0 and name in r.stdout.split()

def capture_pane(name, lines=40):
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", f"{TMUX_SESSION}:{name}", "-p", "-S", f"-{lines}"],
        capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else ""

def parse_elapsed(text):
    # find the *last* elapsed marker, which is the current activity's timer
    matches = ELAPSED_RE.findall(text)
    if not matches:
        return 0
    h, m, s = matches[-1]
    return int(h or 0) * 3600 + int(m or 0) * 60 + int(s or 0)

def notify(msg, title, priority, click):
    try:
        subprocess.run(
            ["/usr/local/bin/notify.sh", msg, title, priority, click],
            check=False, timeout=10
        )
    except Exception:
        pass

def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LIVENESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects = load_projects()
    now = int(time.time())
    result = {}

    for name, cwd in projects:
        entry = {"cwd": cwd, "status": "archived", "activity": "window missing",
                 "elapsed_s": 0}

        if tmux_has_window(name):
            cap = capture_pane(name)
            if "esc to interrupt" in cap:
                elapsed = parse_elapsed(cap)
                activities = ACTIVITY_RE.findall(cap)
                activity = activities[-1] if activities else "working"
                entry["status"] = "busy"
                entry["activity"] = activity
                entry["elapsed_s"] = elapsed

                if elapsed >= STUCK_THRESHOLD:
                    entry["status"] = "stuck"
                    last_alert_file = STATE_DIR / f"{name}.watchdog.last_alert"
                    last_alert = 0
                    if last_alert_file.exists():
                        try:
                            last_alert = int(last_alert_file.read_text().strip() or "0")
                        except ValueError:
                            last_alert = 0
                    if now - last_alert >= REALERT_AFTER:
                        minutes = elapsed // 60
                        notify(
                            f"{name} has been on '{activity}' for {minutes}m with no status update",
                            f"Claude stuck: {name}",
                            "urgent",
                            f"https://casinv.dev/remote/{name}.html",
                        )
                        last_alert_file.write_text(str(now))
            else:
                entry["status"] = "idle"
                entry["activity"] = "idle"

        result[name] = entry

    doc = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "projects": result}
    tmp = LIVENESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(LIVENESS_PATH)

if __name__ == "__main__":
    main()
