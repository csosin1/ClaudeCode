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

        # npm install (if package.json changed or node_modules missing)
        if [ "$REPO_DIR/car-offers/package.json" -nt /opt/car-offers/node_modules/.package-lock.json ] || [ ! -d /opt/car-offers/node_modules/express ]; then
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

    # --- gym-intelligence (Flask on port 8502) ---
    if [ -d "$REPO_DIR/gym-intelligence" ]; then
        mkdir -p /opt/gym-intelligence
        mkdir -p /var/log/gym-intelligence

        # Sync code (preserve venv, .env, *.db)
        rsync -a --delete \
            --exclude='venv' \
            --exclude='*.db' \
            --exclude='.env' \
            --exclude='__pycache__' \
            "$REPO_DIR/gym-intelligence/" /opt/gym-intelligence/

        # .env (one-time — user fills in API key via /gym-intelligence/ Admin tab)
        if [ ! -f /opt/gym-intelligence/.env ]; then
            cat > /opt/gym-intelligence/.env << 'ENVEOF'
ANTHROPIC_API_KEY=
ENVEOF
        fi

        # Find python3
        PYTHON_BIN=""
        for candidate in /usr/bin/python3 /usr/local/bin/python3; do
            if [ -x "$candidate" ]; then
                PYTHON_BIN="$candidate"
                break
            fi
        done
        if [ -z "$PYTHON_BIN" ]; then
            PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
        fi
        if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
            echo "$(date): python3 not found, installing..." >> "$LOG"
            apt-get update >> "$LOG" 2>&1
            apt-get install -y python3 python3-venv python3-pip >> "$LOG" 2>&1
            PYTHON_BIN="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"
        fi

        # Create venv if missing
        if [ ! -d /opt/gym-intelligence/venv ]; then
            echo "$(date): Creating gym-intelligence venv..." >> "$LOG"
            if ! "$PYTHON_BIN" -m venv --help > /dev/null 2>&1; then
                apt-get install -y python3-venv >> "$LOG" 2>&1
            fi
            "$PYTHON_BIN" -m venv /opt/gym-intelligence/venv >> "$LOG" 2>&1
            /opt/gym-intelligence/venv/bin/pip install --upgrade pip >> "$LOG" 2>&1
        fi

        # Re-install deps if requirements.txt changed or flask missing
        if [ "$REPO_DIR/gym-intelligence/requirements.txt" -nt /opt/.gym-intelligence-deps ] || \
           ! /opt/gym-intelligence/venv/bin/python -c "import flask" 2>/dev/null; then
            echo "$(date): pip install for gym-intelligence..." >> "$LOG"
            /opt/gym-intelligence/venv/bin/pip install -r /opt/gym-intelligence/requirements.txt >> "$LOG" 2>&1
            if /opt/gym-intelligence/venv/bin/python -c "import flask" 2>/dev/null; then
                touch /opt/.gym-intelligence-deps
                echo "$(date): gym-intelligence pip install complete." >> "$LOG"
            else
                echo "$(date): ERROR — gym-intelligence pip install failed (flask missing)." >> "$LOG"
            fi
        fi

        # systemd service (always rewrite to pick up changes)
        cat > /etc/systemd/system/gym-intelligence.service << 'SVCEOF'
[Unit]
Description=Gym Intelligence (Flask on port 8502)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/gym-intelligence
ExecStart=/opt/gym-intelligence/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=HOME=/root
StandardOutput=append:/var/log/gym-intelligence/app.log
StandardError=append:/var/log/gym-intelligence/app.log

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable gym-intelligence >> "$LOG" 2>&1
        systemctl restart gym-intelligence >> "$LOG" 2>&1
        echo "$(date): gym-intelligence service restarted." >> "$LOG"

        # Observability (one-time)
        if [ ! -f /opt/.gym_intelligence_logs_initialized ]; then
            touch /var/log/gym-intelligence/app.log
            cat > /etc/logrotate.d/gym-intelligence << 'LREOF'
/var/log/gym-intelligence/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF
            touch /opt/.gym_intelligence_logs_initialized
        fi
        # One-time test: verify Overpass API works from droplet
        if [ ! -f /opt/.gym-intelligence-test-done ] && [ -f /opt/gym-intelligence/test_collect.py ]; then
            echo "$(date): Running gym-intelligence Overpass API test..." >> "$LOG"
            cd /opt/gym-intelligence
            /opt/gym-intelligence/venv/bin/python test_collect.py >> "$LOG" 2>&1
            # Copy results to web-accessible location
            if [ -f /opt/gym-intelligence/test_results.json ]; then
                cp /opt/gym-intelligence/test_results.json /var/www/landing/gym-test.json
                echo "$(date): Test results at /gym-test.json" >> "$LOG"
            fi
            touch /opt/.gym-intelligence-test-done
        fi
    fi

    # === STEP 4: LIGHTWEIGHT DIAGNOSTICS ===
    mkdir -p /var/www/landing
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"node_version\": \"$("$NODE_BIN" --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"car_offers_status\": \"$(systemctl is-active car-offers 2>&1)\","
        echo "  \"port_3100\": $(ss -tlnp | grep -q ':3100' && echo true || echo false),"
        echo "  \"gym_intelligence_status\": \"$(systemctl is-active gym-intelligence 2>&1)\","
        echo "  \"port_8502\": $(ss -tlnp | grep -q ':8502' && echo true || echo false)"
        echo "}"
    } > /var/www/landing/debug.json

    echo "$(date): Deploy complete." >> "$LOG"
else
    : # No changes — silent
fi

