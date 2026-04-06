#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Runs every 30s via systemd timer. Handles games, landing page, and nginx config.
# CRITICAL: Static file sync MUST run first and fast (2-3s). Heavy setup runs after.

REPO_DIR="/opt/site-deploy"
LOG="/var/log/general-deploy.log"

cd "$REPO_DIR" || exit 1

# Fetch latest from main
git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

# Update nginx config if version changed (check every cycle)
if [ -f "$REPO_DIR/deploy/NGINX_VERSION" ]; then
    NEED=$(cat "$REPO_DIR/deploy/NGINX_VERSION")
    HAVE=$(cat /opt/.nginx_version 2>/dev/null || echo "none")
    if [ "$NEED" != "$HAVE" ]; then
        echo "$(date): Updating nginx config (v$NEED)..." >> "$LOG"
        mkdir -p /var/www/landing
        cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true
        bash "$REPO_DIR/deploy/update_nginx.sh" >> "$LOG" 2>&1 || true
        echo "$NEED" > /opt/.nginx_version
    fi
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): Main branch updated, syncing..." >> "$LOG"
    git reset --hard origin/main

    # --- FAST STATIC SYNC (completes in seconds) ---

    mkdir -p /var/www/landing
    cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true

    if [ -d "$REPO_DIR/games" ]; then
        mkdir -p /var/www/games
        rsync -a --delete "$REPO_DIR/games/" /var/www/games/
    fi

    if [ -d "$REPO_DIR/carvana" ]; then
        mkdir -p /var/www/carvana
        rsync -a --delete "$REPO_DIR/carvana/" /var/www/carvana/
    fi

    echo "$(date): Static files deployed." >> "$LOG"

    # --- CAR-OFFERS (uses systemd, not PM2) ---

    if [ -d "$REPO_DIR/car-offers" ]; then
        mkdir -p /opt/car-offers/data

        # Create .env if it doesn't exist (pre-filled with Decodo proxy)
        if [ ! -f /opt/car-offers/.env ]; then
            cat > /opt/car-offers/.env << 'ENVEOF'
# Decodo/Smartproxy residential proxy
PROXY_HOST=gate.decodo.com
PROXY_PORT=7000
PROXY_USER=spjax0kgms
PROXY_PASS=

# Project email (leave blank to auto-generate disposable email)
PROJECT_EMAIL=

# Express server
PORT=3100
ENVEOF
        fi

        # Sync code (preserve node_modules, .env, *.db)
        rsync -a --delete \
            --exclude='node_modules' \
            --exclude='*.db' \
            --exclude='.env' \
            "$REPO_DIR/car-offers/" /opt/car-offers/

        # npm install if needed (express + dotenv are tiny — installs in seconds)
        if [ ! -f /opt/car-offers/.npm_installed ] || [ "$REPO_DIR/car-offers/package.json" -nt /opt/car-offers/.npm_installed ]; then
            echo "$(date): Running npm install for car-offers..." >> "$LOG"
            cd /opt/car-offers && npm install --production >> "$LOG" 2>&1
            touch /opt/car-offers/.npm_installed
            echo "$(date): npm install complete." >> "$LOG"
        fi

        # Install Playwright + system deps in background (heavy, don't block)
        if [ ! -f /opt/car-offers/.playwright_installed ]; then
            echo "$(date): Installing Playwright in background..." >> "$LOG"
            (
                apt-get update -qq >> "$LOG" 2>&1
                apt-get install -y -qq \
                    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
                    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
                    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 >> "$LOG" 2>&1
                cd /opt/car-offers && npx playwright install chromium --with-deps >> "$LOG" 2>&1
                touch /opt/car-offers/.playwright_installed
                echo "$(date): Playwright install complete." >> "$LOG"
            ) &
        fi

        # Create systemd service for car-offers (no PM2 needed)
        if [ ! -f /etc/systemd/system/car-offers.service ]; then
            cat > /etc/systemd/system/car-offers.service << 'SVCEOF'
[Unit]
Description=Car Offer Tool (Express on port 3100)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/car-offers
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
SVCEOF
            systemctl daemon-reload
            systemctl enable car-offers
        fi

        # Start or restart the service
        systemctl restart car-offers >> "$LOG" 2>&1
        echo "$(date): car-offers service restarted." >> "$LOG"

        # Observability (one-time)
        if [ ! -f /opt/.car_offers_logs_initialized ]; then
            mkdir -p /var/log/car-offers
            touch /var/log/car-offers/error.log /var/log/car-offers/uptime.log
            cat > /etc/logrotate.d/car-offers << 'LREOF'
/var/log/car-offers/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF
            (crontab -l 2>/dev/null; echo '*/5 * * * * curl -sf http://159.223.127.125/car-offers/ > /dev/null || echo "$(date) DOWN" >> /var/log/car-offers/uptime.log') | crontab -
            touch /opt/.car_offers_logs_initialized
        fi
    fi

    # Update the running copy of this script
    cp "$REPO_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh 2>/dev/null || true

    echo "$(date): General deploy complete." >> "$LOG"
else
    echo "$(date): No changes." >> "$LOG"
fi
