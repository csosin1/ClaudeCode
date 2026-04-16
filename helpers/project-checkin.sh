#!/usr/bin/env python3
"""
project-checkin.sh — periodic progress check on active project chats.

Not "is the chat alive" (watchdog does that), but "is it making progress
toward its goal?" Detects: stalled overnight work, dead background processes
the chat didn't notice, PROJECT_STATE.md going stale during active work.

Runs every 30 min via cron.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

CONF = Path("/etc/claude-projects.conf")
STATE_DIR = Path("/var/run/claude-sessions")
TMUX_SESSION = "claude"

# If a chat is busy (has "esc to interrupt" or recent activity) AND
# its PROJECT_STATE.md hasn't been touched in this many seconds,
# it's probably not following the update-every-30-min rule.
STALE_PROJECT_STATE_SEC = 3600  # 60 min — generous, to avoid false positives

# If a long-running job's heartbeat file is older than this, alert.
STALE_JOB_SEC = 1200  # 20 min

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

def capture_pane(name, lines=30):
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", f"{TMUX_SESSION}:{name}", "-p", "-S", f"-{lines}"],
        capture_output=True, text=True
    )
    return r.stdout if r.returncode == 0 else ""

def notify(msg, title, priority, click=""):
    subprocess.run(
        ["/usr/local/bin/notify.sh", msg, title, priority, click],
        check=False, timeout=10,
    )

def send_status_prompt(name):
    """Inject a status-check prompt into the chat. Uses non-blocking intake rule:
    if the chat is busy, it should spawn a subagent for this."""
    prompt = (
        "AUTOMATED CHECK-IN (from project-checkin cron, every 30 min). "
        "In 2-3 lines: (1) what are you working on right now, "
        "(2) are all background processes (ps check) still alive, "
        "(3) any blockers? Update PROJECT_STATE.md if stale. "
        "One-line reply, don't interrupt deep work for this."
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{TMUX_SESSION}:{name}", prompt, "Enter"],
        check=False, timeout=5,
    )
    # Submit in case paste-mode ate the Enter
    time.sleep(1)
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{TMUX_SESSION}:{name}", "Enter"],
        check=False, timeout=5,
    )

def should_checkin(debounce_file, interval_sec=1800):
    """Avoid checking in more than once per interval."""
    now = int(time.time())
    if debounce_file.exists():
        try:
            last = int(debounce_file.read_text().strip() or "0")
            if now - last < interval_sec:
                return False
        except ValueError:
            pass
    debounce_file.parent.mkdir(parents=True, exist_ok=True)
    debounce_file.write_text(str(now))
    return True

def check_long_jobs():
    """Check /var/www/landing/jobs/*.json for stalled heartbeats."""
    jobs_dir = Path("/var/www/landing/jobs")
    if not jobs_dir.exists():
        return
    now = int(time.time())
    for jf in jobs_dir.glob("*.json"):
        try:
            doc = json.loads(jf.read_text())
            if doc.get("status") not in ("running",):
                continue
            last_update = doc.get("last_update", "")
            if last_update:
                ts = datetime.fromisoformat(last_update.replace("Z", "+00:00")).timestamp()
                age = now - ts
                if age > STALE_JOB_SEC:
                    name = doc.get("name", jf.stem)
                    project = doc.get("project", "unknown")
                    # Check if PID is alive
                    pid = doc.get("pid")
                    pid_alive = pid and os.path.exists(f"/proc/{pid}")
                    if not pid_alive:
                        notify(
                            f"Long job '{name}' (project: {project}) — PID {pid} is DEAD, last heartbeat {int(age/60)}m ago. Check /var/log/jobs/ for logs.",
                            f"Job died: {name}",
                            "urgent",
                            f"https://casinv.dev/jobs.html",
                        )
                    else:
                        debounce = STATE_DIR / f"job-{name}.stale_alert"
                        if should_checkin(debounce, 1800):
                            notify(
                                f"Long job '{name}' alive (PID {pid}) but heartbeat stale ({int(age/60)}m). Possibly stuck.",
                                f"Job stale: {name}",
                                "default",
                                f"https://casinv.dev/jobs.html",
                            )
        except Exception:
            continue

def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    projects = load_projects()
    now = int(time.time())

    for name, cwd in projects:
        if not tmux_has_window(name):
            continue  # watchdog/respawn handles missing windows

        cap = capture_pane(name)
        is_busy = "esc to interrupt" in cap

        # Check PROJECT_STATE.md freshness only if the chat looks active
        ps_path = Path(cwd) / "PROJECT_STATE.md"
        if ps_path.exists() and is_busy:
            mtime = ps_path.stat().st_mtime
            age = now - mtime
            if age > STALE_PROJECT_STATE_SEC:
                debounce = STATE_DIR / f"{name}.checkin_stale_ps"
                if should_checkin(debounce, STALE_PROJECT_STATE_SEC):
                    notify(
                        f"{name} has been busy but PROJECT_STATE.md is {int(age/60)}m stale. Sending check-in prompt.",
                        f"Stale state: {name}",
                        "default",
                        f"https://casinv.dev/remote/{name}.html",
                    )
                    send_status_prompt(name)

        # For idle chats with in-progress tasks: check if they SHOULD be doing something
        # (This catches the "chat respawned after OOM but forgot it had a running job" case)
        if not is_busy:
            # Read tasks.json to see if this project has an in_progress task
            try:
                tasks = json.loads(Path("/var/www/landing/tasks.json").read_text())
                proj_task = tasks.get("projects", {}).get(name, {})
                cur = proj_task.get("current_task")
                if cur and cur.get("stage") not in ("done", "blocked", None):
                    debounce = STATE_DIR / f"{name}.checkin_idle_with_task"
                    if should_checkin(debounce, 1800):
                        notify(
                            f"{name} is IDLE but has an in-progress task: '{cur.get('name', '?')}'. May need a nudge.",
                            f"Idle with task: {name}",
                            "default",
                            f"https://casinv.dev/remote/{name}.html",
                        )
                        send_status_prompt(name)
            except Exception:
                pass

    # Also check long-running jobs
    check_long_jobs()

if __name__ == "__main__":
    main()
