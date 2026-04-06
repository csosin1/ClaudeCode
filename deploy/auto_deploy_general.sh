#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Runs every 30s via systemd timer. Handles games, landing page, and nginx config.
# CRITICAL: Static file sync MUST run first and fast (2-3s). Heavy setup (npm, apt-get)
# runs AFTER static files are deployed so it never blocks the main deploy.

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
        echo "$(date): Updating nginx config (v$NEED)..."
        mkdir -p /var/www/landing
        cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true
        bash "$REPO_DIR/deploy/update_nginx.sh" >> "$LOG" 2>&1 || true
        echo "$NEED" > /opt/.nginx_version
    fi
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): Main branch updated, syncing static files..."
    git reset --hard origin/main

    # --- FAST STATIC SYNC (must complete in seconds) ---

    # Sync landing page
    mkdir -p /var/www/landing
    cp "$REPO_DIR/deploy/landing.html" /var/www/landing/index.html 2>/dev/null || true

    # Sync games
    if [ -d "$REPO_DIR/games" ]; then
        mkdir -p /var/www/games
        rsync -a --delete "$REPO_DIR/games/" /var/www/games/
        echo "$(date): Games synced to /var/www/games/"
    fi

    # Sync carvana hub page
    if [ -d "$REPO_DIR/carvana" ]; then
        mkdir -p /var/www/carvana
        rsync -a --delete "$REPO_DIR/carvana/" /var/www/carvana/
        echo "$(date): Carvana hub synced to /var/www/carvana/"
    fi

    echo "$(date): Static files deployed."

    # --- CAR-OFFERS PROJECT (heavier — runs after static sync) ---

    if [ -d "$REPO_DIR/car-offers" ]; then
        # One-time setup: system deps, PM2, .env, observability
        if [ ! -f /opt/.car_offers_initialized ]; then
            echo "$(date): First-time car-offers setup starting..." >> "$LOG"

            apt-get update -qq >> "$LOG" 2>&1
            apt-get install -y -qq build-essential \
                libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
                libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
                libpango-1.0-0 libcairo2 libasound2 libxshmfence1 >> "$LOG" 2>&1

            npm install -g pm2 >> "$LOG" 2>&1
            mkdir -p /opt/car-offers/data

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

            touch /opt/.car_offers_initialized
            echo "$(date): car-offers first-time setup complete." >> "$LOG"
        fi

        # Sync code (exclude node_modules, *.db, .env)
        mkdir -p /opt/car-offers
        rsync -a --delete \
            --exclude='node_modules' \
            --exclude='*.db' \
            --exclude='.env' \
            "$REPO_DIR/car-offers/" /opt/car-offers/

        # npm install if package.json changed
        if [ "$REPO_DIR/car-offers/package.json" -nt /opt/car-offers/.npm_installed ] || [ ! -f /opt/car-offers/.npm_installed ]; then
            echo "$(date): Running npm install for car-offers..." >> "$LOG"
            cd /opt/car-offers && npm install --production >> "$LOG" 2>&1
            echo "$(date): Running playwright install chromium..." >> "$LOG"
            npx playwright install chromium --with-deps >> "$LOG" 2>&1
            touch /opt/car-offers/.npm_installed
            echo "$(date): car-offers npm + Playwright install complete." >> "$LOG"
        fi

        # Start or restart with PM2
        echo "$(date): Starting car-offers with PM2..." >> "$LOG"
        if pm2 describe car-offers > /dev/null 2>&1; then
            pm2 restart car-offers >> "$LOG" 2>&1
        else
            cd /opt/car-offers && pm2 start server.js --name car-offers >> "$LOG" 2>&1
            pm2 save >> "$LOG" 2>&1
        fi
        echo "$(date): car-offers synced and running." >> "$LOG"
    fi

    # Update the running copy of this script
    cp "$REPO_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh 2>/dev/null || true

    echo "$(date): General deploy complete."
else
    echo "$(date): No changes on main."
fi
