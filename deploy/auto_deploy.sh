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
    systemctl restart streamlit
    echo "$(date): Deploy complete."
else
    echo "$(date): No changes."
fi
