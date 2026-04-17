#!/bin/bash
# spend-audit.sh — join paid-calls.jsonl + events.jsonl + project DBs, produce prose summary.
#
# Usage:
#   spend-audit.sh [--since=<duration>]
#
# <duration> accepts: Nh (hours), Nd (days), Nm (minutes). Default: 24h.
#
# Output: one line per project with cost + event counts, optional anomaly lines
# prefixed [ANOMALY], plus a final "Anomalies: N" summary line. Exits 0 always.

set -u

SINCE="24h"
for arg in "$@"; do
    case "$arg" in
        --since=*) SINCE="${arg#--since=}" ;;
    esac
done

PAID_LOG="${PAID_CALL_LOG:-/var/log/paid-calls.jsonl}"
EVENTS_LOG="${LOG_EVENT_LOG:-/var/log/events.jsonl}"
KNOWN_PURPOSES="${PAID_CALL_KNOWN_PURPOSES:-/etc/paid-call-known-purposes.conf}"

python3 - "$SINCE" "$PAID_LOG" "$EVENTS_LOG" "$KNOWN_PURPOSES" <<'PY'
import json, os, re, sqlite3, sys, datetime, collections, subprocess

since_arg, paid_log, events_log, known_purposes_file = sys.argv[1:5]

# Parse --since= into seconds
m = re.match(r'^(\d+)([hdm])$', since_arg)
if not m:
    print(f"spend-audit: invalid --since='{since_arg}' (expected e.g. 24h, 7d, 30m)", file=sys.stderr)
    sys.exit(0)
n, unit = int(m.group(1)), m.group(2)
unit_seconds = {'h': 3600, 'd': 86400, 'm': 60}[unit]
window_seconds = n * unit_seconds

now = datetime.datetime.now(datetime.timezone.utc)
since = now - datetime.timedelta(seconds=window_seconds)
baseline_since = now - datetime.timedelta(days=7)

def parse_ts(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

def read_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue

# ---- Load known purposes for anomaly detection
known_purposes = set()
if os.path.exists(known_purposes_file):
    with open(known_purposes_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            known_purposes.add(line)

# ---- Bucket paid calls
# Per (project, vendor, purpose): sum cost in window + baseline-window.
# Count only "starting" rows to avoid double-counting complete/failed pairs.
paid_window_by_project = collections.defaultdict(lambda: collections.defaultdict(float))   # project -> vendor -> $
paid_window_by_project_purpose = collections.defaultdict(lambda: collections.defaultdict(float))  # project -> (vendor,purpose) -> $
paid_baseline_by_project_purpose = collections.defaultdict(lambda: collections.defaultdict(float))  # 7d total
failed_burn_by_project = collections.defaultdict(float)  # failed rows -> cost burned
purposes_seen = set()
event_ids_paid = collections.defaultdict(list)  # event_id -> list of (vendor, cost)
unknown_purpose_lines = []

for row in read_jsonl(paid_log):
    ts = parse_ts(row.get('ts', ''))
    if not ts:
        continue
    vendor = row.get('vendor', '')
    project = row.get('project', '')
    purpose = row.get('purpose', '')
    status = row.get('status', '')
    try:
        cost = float(row.get('est_cost_usd') or 0)
    except Exception:
        cost = 0.0

    if status == 'starting':
        if ts >= baseline_since:
            paid_baseline_by_project_purpose[project][(vendor, purpose)] += cost
        if ts >= since:
            paid_window_by_project[project][vendor] += cost
            paid_window_by_project_purpose[project][(vendor, purpose)] += cost
            purposes_seen.add(f"{project}:{purpose}")
            eid = row.get('event_id') or ''
            if eid:
                event_ids_paid[eid].append((vendor, cost))
    elif status == 'failed' and ts >= since:
        failed_burn_by_project[project] += cost

# ---- Bucket events from events.jsonl
events_by_project = collections.defaultdict(lambda: collections.defaultdict(int))   # project -> event_type -> count
events_baseline = collections.defaultdict(lambda: collections.defaultdict(int))
event_ids_logged = collections.defaultdict(list)

for row in read_jsonl(events_log):
    ts = parse_ts(row.get('ts', ''))
    if not ts:
        continue
    project = row.get('project', '')
    etype = row.get('event_type', '')
    if ts >= baseline_since:
        events_baseline[project][etype] += 1
    if ts >= since:
        events_by_project[project][etype] += 1
        eid = row.get('event_id') or ''
        if eid:
            event_ids_logged[eid].append(project)

# ---- Project-specific DB fallbacks for projects that don't emit events yet
# Tolerant of missing tables/columns — failure = skip with note.
def db_count_since(db_path, query, args):
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        cur = conn.cursor()
        cur.execute(query, args)
        n = cur.fetchone()[0]
        conn.close()
        return int(n or 0)
    except Exception as e:
        return None

def mtime_in_window(path):
    if not os.path.exists(path):
        return 0
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path), tz=datetime.timezone.utc)
    return 1 if mtime >= since else 0

db_fallbacks = {}
since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")

# car-offers: offers.ran_at is ISO8601-ish. Try each candidate; sum successes; skip failures.
co_total = 0
co_any_success = False
co_last_error_db = None
for db in ("/opt/car-offers/offers.db", "/opt/car-offers-preview/offers.db"):
    if not os.path.exists(db):
        continue
    n = db_count_since(db, "SELECT COUNT(*) FROM offers WHERE ran_at >= ?", (since_iso,))
    if n is None:
        co_last_error_db = db
    else:
        co_any_success = True
        co_total += n
if co_any_success:
    db_fallbacks['car-offers'] = {'offers_rows_ran_at': co_total}
elif co_last_error_db:
    db_fallbacks['car-offers'] = {'note': f"DB query failed for {co_last_error_db}, skipping"}

# carvana-abs + carmax-abs: mtime on dashboard.db
db_fallbacks['carvana-abs'] = {
    'dashboard_refreshes': mtime_in_window("/opt/abs-dashboard/carvana_abs/db/dashboard.db")
}
db_fallbacks['carmax-abs'] = {
    'dashboard_refreshes': mtime_in_window("/opt/abs-dashboard/carmax_abs/db/dashboard.db")
}

# timeshare-surveillance: combined.json mtime
ts_json_candidates = [
    "/opt/timeshare-surveillance-preview/data/combined.json",
    "/opt/timeshare-surveillance-preview/dashboard/data/combined.json",
    "/opt/timeshare-surveillance/data/combined.json",
]
for p in ts_json_candidates:
    if os.path.exists(p):
        db_fallbacks['timeshare-surveillance'] = {'combined_refreshed': mtime_in_window(p)}
        break

# gym-intelligence: snapshots table with timestamp column, best-effort
gym_db = "/opt/gym-intelligence/gyms.db"
if os.path.exists(gym_db):
    # Probe schema for a timestamp-like column
    try:
        conn = sqlite3.connect(f"file:{gym_db}?mode=ro", uri=True, timeout=2.0)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(snapshots)")
        cols = [r[1] for r in cur.fetchall()]
        ts_col = None
        for c in ('captured_at', 'created_at', 'ts', 'timestamp', 'snapshot_at'):
            if c in cols:
                ts_col = c
                break
        if ts_col:
            cur.execute(f"SELECT COUNT(*) FROM snapshots WHERE {ts_col} >= ?", (since_iso,))
            n = cur.fetchone()[0] or 0
            db_fallbacks['gym-intelligence'] = {'snapshots': int(n)}
        else:
            db_fallbacks['gym-intelligence'] = {'note': 'no timestamp column on snapshots, skipping'}
        conn.close()
    except Exception:
        db_fallbacks['gym-intelligence'] = {'note': 'gyms.db query failed, skipping'}

# ---- Emit prose summary
all_projects = set(paid_window_by_project.keys()) | set(events_by_project.keys()) | set(db_fallbacks.keys())

def fmt_usd(x):
    return f"${x:.2f}" if x >= 0.01 else f"${x:.3f}"

lines = []
anomaly_count = 0

def project_line(project):
    global anomaly_count
    spend_by_vendor = paid_window_by_project.get(project, {})
    total_spend = sum(spend_by_vendor.values())
    events = events_by_project.get(project, {})
    total_events = sum(events.values())
    fallback = db_fallbacks.get(project, {}) or {}
    fallback_events = sum(v for k, v in fallback.items() if isinstance(v, int))

    parts = []

    # Events section
    if events:
        ev_str = ", ".join(f"{c} {t}" for t, c in sorted(events.items(), key=lambda kv: -kv[1]))
        parts.append(ev_str)
    elif fallback_events > 0:
        ev_str = ", ".join(f"{v} {k}" for k, v in fallback.items() if isinstance(v, int) and v > 0)
        parts.append(f"{ev_str} (from DB)")
    elif 'note' in fallback:
        parts.append(fallback['note'])

    # Spend section
    if spend_by_vendor:
        sp_str = " + ".join(f"{fmt_usd(v)} {k}" for k, v in sorted(spend_by_vendor.items(), key=lambda kv: -kv[1]))
        parts.append(f"{sp_str} = {fmt_usd(total_spend)}")

    # Cost-per-event + baseline comparison
    effective_events = total_events if total_events > 0 else fallback_events
    if total_spend > 0 and effective_events > 0:
        cpe = total_spend / effective_events
        # Baseline: total 7-day paid for project / total 7-day events for project
        base_spend = sum(paid_baseline_by_project_purpose.get(project, {}).values())
        base_events = sum(events_baseline.get(project, {}).values())
        if base_events > 0:
            base_cpe = base_spend / base_events
            parts.append(f"cost/event {fmt_usd(cpe)} (7-day avg {fmt_usd(base_cpe)})")
            # Anomaly: cost/event > 3x baseline
            if base_cpe > 0 and cpe > 3 * base_cpe:
                return f"[ANOMALY] {project} ({since_arg}): " + ". ".join(parts), True
        else:
            parts.append(f"cost/event {fmt_usd(cpe)} (no 7-day baseline)")

    # Failed-burn anomaly
    burned = failed_burn_by_project.get(project, 0.0)
    if burned > 0:
        parts.append(f"failures burned {fmt_usd(burned)}")

    # Anomaly A: spend > 0 and no events in window
    if total_spend > 0 and total_events == 0 and fallback_events == 0:
        return f"[ANOMALY] {project} ({since_arg}): {fmt_usd(total_spend)} spent with no events detected. " + ". ".join(parts), True

    if not parts:
        return None, False

    return f"{project} ({since_arg}): " + ". ".join(parts), False

for project in sorted(all_projects):
    line, is_anom = project_line(project)
    if line is None:
        continue
    if is_anom:
        anomaly_count += 1
    lines.append(line)

# Unknown-purpose anomaly (separate, one line listing them)
unknown = sorted(p for p in purposes_seen if p not in known_purposes)
if unknown:
    anomaly_count += 1
    lines.append(f"[ANOMALY] Unknown purpose tags in window: {', '.join(unknown)}. Register in /etc/paid-call-known-purposes.conf.")

if not lines:
    lines.append(f"No paid-call or event activity in window (since={since_arg}).")

print("\n".join(lines))
print(f"Anomalies: {anomaly_count}" + ("" if anomaly_count == 0 else " (see above)"))
PY
