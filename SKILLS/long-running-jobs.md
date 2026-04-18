---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Long-Running Jobs (systemd + heartbeat + watchdog)

## When to use

Use this skill when working on long-running jobs (systemd + heartbeat + watchdog). (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Any job expected to run longer than 15 minutes must be durable against Claude session death, OOM, and droplet churn.** The job's lifetime and the chat's lifetime are independent. If you launch a multi-hour ingest via `nohup bash -c '...' &` from an interactive Claude Code shell, you have a single point of failure — when the Claude session goes stale (remote-control relay drops, tmux hiccup) you've lost observability, and one OOM takes the whole thing down with no alerting.

Three-layer pattern that avoids this:

1. **systemd** runs the job (survives session death, enforces memory caps, auto-restarts on failure).
2. **Heartbeat file** lets anything on the droplet see progress at a glance.
3. **Watchdog cron** reads heartbeats + systemd status, alerts via push notification on stale / failed jobs.

## When To Use

- Any ABS / SEC / data ingest scoped to more than ~15 minutes of wall time.
- Multi-deal / multi-file batch jobs with >10 items.
- Model-training runs.
- Any scrape / crawl / long-running Playwright session.
- **Short jobs (<15 min) are exempt** — a `nohup bash &` backgrounded from Claude is fine.

## The Pattern

### Layer 1 — Launch via systemd (not nohup bash)

Use `systemd-run` for transient services (no service file to install):

```bash
systemd-run \
    --unit=<project>-<job-name> \
    --description="<one-line description>" \
    --property=MemoryMax=1800M \
    --property=Restart=on-failure \
    --property=RestartSec=30 \
    /path/to/worker.sh
```

Key properties:
- `MemoryMax=` — cgroup cap. If the job exceeds this, the kernel kills it cleanly inside its own cgroup, leaving the rest of the droplet untouched. Set it to the peak you can tolerate given other tenants on the host.
- `Restart=on-failure` — if the worker exits with non-zero (e.g. OOM, crash), systemd restarts it after `RestartSec`. Worker MUST be idempotent — each restart should resume from durable state, not reprocess work already committed.
- `--unit=` — stable name so you can `systemctl status <unit>`, `journalctl -u <unit>`.

For services that need to survive forever (not ad-hoc), write a proper `.service` file under `/etc/systemd/system/` with the same properties.

### Layer 2 — Heartbeat file

Every long-running job writes `/var/log/<project>/heartbeat.json` at every unit of work completed (every item, every minute, whichever is more frequent). JSON schema:

```json
{
    "job": "<project>-<job-name>",
    "started": 1776260000,
    "last_tick": 1776261111,
    "items_done": 7,
    "items_total": 33,
    "item_current": "deal-2019-4",
    "status": "running",
    "stale_after_seconds": 1800,
    "systemd_unit": "abs-ingest-carmax",
    "log_path": "/var/log/abs-dashboard/ingest.log"
}
```

Required fields: `job`, `last_tick` (unix epoch), `status` ∈ {`running`, `done`, `failed`}.
Optional but strongly recommended: `items_done`, `items_total`, `item_current`, `stale_after_seconds` (per-job threshold for what counts as stale — default 20 min), `systemd_unit`.

Write atomically: `heartbeat.json.tmp` → `os.replace()`. Never a half-written heartbeat.

**Best:** embed the heartbeat write directly in the worker's main loop (after every item).
**Acceptable fallback** for an in-flight job you can't modify: run a log-tail watcher alongside (like `deploy/heartbeat_writer.py` for abs-dashboard).

### Layer 3 — Watchdog + push alerting

`/usr/local/bin/monitor-long-jobs.sh` runs every 5 min via `/etc/cron.d/monitor-long-jobs`. It:

1. Iterates every `/var/log/*/heartbeat.json` + `/opt/*/heartbeat.json`.
2. For each: if `status` is failed/done, alert once (dedup via `/var/lib/monitor-long-jobs/alert-<key>`).
3. Else if `now - last_tick > stale_after_seconds`, alert (stale).
4. Else if a `systemd_unit` is named and `systemctl is-active` reports failed, alert.
5. Alert = push notification via `/usr/local/bin/notify.sh` with priority `urgent` for failures, `default` for completions. Dedup: re-alert at most once per hour per job.

User gets a push on their phone when something's wrong — even if Claude is offline, even if the relay is stale.

## Minimum working example

```bash
# Worker script (abs-dashboard/deploy/ingest_kmx.sh) writes heartbeat each deal:
cat > deploy/ingest_kmx.sh <<'EOF'
#!/bin/bash
set -euo pipefail
HB=/var/log/abs-dashboard/heartbeat.json
DEALS="2019-4 2020-1 ... 2026-1"
total=$(echo "$DEALS" | wc -w)
done_count=0
for d in $DEALS; do
    python3 -c "
import json, os, time
hb = {'job': 'abs-ingest-kmx', 'last_tick': int(time.time()),
      'items_done': $done_count, 'items_total': $total,
      'item_current': '$d', 'status': 'running',
      'stale_after_seconds': 1800,
      'systemd_unit': 'abs-ingest-kmx'}
os.makedirs(os.path.dirname('$HB'), exist_ok=True)
with open('$HB.tmp', 'w') as f: json.dump(hb, f)
os.replace('$HB.tmp', '$HB')
"
    python3 -m carmax_abs.run_ingestion --deal "$d"
    done_count=$((done_count + 1))
done
# mark done
python3 -c "import json, time; json.dump({'job':'abs-ingest-kmx','last_tick':int(time.time()),'status':'done','items_done':$done_count,'items_total':$total}, open('$HB','w'))"
EOF
chmod +x deploy/ingest_kmx.sh

# Launch under systemd:
systemd-run --unit=abs-ingest-kmx \
    --description="CarMax ABS-EE loan-level ingest" \
    --property=MemoryMax=1800M \
    --property=Restart=on-failure \
    --property=RestartSec=60 \
    /opt/abs-dashboard/deploy/ingest_kmx.sh
```

## Anti-patterns (what kills multi-hour jobs)

- **`nohup bash -c '...' &` from Claude Code shell.** Wrapper dies when the parent tree has issues. No auto-restart, no heartbeat, no alerting.
- **Silent success = fine assumption.** "I'll just check back in 2 hours." That's 2 hours of blindness.
- **`>= 15 min job` dispatched without heartbeat.** You won't know it died until you look.
- **`systemd-run` without `MemoryMax=`** on a memory-pressured host. An unbounded job will OOM the droplet's other tenants.
- **No `Restart=on-failure`.** Auto-restart is free and eliminates an entire class of "had to restart it by hand" work.
- **Heartbeat every hour instead of every item.** Your stale-detection window needs to be smaller than your item duration. If you process one item per 15 min, heartbeat every item.

## Resumability checklist

Before launching, confirm:
- [ ] Every item's work is idempotent. Re-running an already-done item is a no-op or makes zero-cost updates.
- [ ] Progress is committed to disk (DB write, file write) at the end of each item, not only at the end of the run.
- [ ] A fresh start from a stopped run can skip already-done items (query DB for what's done; don't re-do).
- [ ] Heartbeat write happens AFTER commit, not before.

## Integration

- Companion: `SKILLS/session-resilience.md` — handles the "Claude session died mid-work" case. This skill handles "the job outlives the session."
- Companion: `SKILLS/capacity-monitoring.md` — before kicking off a big job, check `/capacity.json`. Don't launch multi-hour jobs when the droplet is already `urgent`.
- When any OOM occurs during a job: log to `LESSONS.md` with the peak RSS + trigger conditions, so `MemoryMax=` is tuned for next time.
- If the watchdog fires: the alert must identify the job, unit, and log path so the recipient can diagnose without logging in blind.

## Incident reference

2026-04-15 abs-dashboard: 33-deal CarMax ingest launched via `nohup bash -c '...' &`. Python OOMed during 2019-4 at 04:40 UTC (2.5 GB RSS, 4 GB host with other tenants). Bash wrapper also terminated shortly after. No watchdog, no alerting. Failure went undetected for ~9 hours until user asked about status manually. Fix: this skill. Cost: ~9 hours of lost ingest throughput + manual discovery + resume.
