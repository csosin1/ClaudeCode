#!/bin/bash
# Auto-deploy: checks GitHub every 5 min, deploys if there are changes.
# Runs as a systemd timer — no manual intervention needed.
cd /opt/abs-dashboard

# Fetch latest from GitHub
git fetch origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/claude/carvana-loan-dashboard-4QMPM)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New changes detected, deploying..."
    git pull origin claude/carvana-loan-dashboard-4QMPM

    # Run any one-time deploy scripts
    if [ -f /opt/abs-dashboard/deploy/update_nginx.sh ]; then
        bash /opt/abs-dashboard/deploy/update_nginx.sh
    fi

    # Re-ingest pool data if reingest flag exists (one-time after parser fix)
    if [ -f /opt/abs-dashboard/carvana_abs/reingest_pool.py ] && [ ! -f /opt/.pool_reingested_v2 ]; then
        echo "$(date): Re-ingesting pool data with fixed parser..."
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/reingest_pool.py 2>&1 || true
        touch /opt/.pool_reingested_v2
    fi

    # Rebuild summary tables if schema changed
    if [ -f /opt/abs-dashboard/carvana_abs/rebuild_summaries.py ]; then
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/rebuild_summaries.py 2>&1 || true
    fi

    # Export small dashboard DB from the full DB
    if [ -f /opt/abs-dashboard/carvana_abs/export_dashboard_db.py ]; then
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/export_dashboard_db.py 2>&1 || true
    fi

    # Generate preview (not live) — user must approve to promote
    if [ -f /opt/abs-dashboard/carvana_abs/generate_preview.py ]; then
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py 2>&1 || true
    fi

    # Set up preview nginx if not done yet
    if [ -f /opt/abs-dashboard/deploy/setup_preview.sh ] && [ ! -f /opt/.preview_setup ]; then
        bash /opt/abs-dashboard/deploy/setup_preview.sh
        touch /opt/.preview_setup
    fi

    echo "$(date): Deploy complete. Preview updated."
else
    echo "$(date): No changes."
fi
