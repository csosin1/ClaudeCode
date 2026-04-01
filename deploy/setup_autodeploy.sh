#!/bin/bash
# One-time setup: creates a systemd timer that runs auto_deploy.sh every 5 minutes.
# Run this ONCE on the droplet. After that, every git push auto-deploys.

set -e

# Copy the deploy script
cp /opt/abs-dashboard/deploy/auto_deploy.sh /opt/auto_deploy.sh
chmod +x /opt/auto_deploy.sh

# Create systemd service
cat > /etc/systemd/system/auto-deploy.service << 'EOF'
[Unit]
Description=Auto-deploy ABS Dashboard from GitHub

[Service]
Type=oneshot
ExecStart=/opt/auto_deploy.sh
StandardOutput=append:/var/log/auto-deploy.log
StandardError=append:/var/log/auto-deploy.log
EOF

# Create systemd timer (every 5 minutes)
cat > /etc/systemd/system/auto-deploy.timer << 'EOF'
[Unit]
Description=Check GitHub for updates every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable auto-deploy.timer
systemctl start auto-deploy.timer

echo "============================================================"
echo "  Auto-deploy is set up!"
echo "============================================================"
echo ""
echo "  Every 5 minutes, the server checks GitHub for new code."
echo "  If changes are found, it auto-pulls and restarts the dashboard."
echo "  You never need to touch this server again."
echo ""
echo "  Logs: /var/log/auto-deploy.log"
echo "  Status: systemctl status auto-deploy.timer"
echo "============================================================"
