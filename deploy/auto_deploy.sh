#!/bin/bash
# Auto-deploy: checks GitHub every 30s, deploys if there are changes.
cd /opt/abs-dashboard

# Fetch latest from GitHub
git fetch origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/claude/carvana-loan-dashboard-4QMPM)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New changes detected, deploying..."
    git reset --hard origin/claude/carvana-loan-dashboard-4QMPM

    # Check if a reingest is needed (flag file in repo signals this)
    if [ -f /opt/abs-dashboard/deploy/REINGEST_VERSION ]; then
        NEED_VERSION=$(cat /opt/abs-dashboard/deploy/REINGEST_VERSION)
        HAVE_VERSION=$(cat /opt/.reingest_done 2>/dev/null || echo "none")
        if [ "$NEED_VERSION" != "$HAVE_VERSION" ]; then
            echo "$(date): Reingest needed (v$NEED_VERSION)..."
            /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/reingest_pool.py >> /var/log/auto-deploy.log 2>&1 || true
            /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/rebuild_summaries.py >> /var/log/auto-deploy.log 2>&1 || true
            echo "$NEED_VERSION" > /opt/.reingest_done
        fi
    fi

    # Always export dashboard DB and regenerate preview on code changes
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/export_dashboard_db.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py >> /var/log/auto-deploy.log 2>&1 || true

    # Validate the generated HTML and write status
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/validate_dashboard.py >> /var/log/auto-deploy.log 2>&1
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/deploy_status.py >> /var/log/auto-deploy.log 2>&1 || true

    # Set up status endpoint in nginx if not done
    if [ ! -f /opt/.status_nginx_done ]; then
        # Add status location to nginx config
        sed -i '/location \/games\//i\    location /status/ { alias /opt/abs-dashboard/carvana_abs/static_site/status/; add_header Access-Control-Allow-Origin "*"; }' /etc/nginx/sites-available/abs-dashboard 2>/dev/null
        nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null
        touch /opt/.status_nginx_done
    fi

    # Run any one-time setup scripts
    if [ -f /opt/abs-dashboard/deploy/setup_preview.sh ] && [ ! -f /opt/.preview_setup ]; then
        bash /opt/abs-dashboard/deploy/setup_preview.sh
        touch /opt/.preview_setup
    fi

    # Auto-promote if PROMOTE flag exists
    if [ -f /opt/abs-dashboard/deploy/PROMOTE ]; then
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py promote >> /var/log/auto-deploy.log 2>&1 || true
        echo "$(date): Promoted preview to live."
    fi

    # Update the running copy of this script
    cp /opt/abs-dashboard/deploy/auto_deploy.sh /opt/auto_deploy.sh 2>/dev/null || true

    echo "$(date): Deploy complete. Preview updated."
else
    echo "$(date): No changes."
fi
