#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Webhook triggers instant deploy; 5-min timer as fallback.
#
# RULE 1: Update THIS SCRIPT first after git reset — breaks deadlock if old version is stuck.
# RULE 2: Static file sync next (2-3s). Heavy setup (npm, apt-get) runs last and never blocks.

REPO_DIR="/opt/site-deploy"
LOG="/var/log/general-deploy.log"

cd "$REPO_DIR" || exit 1

# Fetch latest from main
git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New code on main, deploying..." >> "$LOG"
    git reset --hard origin/main

    # === STEP 0: UPDATE THIS SCRIPT FIRST (breaks deadlock) ===
    cp "$REPO_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh 2>/dev/null || true

    # === STEP 1: NGINX CONFIG (if version changed) ===
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

    # === STEP 2: FAST STATIC SYNC (must complete in seconds) ===

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

    # === STEP 3: CAR-OFFERS (Express server via systemd) ===

    if [ -d "$REPO_DIR/car-offers" ]; then
        mkdir -p /opt/car-offers/data

        # .env (one-time, pre-filled with Decodo proxy — user adds password via web UI)
        if [ ! -f /opt/car-offers/.env ]; then
            cat > /opt/car-offers/.env << 'ENVEOF'
PROXY_HOST=gate.decodo.com
PROXY_PORT=7000
PROXY_USER=spjax0kgms
PROXY_PASS=
PROJECT_EMAIL=
PORT=3100
ENVEOF
        fi

        # Sync code (preserve node_modules, .env, *.db)
        rsync -a --delete \
            --exclude='node_modules' \
            --exclude='*.db' \
            --exclude='.env' \
            "$REPO_DIR/car-offers/" /opt/car-offers/

        # npm install (express + dotenv = seconds)
        if [ ! -f /opt/car-offers/.npm_installed ] || [ "$REPO_DIR/car-offers/package.json" -nt /opt/car-offers/.npm_installed ]; then
            echo "$(date): npm install for car-offers..." >> "$LOG"
            cd /opt/car-offers && npm install --production >> "$LOG" 2>&1
            touch /opt/car-offers/.npm_installed
            echo "$(date): npm install done." >> "$LOG"
        fi

        # Playwright + system deps — background (heavy, don't block server)
        if [ ! -f /opt/car-offers/.playwright_installed ]; then
            echo "$(date): Playwright installing in background..." >> "$LOG"
            (
                apt-get update -qq >> "$LOG" 2>&1
                apt-get install -y -qq \
                    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
                    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
                    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 >> "$LOG" 2>&1
                cd /opt/car-offers && npx playwright install chromium --with-deps >> "$LOG" 2>&1
                touch /opt/car-offers/.playwright_installed
                echo "$(date): Playwright install done." >> "$LOG"
            ) &
        fi

        # systemd service (no PM2)
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
StandardOutput=append:/var/log/car-offers/error.log
StandardError=append:/var/log/car-offers/error.log

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable car-offers >> "$LOG" 2>&1
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

    # === STEP 4: DIAGNOSTICS (write server state to static file for QA) ===
    mkdir -p /var/www/landing
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"node_version\": \"$(node --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"node_path\": \"$(which node 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"npm_version\": \"$(npm --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"car_offers_dir_exists\": $([ -d /opt/car-offers ] && echo true || echo false),"
        echo "  \"server_js_exists\": $([ -f /opt/car-offers/server.js ] && echo true || echo false),"
        echo "  \"node_modules_exists\": $([ -d /opt/car-offers/node_modules ] && echo true || echo false),"
        echo "  \"express_installed\": $([ -d /opt/car-offers/node_modules/express ] && echo true || echo false),"
        echo "  \"dotenv_installed\": $([ -d /opt/car-offers/node_modules/dotenv ] && echo true || echo false),"
        echo "  \"env_file_exists\": $([ -f /opt/car-offers/.env ] && echo true || echo false),"
        echo "  \"npm_installed_flag\": $([ -f /opt/car-offers/.npm_installed ] && echo true || echo false),"
        echo "  \"playwright_installed_flag\": $([ -f /opt/car-offers/.playwright_installed ] && echo true || echo false),"
        echo "  \"systemd_service_exists\": $([ -f /etc/systemd/system/car-offers.service ] && echo true || echo false),"
        echo "  \"systemd_status\": \"$(systemctl is-active car-offers 2>&1)\","
        echo "  \"systemd_enabled\": \"$(systemctl is-enabled car-offers 2>&1)\","
        echo "  \"port_3100_listening\": $(ss -tlnp | grep -q ':3100' && echo true || echo false),"
        echo "  \"car_offers_log_tail\": $(tail -20 /var/log/car-offers/error.log 2>/dev/null | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '\"no log\"'),"
        echo "  \"deploy_log_tail\": $(tail -20 /var/log/general-deploy.log 2>/dev/null | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '\"no log\"'),"
        echo "  \"package_json_contents\": $(cat /opt/car-offers/package.json 2>/dev/null | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '\"not found\"')"
        echo "}"
    } > /var/www/landing/debug.json

    echo "$(date): Deploy complete." >> "$LOG"
else
    : # No changes — silent
fi
