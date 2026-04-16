#!/usr/bin/env python3
"""
branch-audit.sh — surface stale / abandoned feature branches across site-deploy.
Runs weekly. Fires a notify.sh with a summary. Does NOT auto-delete or auto-rebase —
user decision on each.

Thresholds:
  STALE_DAYS = 14   # branches with no commits for >14 days
  BEHIND_MAIN = 200  # merge-base is >N commits behind current main
"""
import subprocess
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = "/opt/site-deploy"
STALE_DAYS = 14
BEHIND_MAIN = 200
OUT = Path("/var/www/landing/branch-audit.json")

def git(*args):
    r = subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""

def main():
    git("fetch", "--prune", "--all", "--quiet")
    main_head = git("rev-parse", "origin/main")
    now = datetime.now(timezone.utc)

    # List remote feature branches (claude/*)
    refs = git("for-each-ref", "--format=%(refname:short)|%(committerdate:iso-strict)",
               "refs/remotes/origin/claude/").splitlines()

    stale = []
    behind = []
    fresh = []

    for line in refs:
        if "|" not in line:
            continue
        ref, iso = line.split("|", 1)
        try:
            last_commit = datetime.fromisoformat(iso)
        except ValueError:
            continue
        age_days = (now - last_commit).days

        merge_base = git("merge-base", ref, "origin/main")
        behind_count = int(git("rev-list", "--count", f"{merge_base}..origin/main") or "0")
        ahead_count  = int(git("rev-list", "--count", f"{merge_base}..{ref}") or "0")

        entry = {
            "ref": ref.replace("origin/", ""),
            "last_commit": iso[:19],
            "age_days": age_days,
            "behind_main": behind_count,
            "unique_commits": ahead_count,
        }

        if age_days > STALE_DAYS:
            stale.append(entry)
        elif behind_count > BEHIND_MAIN:
            behind.append(entry)
        else:
            fresh.append(entry)

    doc = {
        "updated_at": now.isoformat(timespec="seconds"),
        "thresholds": {"stale_days": STALE_DAYS, "behind_main": BEHIND_MAIN},
        "stale": sorted(stale, key=lambda e: -e["age_days"]),
        "behind": sorted(behind, key=lambda e: -e["behind_main"]),
        "fresh": sorted(fresh, key=lambda e: -e["age_days"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2))

    # Notify if there's anything actionable
    n_stale = len(stale)
    n_behind = len(behind)
    if n_stale or n_behind:
        msg = f"{n_stale} stale (>{STALE_DAYS}d), {n_behind} behind (>{BEHIND_MAIN} commits). Review at /branch-audit.json"
        subprocess.run(
            ["/usr/local/bin/notify.sh", msg, "Branch audit", "default",
             "https://casinv.dev/branch-audit.json"],
            check=False, timeout=10,
        )

if __name__ == "__main__":
    main()
