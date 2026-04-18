#!/bin/bash
# Daily: pull latest SEC EDGAR filings, rebuild analysis, regenerate dashboard,
# and promote preview → live. Runs via cron.
#
# Markov re-run is DATA-TRIGGERED: we only re-run unified_markov.py when this
# cycle actually inserted new rows into pool_performance or loan_performance.
# The model inputs are a pure function of those tables (plus covariates that
# don't change intraday), so with no new filings there's no reason to redo
# the ~2hr optimisation. Stale deal_forecasts is strictly better than
# no-dashboard, so Markov failures are non-fatal to the rest of the pipeline.
#
# Env vars:
#   ABS_CRON_DRY_RUN=1  Skip the actual Markov re-run; log what would happen.
#                       Used for validating new-data detection logic.
set -u
LOG=/var/log/abs-ingestion.log
STATE_DIR=/var/lib/abs-dashboard
STATE_FILE="$STATE_DIR/cron_state.json"
mkdir -p "$(dirname "$LOG")" "$STATE_DIR"
echo "===== $(date -u) start =====" >> "$LOG"

cd /opt/abs-dashboard
# Pull latest code first so any fixes/changes go live with today's data.
git pull --ff-only origin claude/carvana-loan-dashboard-4QMPM >> "$LOG" 2>&1 || true

cd /opt/abs-dashboard/carvana_abs
export SEC_USER_AGENT="Clifford Sosin clifford.sosin@casinvestmentpartners.com"
PY=/opt/abs-venv/bin/python
CARVANA_DB=/opt/abs-dashboard/carvana_abs/db/carvana_abs.db
CARMAX_DB=/opt/abs-dashboard/carmax_abs/db/carmax_abs.db

# Helper: snapshot (count, max_rowid) for each (db, table) combo to JSON.
# Prints compact JSON to stdout. Missing tables -> zeros.
#
# pool_performance: COUNT(*) is cheap (<20K rows) and doubles as tamper-check.
# loan_performance: uses MAX(rowid) only — COUNT(*) on 100M rows takes ~60s
# and rowid is monotonic on INSERT-only ingest. We record count as -1 to signal
# "not measured"; diff logic only compares MAX(rowid) for that table.
snapshot_counts() {
    $PY - "$CARVANA_DB" "$CARMAX_DB" <<'PYEOF'
import json, sqlite3, sys
out = {}
for path in sys.argv[1:]:
    key = path
    out[key] = {}
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        out[key] = {"pool_performance": [0, 0], "loan_performance": [-1, 0]}
        continue
    # pool_performance — small, full count
    try:
        row = c.execute("SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM pool_performance").fetchone()
        out[key]["pool_performance"] = [int(row[0]), int(row[1])]
    except sqlite3.Error:
        out[key]["pool_performance"] = [0, 0]
    # loan_performance — MAX(rowid) only; COUNT is too slow on 100M rows.
    try:
        row = c.execute("SELECT COALESCE(MAX(rowid), 0) FROM loan_performance").fetchone()
        out[key]["loan_performance"] = [-1, int(row[0])]
    except sqlite3.Error:
        out[key]["loan_performance"] = [-1, 0]
    c.close()
print(json.dumps(out))
PYEOF
}

# 1. Pull new filings from EDGAR (for Carvana) + CarMax cron (if any)
$PY run_ingestion.py >> "$LOG" 2>&1

# CarMax ingestion lives in its own module; run it too so the count diff covers both.
if [ -f /opt/abs-dashboard/carmax_abs/run_ingestion.py ]; then
    (cd /opt/abs-dashboard/carmax_abs && $PY run_ingestion.py >> "$LOG" 2>&1) || true
fi

# 1b. Compute post-ingest snapshot and compare to prior cycle.
POST_INGEST_FILE=$(mktemp)
snapshot_counts > "$POST_INGEST_FILE"
echo "$(date -u): post-ingest snapshot: $(cat "$POST_INGEST_FILE")" >> "$LOG"

NEW_DATA=0
if [ -f "$STATE_FILE" ]; then
    NEW_DATA=$($PY - "$STATE_FILE" "$POST_INGEST_FILE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f: prior = json.load(f)
with open(sys.argv[2]) as f: now = json.load(f)
changed = False
for db, tables in now.items():
    pdb = prior.get(db, {})
    for tbl, pair in tables.items():
        cnt, mx = pair
        pc, pm = pdb.get(tbl, [0, 0])
        # count == -1 means "not measured" (loan_performance); skip count check.
        if cnt != -1 and pc != -1 and cnt > pc:
            changed = True; break
        if mx > pm:
            changed = True; break
    if changed:
        break
print(1 if changed else 0)
PYEOF
)
else
    # First run: no prior state. Treat as no-new-data to avoid a spurious
    # 2-hour Markov run on initial deployment of this logic.
    echo "$(date -u): no prior state file, treating as NEW_DATA=0" >> "$LOG"
fi
echo "$(date -u): NEW_DATA=$NEW_DATA" >> "$LOG"

# 2. Rebuild pool-level summaries (re-parses servicer certs into pool_performance)
$PY rebuild_summaries.py >> "$LOG" 2>&1

# 3. Export the lean dashboard DB used by generate_dashboard
$PY export_dashboard_db.py >> "$LOG" 2>&1

# 4. Refresh default-model outputs
$PY default_model.py >> "$LOG" 2>&1

# 4b. Data-triggered Markov re-run.
# Peak RSS ~3.3 GB on an 8 GB droplet. Cron runs at 14:17 UTC; dashboard
# regen still finishes on stale deal_forecasts if Markov hangs. Wrapped in
# `timeout 4h` so a stuck run can't block subsequent cron cycles.
if [ "$NEW_DATA" = "1" ]; then
    if [ "${ABS_CRON_DRY_RUN:-0}" = "1" ]; then
        echo "$(date -u): [DRY RUN] new filings detected — would re-run Markov now" >> "$LOG"
    else
        echo "$(date -u): new filings detected — re-running Markov (timeout 4h)..." >> "$LOG"
        timeout 4h $PY /opt/abs-dashboard/unified_markov.py >> "$LOG" 2>&1 || \
            echo "$(date -u): WARN: unified_markov.py failed or timed out (exit=$?); continuing with stale deal_forecasts" >> "$LOG"
        echo "$(date -u): Markov step finished" >> "$LOG"
    fi
else
    echo "$(date -u): no new data — skipping Markov re-run" >> "$LOG"
fi

# 5. Regenerate the static dashboard into preview/
$PY generate_preview.py >> "$LOG" 2>&1

# 6. Promote preview → live (this project auto-promotes)
$PY generate_preview.py promote >> "$LOG" 2>&1

# 6b. Display-layer sanity-range audit. Scans the rendered HTML tree under
# static_site/live/ and validates every numeric cell against DISPLAY_RANGES
# + aggregate sanity + cross-column chain checks. If HALT findings surface
# the data is already live (we don't roll back) — we emit a notify.sh push
# and append to AUDIT_FINDINGS.md so a human can triage. See LESSONS.md
# entry for 2026-04-18 for the "why".
AUDIT_OUT=$(mktemp)
if $PY /opt/abs-dashboard/audit_display_ranges.py --live > "$AUDIT_OUT" 2>&1; then
    echo "$(date -u): display-range audit PASS" >> "$LOG"
    tail -20 "$AUDIT_OUT" >> "$LOG"
else
    echo "$(date -u): display-range audit FAIL — see AUDIT_FINDINGS.md" >> "$LOG"
    cat "$AUDIT_OUT" >> "$LOG"
    {
        echo ""
        echo "## $(date -u +%Y-%m-%d) — display-range audit HALT after promote"
        echo ""
        echo "Audit script: /opt/abs-dashboard/audit_display_ranges.py"
        echo "Live tree audited after cron_ingest promote."
        echo ""
        echo '```'
        cat "$AUDIT_OUT"
        echo '```'
    } >> /opt/abs-dashboard/AUDIT_FINDINGS.md || true
    if command -v notify.sh >/dev/null 2>&1; then
        notify.sh "abs-dashboard: display-range audit HALT" \
                  "See /opt/abs-dashboard/AUDIT_FINDINGS.md; promote already happened." \
                  --priority high 2>> "$LOG" || true
    fi
fi
rm -f "$AUDIT_OUT"

# 7. Final-state snapshot for next cycle's comparison. We write at the END so
# the next run compares against the actual final state of this run (including
# any rows added by rebuild_summaries).
snapshot_counts > "$STATE_FILE"
echo "$(date -u): wrote final snapshot to $STATE_FILE" >> "$LOG"
rm -f "$POST_INGEST_FILE"

echo "===== $(date -u) done =====" >> "$LOG"
