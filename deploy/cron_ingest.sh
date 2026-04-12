#!/bin/bash
# Daily: pull latest SEC EDGAR filings, rebuild analysis, regenerate dashboard,
# and promote preview → live. Runs via cron.
set -u
LOG=/var/log/abs-ingestion.log
mkdir -p "$(dirname "$LOG")"
echo "===== $(date -u) start =====" >> "$LOG"

cd /opt/abs-dashboard
# Pull latest code first so any fixes/changes go live with today's data.
git pull --ff-only origin claude/carvana-loan-dashboard-4QMPM >> "$LOG" 2>&1 || true

cd /opt/abs-dashboard/carvana_abs
export SEC_USER_AGENT="Clifford Sosin clifford.sosin@casinvestmentpartners.com"
PY=/opt/abs-venv/bin/python

# 1. Pull new filings from EDGAR
$PY run_ingestion.py >> "$LOG" 2>&1

# 2. Rebuild pool-level summaries (re-parses servicer certs into pool_performance)
$PY rebuild_summaries.py >> "$LOG" 2>&1

# 3. Export the lean dashboard DB used by generate_dashboard
$PY export_dashboard_db.py >> "$LOG" 2>&1

# 4. Refresh default-model outputs
$PY default_model.py >> "$LOG" 2>&1

# 5. Regenerate the static dashboard into preview/
$PY generate_preview.py >> "$LOG" 2>&1

# 6. Promote preview → live (this project auto-promotes)
$PY generate_preview.py promote >> "$LOG" 2>&1

echo "===== $(date -u) done =====" >> "$LOG"
