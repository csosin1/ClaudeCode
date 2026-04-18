#!/bin/bash
# Post-Markov pipeline for overnight ingest of 5 new deals.
# Runs AFTER unified_markov.py successfully writes deal_forecasts.
#
# Steps (all in /opt/abs-dashboard on prod):
#   1. Run compute_methodology.py  — rebuild analytics.json with the new-deal universe
#   2. export_dashboard_db (both issuers)  — refresh dashboard.db from main DBs
#   3. generate_preview.py  — rebuild static HTML
#   4. generate_preview.py promote  — promote preview -> live
#
# Exit non-zero on any step failure — run as:
#     ssh prod-private 'bash /opt/abs-dashboard/deploy/overnight_post_markov.sh \
#         > /var/log/abs-dashboard/post_markov.log 2>&1'
set -euo pipefail

cd /opt/abs-dashboard

LOG=/var/log/abs-dashboard/post_markov.log
PY=/opt/abs-venv/bin/python
export SEC_USER_AGENT="Clifford Sosin clifford.sosin@casinvestmentpartners.com"
export PYTHONPATH=/opt/abs-dashboard

echo "[$(date -u +%FT%TZ)] Starting post-Markov pipeline"

echo "[$(date -u +%FT%TZ)] Step 1/4: compute_methodology.py"
$PY carvana_abs/compute_methodology.py

echo "[$(date -u +%FT%TZ)] Step 2/4: export_dashboard_db for both issuers"
$PY -m carvana_abs.export_dashboard_db
$PY -m carmax_abs.export_dashboard_db

echo "[$(date -u +%FT%TZ)] Step 3/4: generate_preview.py"
$PY carvana_abs/generate_preview.py

echo "[$(date -u +%FT%TZ)] Step 4/4: generate_preview.py promote"
$PY carvana_abs/generate_preview.py promote

echo "[$(date -u +%FT%TZ)] Post-Markov pipeline COMPLETE"
