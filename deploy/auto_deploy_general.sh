#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Webhook triggers instant deploy; 5-min timer as fallback.
#
# RULE 1: Update THIS SCRIPT first after git reset — breaks deadlock if old version is stuck.
# RULE 2: Static file sync next (2-3s). Heavy setup (npm, apt-get) runs last and never blocks.

REPO_DIR="/opt/site-deploy"
LOG="/var/log/general-deploy.log"

# Find Node.js — may be installed via nvm, nodesource, or snap
NODE_BIN=""
for candidate in /usr/local/bin/node /usr/bin/node /snap/bin/node "$HOME/.nvm/versions/node/*/bin/node"; do
    if [ -x "$candidate" ]; then
        NODE_BIN="$candidate"
        break
    fi
done
if [ -z "$NODE_BIN" ]; then
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" 2>/dev/null
    NODE_BIN="$(command -v node 2>/dev/null || true)"
fi
if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN" ]; then
    echo "$(date): Node.js not found, installing via nodesource..." >> "$LOG"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >> "$LOG" 2>&1
    apt-get install -y nodejs >> "$LOG" 2>&1
    NODE_BIN="$(command -v node 2>/dev/null || echo /usr/bin/node)"
fi

NPM_BIN="$(dirname "$NODE_BIN")/npm"
NPX_BIN="$(dirname "$NODE_BIN")/npx"
export PATH="$(dirname "$NODE_BIN"):$PATH"

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

    # === STEP 3: SERVER-SIDE PROJECTS ===

    # --- car-offers (Express on port 3100) ---
    if [ -d "$REPO_DIR/car-offers" ]; then
        mkdir -p /opt/car-offers/data
        mkdir -p /var/log/car-offers

        # .env (one-time — user fills in password via /car-offers/setup)
        if [ ! -f /opt/car-offers/.env ]; then
            cat > /opt/car-offers/.env << 'ENVEOF'
PROXY_HOST=gate.decodo.com
PROXY_PORT=10001
PROXY_USER=spjax0kgms
PROXY_PASS=
PROJECT_EMAIL=
PORT=3100
ENVEOF
        fi

        # One-time: fix proxy port from 7000 to 10001
        if [ ! -f /opt/.car_offers_port_fixed ]; then
            if [ -f /opt/car-offers/.env ]; then
                sed -i 's/^PROXY_PORT=7000$/PROXY_PORT=10001/' /opt/car-offers/.env
                touch /opt/.car_offers_port_fixed
                echo "$(date): Fixed proxy port to 10001." >> "$LOG"
            fi
        fi

        # Sync code (preserve node_modules, .env, data)
        rsync -a --delete \
            --exclude='node_modules' \
            --exclude='*.db' \
            --exclude='.env' \
            "$REPO_DIR/car-offers/" /opt/car-offers/

        # npm install (only if needed, validate result)
        if [ ! -d /opt/car-offers/node_modules/express ]; then
            echo "$(date): npm install for car-offers..." >> "$LOG"
            cd /opt/car-offers && "$NPM_BIN" install --production >> "$LOG" 2>&1
            if [ -d /opt/car-offers/node_modules/express ]; then
                echo "$(date): npm install done." >> "$LOG"
            else
                echo "$(date): ERROR — npm install failed (express missing)." >> "$LOG"
            fi
        fi

        # Playwright (one-time, only if not already installed)
        if [ ! -f /opt/car-offers/.playwright_installed ]; then
            echo "$(date): Installing Playwright + Chromium..." >> "$LOG"
            cd /opt/car-offers && "$NPX_BIN" playwright install --with-deps chromium >> "$LOG" 2>&1
            if "$NPX_BIN" playwright --version > /dev/null 2>&1; then
                touch /opt/car-offers/.playwright_installed
                echo "$(date): Playwright installed." >> "$LOG"
            else
                echo "$(date): WARNING — Playwright install may have failed." >> "$LOG"
            fi
        fi

        # systemd service
        cat > /etc/systemd/system/car-offers.service << SVCEOF
[Unit]
Description=Car Offer Tool (Express on port 3100)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/car-offers
ExecStart=$NODE_BIN server.js
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
            (crontab -l 2>/dev/null; echo '*/5 * * * * curl -sf http://127.0.0.1:3100/ > /dev/null || echo "$(date) DOWN" >> /var/log/car-offers/uptime.log') | crontab -
            touch /opt/.car_offers_logs_initialized
        fi
    fi

    # === STEP 4: LIGHTWEIGHT DIAGNOSTICS ===
    # Minimal health check — just enough for QA to verify server state
    mkdir -p /var/www/landing
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"node_version\": \"$("$NODE_BIN" --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"car_offers_status\": \"$(systemctl is-active car-offers 2>&1)\","
        echo "  \"port_3100\": $(ss -tlnp | grep -q ':3100' && echo true || echo false)"
        echo "}"
    } > /var/www/landing/debug.json

    # === STEP 5: AUTO-TEST (proxy + carvana, one-shot, background) ===
    rm -f /opt/.car_offers_autotest_done  # retry after port fix
    if [ ! -f /opt/.car_offers_autotest_v2 ]; then
        (
            # Wait for service to be ready
            sleep 15
            for i in 1 2 3 4 5; do
                curl -sf http://127.0.0.1:3100/ > /dev/null 2>&1 && break
                sleep 5
            done

            echo "$(date): Auto-test: testing proxy..." >> "$LOG"
            PROXY_RESULT=$(curl -sf http://127.0.0.1:3100/api/test-proxy --max-time 30 2>&1)
            echo "$PROXY_RESULT" > /var/www/landing/proxy-test.json
            echo "$(date): Proxy test result: $PROXY_RESULT" >> "$LOG"

            # Only run Carvana if proxy works
            if echo "$PROXY_RESULT" | grep -q '"ok":true'; then
                echo "$(date): Auto-test: proxy OK, running Carvana test..." >> "$LOG"
                CARVANA_RESULT=$(curl -sf -X POST http://127.0.0.1:3100/api/carvana \
                    -H 'Content-Type: application/json' \
                    -d '{"vin":"1HGCV2F9XNA008352","mileage":"48000","zip":"06880"}' \
                    --max-time 200 2>&1)
                echo "$CARVANA_RESULT" > /var/www/landing/carvana-result.json
                echo "$(date): Carvana test result: $CARVANA_RESULT" >> "$LOG"
            else
                echo "$(date): Auto-test: proxy FAILED, skipping Carvana." >> "$LOG"
                echo "$PROXY_RESULT" > /var/www/landing/carvana-result.json
            fi
            touch /opt/.car_offers_autotest_v2
        ) &
    fi

    echo "$(date): Deploy complete." >> "$LOG"
else
    : # No changes — silent
fi
