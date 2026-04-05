#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Runs every 30s via systemd timer. Handles games, landing page, and nginx config.
# Each project with a build step (e.g. Carvana) has its OWN separate auto-deploy.

REPO_DIR="/opt/site-deploy"
LOG="/var/log/general-deploy.log"

cd "$REPO_DIR" || exit 1

# Prevent concurrent deploys (webhook + timer race condition)
exec 200>/tmp/deploy.lock
flock -n 200 || { echo "$(date): Deploy already running, skipping." >> "$LOG"; exit 0; }

# One-time observability setup (runs once, then skips)
if [ ! -f /opt/.observability_initialized ]; then
    echo "$(date): Initializing observability..."
    for proj in landing games carvana; do
        mkdir -p "/var/log/$proj"
        touch "/var/log/$proj/error.log" "/var/log/$proj/uptime.log"
        # Logrotate config
        cat > "/etc/logrotate.d/$proj" << LREOF
/var/log/$proj/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF
    done
    # Uptime cron jobs (every 5 min)
    (crontab -l 2>/dev/null; echo '*/5 * * * * curl -sf http://159.223.127.125/ > /dev/null || echo "$(date) DOWN" >> /var/log/landing/uptime.log') | crontab -
    (crontab -l 2>/dev/null; echo '*/5 * * * * curl -sf http://159.223.127.125/games/ > /dev/null || echo "$(date) DOWN" >> /var/log/games/uptime.log') | crontab -
    (crontab -l 2>/dev/null; echo '*/5 * * * * curl -sf http://159.223.127.125/CarvanaLoanDashBoard/ > /dev/null || echo "$(date) DOWN" >> /var/log/carvana/uptime.log') | crontab -
    touch /opt/.observability_initialized
    echo "$(date): Observability initialized — logs, crons, logrotate configured."
fi

# One-time webhook deploy listener setup
if [ ! -f /opt/.webhook_initialized ]; then
    echo "$(date): Installing webhook deploy listener..."

    # Copy listener script
    cp "$REPO_DIR/deploy/webhook_deploy.py" /opt/webhook_deploy.py
    chmod +x /opt/webhook_deploy.py

    # Webhook secret should already exist from initial deploy.
    # If missing (fresh setup), generate a new one — then configure GitHub webhook manually.
    if [ ! -f /opt/.webhook_secret ]; then
        python3 -c "import secrets; print(secrets.token_hex(32))" > /opt/.webhook_secret
        chmod 600 /opt/.webhook_secret
        echo "$(date): NEW webhook secret generated. Configure GitHub webhook with: $(cat /opt/.webhook_secret)"
    fi

    # Create systemd service
    cat > /etc/systemd/system/webhook-deploy.service << 'SVCEOF'
[Unit]
Description=GitHub webhook deploy listener
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/webhook_deploy.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/webhook-deploy.log
StandardError=append:/var/log/webhook-deploy.log

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable webhook-deploy.service
    systemctl start webhook-deploy.service

    # Logrotate for webhook log
    cat > /etc/logrotate.d/webhook-deploy << 'LREOF'
/var/log/webhook-deploy.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF

    touch /opt/.webhook_initialized
    echo "$(date): Webhook deploy listener installed and started on 127.0.0.1:9000"
fi

# Slow timer from 30s to 5min once webhook is handling instant deploys
if [ ! -f /opt/.timer_slowed ] && [ -f /opt/.webhook_initialized ]; then
    cat > /etc/systemd/system/general-deploy.timer << 'TMREOF'
[Unit]
Description=Check main branch for updates every 5 minutes (fallback for webhook)

[Timer]
OnBootSec=1min
OnUnitActiveSec=300s
Persistent=true

[Install]
WantedBy=timers.target
TMREOF
    systemctl daemon-reload
    systemctl restart general-deploy.timer
    touch /opt/.timer_slowed
    echo "$(date): Timer slowed to 5-minute fallback (webhook handles instant deploys)."
fi

# Fetch latest from main
git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

# Update nginx config if version changed (check every cycle)
if [ -f "$REPO_DIR/deploy/NGINX_VERSION" ]; then
    NEED=$(cat "$REPO_DIR/deploy/NGINX_VERSION")
    HAVE=$(cat /opt/.nginx_version 2>/dev/null || echo "none")
    if [ "$NEED" != "$HAVE" ]; then
        echo "$(date): Updating nginx config (v$NEED)..."
        # Copy landing page first (update_nginx.sh references it)
        mkdir -p /var/www/landing
        cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true
        bash "$REPO_DIR/deploy/update_nginx.sh" >> "$LOG" 2>&1 || true
        echo "$NEED" > /opt/.nginx_version
    fi
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): Main branch updated, syncing static files..."
    git reset --hard origin/main

    # Sync landing page
    mkdir -p /var/www/landing
    cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true

    # Sync games — copy entire games/ directory tree to /var/www/games/
    if [ -d "$REPO_DIR/games" ]; then
        mkdir -p /var/www/games
        rsync -a --delete "$REPO_DIR/games/" /var/www/games/
        echo "$(date): Games synced to /var/www/games/"
    fi

    # Update the running copy of this script and webhook listener
    cp "$REPO_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh 2>/dev/null || true
    cp "$REPO_DIR/deploy/webhook_deploy.py" /opt/webhook_deploy.py 2>/dev/null && systemctl restart webhook-deploy.service 2>/dev/null || true

    echo "$(date): General deploy complete."
else
    echo "$(date): No changes on main."
fi
