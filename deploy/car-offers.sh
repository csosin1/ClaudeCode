#!/bin/bash
# Deploy script for car-offers (Express on port 3100)
# OWNED BY: car-offers chat. This file can be modified by the project chat directly.
# The main deploy script (auto_deploy_general.sh) sources this file.
#
# Available variables from parent: $REPO_DIR, $LOG, $NODE_BIN, $NPM_BIN, $NPX_BIN

PROJECT="car-offers"
PROJECT_DIR="/opt/$PROJECT"
LOG_DIR="/var/log/$PROJECT"

if [ ! -d "$REPO_DIR/$PROJECT" ]; then
    return 0 2>/dev/null || exit 0
fi

mkdir -p "$PROJECT_DIR/data"
mkdir -p "$LOG_DIR"

# .env (one-time — user fills in password via /car-offers/setup)
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'ENVEOF'
PROXY_HOST=gate.decodo.com
PROXY_PORT=10001
PROXY_USER=spjax0kgms
PROXY_PASS=
PROJECT_EMAIL=
PORT=3100
ENVEOF
fi

# Note: code hardcodes port 7000 for geo-targeting (user- prefix params).
# .env PROXY_PORT is not used for the actual proxy connection.

# Sync code (preserve node_modules, .env, data)
rsync -a --delete \
    --exclude='node_modules' \
    --exclude='*.db' \
    --exclude='.env' \
    "$REPO_DIR/$PROJECT/" "$PROJECT_DIR/"

# npm install (if package.json changed or node_modules missing)
if [ "$REPO_DIR/$PROJECT/package.json" -nt "$PROJECT_DIR/node_modules/.package-lock.json" ] || [ ! -d "$PROJECT_DIR/node_modules/express" ]; then
    echo "$(date): npm install for $PROJECT..." >> "$LOG"
    cd "$PROJECT_DIR" && "$NPM_BIN" install --production >> "$LOG" 2>&1
    if [ -d "$PROJECT_DIR/node_modules/express" ]; then
        echo "$(date): npm install done." >> "$LOG"
    else
        echo "$(date): ERROR — npm install failed (express missing)." >> "$LOG"
    fi
fi

# Playwright (one-time, only if not already installed)
if [ ! -f "$PROJECT_DIR/.playwright_installed" ]; then
    echo "$(date): Installing Playwright + Chromium..." >> "$LOG"
    cd "$PROJECT_DIR" && "$NPX_BIN" playwright install --with-deps chromium >> "$LOG" 2>&1
    if "$NPX_BIN" playwright --version > /dev/null 2>&1; then
        touch "$PROJECT_DIR/.playwright_installed"
        echo "$(date): Playwright installed." >> "$LOG"
    else
        echo "$(date): WARNING — Playwright install may have failed." >> "$LOG"
    fi
fi

# Xvfb for headed browser mode (one-time, non-fatal)
# Headed mode bypasses Cloudflare's headless browser detection
if ! command -v Xvfb >/dev/null 2>&1; then
    echo "$(date): Installing Xvfb..." >> "$LOG"
    apt-get install -y xvfb >> "$LOG" 2>&1 || echo "$(date): Xvfb install failed (non-fatal)" >> "$LOG"
fi

# Start Xvfb if available (non-fatal)
if command -v Xvfb >/dev/null 2>&1 && ! pgrep -x Xvfb >/dev/null 2>&1; then
    nohup Xvfb :99 -screen 0 1920x1080x24 >/dev/null 2>&1 &
    sleep 1
    echo "$(date): Xvfb started on :99" >> "$LOG"
fi

# Build DISPLAY env line for systemd (empty string if no Xvfb)
DISPLAY_LINE=""
if command -v Xvfb >/dev/null 2>&1; then
    DISPLAY_LINE="Environment=DISPLAY=:99"
fi

# systemd service
cat > /etc/systemd/system/$PROJECT.service <<EOF
[Unit]
Description=Car Offer Tool (Express on port 3100)
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$NODE_BIN server.js
Restart=always
RestartSec=5
Environment=NODE_ENV=production
$DISPLAY_LINE
StandardOutput=append:$LOG_DIR/error.log
StandardError=append:$LOG_DIR/error.log

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable $PROJECT >> "$LOG" 2>&1

# Only start service if deps are ready (prevents 502 on first deploy)
if [ -d "$PROJECT_DIR/node_modules/express" ]; then
    systemctl restart $PROJECT >> "$LOG" 2>&1
    echo "$(date): $PROJECT service restarted." >> "$LOG"

    # Post-restart: wait for service, dump status for diagnostics
    (
        sleep 15
        echo "$(date): [post-restart] Checking service health..." >> "$LOG"
        STATUS=$(curl -sf --max-time 5 http://127.0.0.1:3100/api/status 2>&1) || STATUS="curl failed"
        echo "$(date): [post-restart] /api/status: $STATUS" >> "$LOG"

        # Wait for auto-run Carvana to complete (up to 5 min)
        for i in 1 2 3 4 5 6 7 8 9 10; do
            sleep 30
            RESULTS=$(curl -sf --max-time 5 http://127.0.0.1:3100/api/startup-results 2>&1) || RESULTS="curl failed"
            if echo "$RESULTS" | grep -q '"lastCarvanaRun"' && ! echo "$RESULTS" | grep -q '"lastCarvanaRun":null'; then
                echo "$(date): [post-restart] Carvana run completed (attempt $i):" >> "$LOG"
                echo "$RESULTS" >> "$LOG"
                break
            fi
            echo "$(date): [post-restart] Waiting for Carvana auto-run... ($((i*30))s)" >> "$LOG"
        done
    ) &
else
    echo "$(date): $PROJECT deps not ready — skipping service start." >> "$LOG"
fi

# Observability (one-time)
if [ ! -f /opt/.car_offers_logs_initialized ]; then
    touch "$LOG_DIR/error.log" "$LOG_DIR/uptime.log"
    cat > /etc/logrotate.d/$PROJECT << 'LREOF'
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

echo "$(date): $PROJECT deploy block done." >> "$LOG"
