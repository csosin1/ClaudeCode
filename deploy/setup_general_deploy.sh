#!/bin/bash
# One-time setup: installs the general auto-deploy timer for main branch.
# This handles games, landing page, and any static files pushed to main.
# Bootstrapped by Carvana's auto-deploy, then runs independently.
set -e

REPO_URL="https://github.com/csosin1/ClaudeCode.git"
DEPLOY_DIR="/opt/site-deploy"

echo "Setting up general auto-deploy for main branch..."

# Clone repo to separate directory (isolated from Carvana's /opt/abs-dashboard)
if [ ! -d "$DEPLOY_DIR" ]; then
    git clone --branch main "$REPO_URL" "$DEPLOY_DIR"
else
    cd "$DEPLOY_DIR"
    git fetch origin main
    git reset --hard origin/main
fi

# Copy the deploy script
cp "$DEPLOY_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh
chmod +x /opt/auto_deploy_general.sh

# Create systemd service
cat > /etc/systemd/system/general-deploy.service << 'EOF'
[Unit]
Description=General auto-deploy from main branch
[Service]
Type=oneshot
ExecStart=/opt/auto_deploy_general.sh
StandardOutput=append:/var/log/general-deploy.log
StandardError=append:/var/log/general-deploy.log
EOF

# Create systemd timer (5-minute fallback — webhook handles instant deploys)
cat > /etc/systemd/system/general-deploy.timer << 'EOF'
[Unit]
Description=Check main branch for updates every 5 minutes (fallback for webhook)
[Timer]
OnBootSec=1min
OnUnitActiveSec=300s
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable general-deploy.timer
systemctl start general-deploy.timer

# Run first deploy immediately
/opt/auto_deploy_general.sh

echo "General auto-deploy installed and running."
echo "  Timer: general-deploy.timer (every 5min, webhook handles instant)"
echo "  Log:   /var/log/general-deploy.log"
echo "  Repo:  $DEPLOY_DIR (main branch)"
