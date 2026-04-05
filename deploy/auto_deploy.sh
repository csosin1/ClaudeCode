#!/bin/bash
# Auto-deploy: checks GitHub every 30s, deploys if there are changes.
cd /opt/abs-dashboard

# Fetch latest from GitHub
git fetch origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/claude/carvana-loan-dashboard-4QMPM)

# Bootstrap general auto-deploy (one-time: installs timer for main branch)
if [ -f /opt/abs-dashboard/deploy/setup_general_deploy.sh ] && [ ! -f /opt/.general_deploy_setup ]; then
    echo "$(date): Installing general auto-deploy for main branch..."
    bash /opt/abs-dashboard/deploy/setup_general_deploy.sh >> /var/log/auto-deploy.log 2>&1 || true
    touch /opt/.general_deploy_setup
fi

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

    # Install any new dependencies
    /opt/abs-venv/bin/pip install -q -r /opt/abs-dashboard/carvana_abs/requirements.txt >> /var/log/auto-deploy.log 2>&1 || true

    # Always export dashboard DB, run model, and regenerate preview on code changes
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/export_dashboard_db.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/default_model.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py >> /var/log/auto-deploy.log 2>&1 || true

    # Run data validation and check the generated HTML
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/validate_data.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/validate_dashboard.py > /opt/abs-dashboard/deploy/LAST_VALIDATION.txt 2>&1
    cat /opt/abs-dashboard/deploy/LAST_VALIDATION.txt >> /var/log/auto-deploy.log
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/deploy_status.py >> /var/log/auto-deploy.log 2>&1 || true

    # Write status and push to GitHub so it can be read remotely
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/deploy_status.py > /opt/abs-dashboard/deploy/LAST_STATUS.json 2>&1 || true
    cd /opt/abs-dashboard
    git add deploy/LAST_STATUS.json deploy/LAST_VALIDATION.txt deploy/LAST_DATA_CHECK.txt 2>/dev/null
    git commit -m "Auto-deploy status update" --allow-empty 2>/dev/null || true
    # Pull-rebase before push to avoid non-fast-forward rejection
    git pull --rebase origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null || true
    git push origin claude/carvana-loan-dashboard-4QMPM 2>>/var/log/auto-deploy.log || echo "$(date): git push failed" >> /var/log/auto-deploy.log

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
