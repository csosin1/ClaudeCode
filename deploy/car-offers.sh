#!/bin/bash
# Deploy script for car-offers — preview-first.
# Every push updates PREVIEW_DIR (port 3101). Live (port 3100) only changes via promote.sh.
#
# Available variables from parent: $REPO_DIR, $LOG, $NODE_BIN, $NPM_BIN, $NPX_BIN

PROJECT="car-offers"
LIVE_DIR="/opt/$PROJECT"
PREVIEW_DIR="/opt/$PROJECT-preview"
LOG_DIR="/var/log/$PROJECT"
LIVE_PORT=3100
PREVIEW_PORT=3101

if [ ! -d "$REPO_DIR/$PROJECT" ]; then
    return 0 2>/dev/null || exit 0
fi

# --- Pre-flight: verify nginx is serving ---
PRE_STATUS=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/ 2>/dev/null || echo "000")
if [ "$PRE_STATUS" != "200" ] && [ -f "$REPO_DIR/deploy/update_nginx.sh" ]; then
    echo "$(date): [car-offers] nginx returning $PRE_STATUS — rebuilding config..." >> "$LOG"
    bash "$REPO_DIR/deploy/update_nginx.sh" >> "$LOG" 2>&1 || true
fi

mkdir -p "$LIVE_DIR/data" "$PREVIEW_DIR/data" "$LOG_DIR"

# .env bootstraps (different PORT for each instance)
write_env() {
    local target="$1" port="$2"
    cat > "$target/.env" <<ENVEOF
PROXY_HOST=gate.decodo.com
PROXY_PORT=10001
PROXY_USER=spjax0kgms
PROXY_PASS=
PROJECT_EMAIL=
PORT=$port
ENVEOF
}
[ -f "$LIVE_DIR/.env" ]    || write_env "$LIVE_DIR"    "$LIVE_PORT"
[ -f "$PREVIEW_DIR/.env" ] || write_env "$PREVIEW_DIR" "$PREVIEW_PORT"

# --- Sync code to PREVIEW only (live is promoted separately) ---
rsync -a --delete \
    --exclude='node_modules' \
    --exclude='*.db' \
    --exclude='.env' \
    --exclude='startup-results.json' \
    --exclude='.patchright_installed' \
    --exclude='.playwright_installed' \
    --exclude='.chrome-profile' \
    --exclude='.proxy-session' \
    --exclude='.profile-warmup' \
    "$REPO_DIR/$PROJECT/" "$PREVIEW_DIR/"

# --- npm install in preview (if package.json changed or deps missing) ---
if [ "$REPO_DIR/$PROJECT/package.json" -nt "$PREVIEW_DIR/node_modules/.package-lock.json" ] || [ ! -d "$PREVIEW_DIR/node_modules/express" ]; then
    echo "$(date): npm install for preview..." >> "$LOG"
    cd "$PREVIEW_DIR" && "$NPM_BIN" install --production >> "$LOG" 2>&1
fi

# --- Patchright + Playwright in preview (one-time each) ---
if [ ! -f "$PREVIEW_DIR/.patchright_installed" ]; then
    echo "$(date): Installing Patchright + Chromium (preview)..." >> "$LOG"
    cd "$PREVIEW_DIR" && "$NPX_BIN" patchright install --with-deps chromium >> "$LOG" 2>&1
    "$NPX_BIN" patchright --version > /dev/null 2>&1 && touch "$PREVIEW_DIR/.patchright_installed"
fi
if [ ! -f "$PREVIEW_DIR/.playwright_installed" ]; then
    echo "$(date): Installing Playwright + Chromium (preview fallback)..." >> "$LOG"
    cd "$PREVIEW_DIR" && "$NPX_BIN" playwright install --with-deps chromium >> "$LOG" 2>&1
    "$NPX_BIN" playwright --version > /dev/null 2>&1 && touch "$PREVIEW_DIR/.playwright_installed"
fi

# --- System fonts: install Microsoft core fonts + Liberation + Noto so
# the font-enumeration fingerprint looks like a consumer Windows machine,
# not a bare DejaVu-only Linux server. One-time; non-interactive EULA. ---
if [ ! -f /opt/.car_offers_fonts_installed ]; then
    echo "$(date): [car-offers] Installing consumer fonts (mscorefonts + liberation + noto)..." >> "$LOG"
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections >> "$LOG" 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ttf-mscorefonts-installer fonts-liberation fonts-noto-core fontconfig \
        >> "$LOG" 2>&1 || true
    fc-cache -f >> "$LOG" 2>&1 || true
    touch /opt/.car_offers_fonts_installed
fi

# --- Xvfb as a managed systemd unit so it survives reboots and isn't
# reaped when the deploy shell exits. 1920x1080 matches our fingerprint
# baseline; browser.js still reports the per-session window size via
# window.screen.* patches. ---
if ! command -v Xvfb >/dev/null 2>&1; then
    apt-get install -y xvfb >> "$LOG" 2>&1 || true
fi
if command -v Xvfb >/dev/null 2>&1; then
    cat > /etc/systemd/system/xvfb.service <<'XVFBEOF'
[Unit]
Description=Xvfb virtual framebuffer on :99
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
XVFBEOF
    systemctl daemon-reload
    systemctl enable --now xvfb.service >> "$LOG" 2>&1 || true
fi
DISPLAY_LINE=""
command -v Xvfb >/dev/null 2>&1 && DISPLAY_LINE="Environment=DISPLAY=:99"

# --- Bootstrap LIVE_DIR from preview if empty (first install only) ---
if [ ! -d "$LIVE_DIR/node_modules" ]; then
    echo "$(date): Bootstrapping live from preview (first install)..." >> "$LOG"
    rsync -a --exclude='.env' "$PREVIEW_DIR/" "$LIVE_DIR/"
fi

# --- systemd units (always rewrite to pick up changes) ---
# NOTE: TZ=America/New_York is critical — Decodo sticky session returns
# Norwalk CT IPs; if Chromium's host clock is UTC, Intl.DateTimeFormat
# reports a TZ that contradicts the proxy IP and fails CF's timezone check.
write_unit() {
    local name="$1" dir="$2" port="$3" desc="$4"
    cat > /etc/systemd/system/$name.service <<EOF
[Unit]
Description=$desc
After=network.target xvfb.service
Wants=xvfb.service

[Service]
Type=simple
WorkingDirectory=$dir
ExecStart=$NODE_BIN server.js
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=TZ=America/New_York
$DISPLAY_LINE
StandardOutput=append:$LOG_DIR/$name.log
StandardError=append:$LOG_DIR/$name.log

[Install]
WantedBy=multi-user.target
EOF
}
write_unit "$PROJECT"         "$LIVE_DIR"    "$LIVE_PORT"    "Car Offer Tool — LIVE (port $LIVE_PORT)"
write_unit "$PROJECT-preview" "$PREVIEW_DIR" "$PREVIEW_PORT" "Car Offer Tool — PREVIEW (port $PREVIEW_PORT)"
systemctl daemon-reload
systemctl enable $PROJECT $PROJECT-preview >> "$LOG" 2>&1

# --- Start live if deps ready AND not already running (don't restart live on deploy) ---
if [ -d "$LIVE_DIR/node_modules/express" ] && ! systemctl is-active $PROJECT >/dev/null 2>&1; then
    systemctl start $PROJECT >> "$LOG" 2>&1
    echo "$(date): $PROJECT live service started (bootstrap)." >> "$LOG"
fi

# --- Restart preview on every deploy (this is where new code lives) ---
if [ -d "$PREVIEW_DIR/node_modules/express" ]; then
    systemctl restart $PROJECT-preview >> "$LOG" 2>&1
    echo "$(date): $PROJECT preview restarted." >> "$LOG"
else
    echo "$(date): $PROJECT preview deps not ready — skipping service start." >> "$LOG"
fi

# --- Observability (one-time) ---
if [ ! -f /opt/.car_offers_logs_initialized ]; then
    touch "$LOG_DIR/error.log" "$LOG_DIR/preview.log" "$LOG_DIR/uptime.log"
    cat > /etc/logrotate.d/$PROJECT <<'LREOF'
/var/log/car-offers/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF
    (crontab -l 2>/dev/null; echo "*/5 * * * * curl -sf http://127.0.0.1:$LIVE_PORT/ > /dev/null || echo \"\$(date) DOWN\" >> $LOG_DIR/uptime.log") | crontab -
    touch /opt/.car_offers_logs_initialized
fi

echo "$(date): $PROJECT deploy block done (preview updated; live unchanged)." >> "$LOG"
