#!/bin/bash
# Deploy script for timeshare-surveillance — preview-first.
#
# Every push updates PREVIEW_DIR. LIVE_DIR only changes via promote.sh.
# Two systemd units per instance:
#   timeshare-surveillance-watcher{,-preview}.service  (EDGAR poller)
#   timeshare-surveillance-admin{,-preview}.service    (Flask setup page)
#
# Ports:
#   admin live:    8510
#   admin preview: 8511
#
# Available variables from parent auto_deploy_general.sh: $REPO_DIR, $LOG

PROJECT="timeshare-surveillance"
LIVE_DIR="/opt/$PROJECT-live"
PREVIEW_DIR="/opt/$PROJECT-preview"
LOG_DIR="/var/log/$PROJECT"
LIVE_ADMIN_PORT=8510
PREVIEW_ADMIN_PORT=8511
SOURCE_DIR="$REPO_DIR/$PROJECT"

if [ ! -d "$SOURCE_DIR" ]; then
    return 0 2>/dev/null || exit 0
fi

mkdir -p "$LIVE_DIR" "$PREVIEW_DIR" "$LOG_DIR"

# --- Sync source to PREVIEW only ---
# sec_cache/ is excluded so the persistent raw-SEC cache survives redeploys —
# a full 5-year re-extraction would otherwise re-download 75+ filings.
rsync -a --delete \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='data/raw/*' \
    --include='data/raw/.gitkeep' \
    --exclude='data/sec_cache/*' \
    --include='data/sec_cache/.gitkeep' \
    --exclude='data/surveillance.db' \
    --exclude='data/surveillance.db-wal' \
    --exclude='data/surveillance.db-shm' \
    --exclude='data/combined.json' \
    --exclude='data/seen_accessions.json' \
    --exclude='data/flag_state.json' \
    --exclude='dashboard/data/combined.json' \
    "$SOURCE_DIR/" "$PREVIEW_DIR/"

# Ensure raw/ and sec_cache/ dirs exist after rsync exclude
mkdir -p "$PREVIEW_DIR/data/raw" "$LIVE_DIR/data/raw" \
         "$PREVIEW_DIR/data/sec_cache" "$LIVE_DIR/data/sec_cache"
touch "$PREVIEW_DIR/data/raw/.gitkeep" "$LIVE_DIR/data/raw/.gitkeep" \
      "$PREVIEW_DIR/data/sec_cache/.gitkeep" "$LIVE_DIR/data/sec_cache/.gitkeep"

# Ensure dashboard/data/combined.json exists so first page load doesn't 404.
# Dashboard fetches ./data/combined.json relative to nginx alias = $dir/dashboard/.
for d in "$PREVIEW_DIR" "$LIVE_DIR"; do
    mkdir -p "$d/dashboard/data"
    [ -f "$d/dashboard/data/combined.json" ] || echo '[]' > "$d/dashboard/data/combined.json"
done

# --- Find python3 ---
PYTHON_BIN=""
for candidate in /usr/bin/python3 /usr/local/bin/python3; do
    [ -x "$candidate" ] && PYTHON_BIN="$candidate" && break
done
[ -z "$PYTHON_BIN" ] && PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    apt-get update >> "$LOG" 2>&1
    apt-get install -y python3 python3-venv python3-pip >> "$LOG" 2>&1
    PYTHON_BIN="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"
fi

# --- Per-instance venv ---
ensure_venv() {
    local dir="$1"
    if [ ! -d "$dir/venv" ]; then
        "$PYTHON_BIN" -m venv "$dir/venv" >> "$LOG" 2>&1
        "$dir/venv/bin/pip" install --quiet --upgrade pip >> "$LOG" 2>&1
    fi
    if [ "$SOURCE_DIR/pipeline/requirements.txt" -nt "$dir/.deps_installed" ] \
        || ! "$dir/venv/bin/python" -c "import flask, anthropic, requests, dateutil" 2>/dev/null; then
        "$dir/venv/bin/pip" install -q -r "$SOURCE_DIR/pipeline/requirements.txt" >> "$LOG" 2>&1
        "$dir/venv/bin/python" -c "import flask, anthropic, requests, dateutil" 2>/dev/null \
            && touch "$dir/.deps_installed"
    fi
}
ensure_venv "$PREVIEW_DIR"

# --- .env bootstrap — generate ADMIN_TOKEN on first install ---
write_env_if_absent() {
    local dir="$1" port="$2" suffix="$3"
    local env_path="$dir/.env"
    if [ -f "$env_path" ]; then
        return 0
    fi
    local token
    token="$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | xxd -p)"
    cat > "$env_path" <<ENVEOF
# timeshare-surveillance env — fill in via the /admin/ setup page
ANTHROPIC_API_KEY=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL=
ADMIN_TOKEN=$token
ADMIN_PORT=$port
INSTANCE_LABEL=${suffix}
DASHBOARD_SERVE_DIR=$dir/dashboard
ENVEOF
    # DASHBOARD_URL depends on live vs preview — append so the path is correct.
    if [ "$suffix" = "preview" ]; then
        echo "DASHBOARD_URL=https://casinv.dev/timeshare-surveillance/preview/" >> "$env_path"
    else
        echo "DASHBOARD_URL=https://casinv.dev/timeshare-surveillance/" >> "$env_path"
    fi
    chmod 600 "$env_path"
    # Mirror ADMIN_TOKEN so the orchestrator can retrieve and notify the user.
    mkdir -p "$LOG_DIR"
    local mirror="$LOG_DIR/ADMIN_TOKEN_${suffix:-live}.txt"
    printf '%s\n' "$token" > "$mirror"
    chmod 600 "$mirror"
    echo "$(date): Bootstrapped .env for $dir (token mirrored to $mirror)." >> "$LOG"
}
write_env_if_absent "$PREVIEW_DIR" "$PREVIEW_ADMIN_PORT" "preview"

# --- Bootstrap LIVE_DIR from preview's code if empty (first install only) ---
if [ ! -f "$LIVE_DIR/pipeline/fetch_and_parse.py" ]; then
    echo "$(date): Bootstrapping live from preview (first install)..." >> "$LOG"
    rsync -a \
        --exclude='venv' \
        --exclude='.env' \
        --exclude='__pycache__' \
        "$PREVIEW_DIR/" "$LIVE_DIR/"
fi
write_env_if_absent "$LIVE_DIR" "$LIVE_ADMIN_PORT" "live"
ensure_venv "$LIVE_DIR"

# --- Render + install systemd units (always rewrite to pick up template changes) ---
render_unit() {
    local template="$1" out="$2" project_dir="$3"
    sed -e "s|__PROJECT_DIR__|$project_dir|g" \
        -e "s|__VENV__|$project_dir/venv|g" \
        "$template" > "$out"
}

WATCHER_TPL="$SOURCE_DIR/watcher/watcher.service.template"
ADMIN_TPL="$SOURCE_DIR/watcher/admin.service.template"

render_unit "$WATCHER_TPL" "/etc/systemd/system/timeshare-surveillance-watcher.service" "$LIVE_DIR"
render_unit "$WATCHER_TPL" "/etc/systemd/system/timeshare-surveillance-watcher-preview.service" "$PREVIEW_DIR"
render_unit "$ADMIN_TPL"   "/etc/systemd/system/timeshare-surveillance-admin.service"   "$LIVE_DIR"
render_unit "$ADMIN_TPL"   "/etc/systemd/system/timeshare-surveillance-admin-preview.service" "$PREVIEW_DIR"

systemctl daemon-reload
systemctl enable \
    timeshare-surveillance-watcher \
    timeshare-surveillance-watcher-preview \
    timeshare-surveillance-admin \
    timeshare-surveillance-admin-preview >> "$LOG" 2>&1

# Start live units if deps ready AND not running (bootstrap only).
if "$LIVE_DIR/venv/bin/python" -c "import flask, anthropic" 2>/dev/null; then
    for svc in timeshare-surveillance-watcher timeshare-surveillance-admin; do
        if ! systemctl is-active "$svc" >/dev/null 2>&1; then
            systemctl start "$svc" >> "$LOG" 2>&1 && \
                echo "$(date): started $svc (bootstrap)" >> "$LOG"
        fi
    done
fi

# Restart preview units on every deploy.
if "$PREVIEW_DIR/venv/bin/python" -c "import flask, anthropic" 2>/dev/null; then
    systemctl restart timeshare-surveillance-watcher-preview timeshare-surveillance-admin-preview >> "$LOG" 2>&1
    echo "$(date): $PROJECT preview units restarted." >> "$LOG"
else
    echo "$(date): $PROJECT preview deps not ready — skipping restart." >> "$LOG"
fi

# --- Observability (one-time) ---
if [ ! -f /opt/.timeshare_surveillance_logs_initialized ]; then
    touch "$LOG_DIR/watcher.log" "$LOG_DIR/admin.log" \
          "$LOG_DIR/pipeline.log" "$LOG_DIR/cron_refresh.log" \
          "$LOG_DIR/uptime.log"
    cat > /etc/logrotate.d/$PROJECT <<'LREOF'
/var/log/timeshare-surveillance/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF

    # 5-min uptime cron against the live dashboard.
    ( crontab -l 2>/dev/null | grep -v '/timeshare-surveillance/ > /dev/null' ; \
      echo "*/5 * * * * curl -sf http://127.0.0.1/timeshare-surveillance/ > /dev/null || echo \"\$(date) DOWN timeshare\" >> /var/log/timeshare-surveillance/uptime.log" ) | crontab -

    # Weekly refresh cron (live only).
    ( crontab -l 2>/dev/null | grep -v 'timeshare-surveillance-live/watcher/cron_refresh.sh' ; \
      echo "0 6 * * 0 /opt/timeshare-surveillance-live/watcher/cron_refresh.sh" ) | crontab -

    chmod +x "$LIVE_DIR/watcher/cron_refresh.sh" "$PREVIEW_DIR/watcher/cron_refresh.sh" 2>/dev/null || true

    touch /opt/.timeshare_surveillance_logs_initialized
fi

# Always keep cron_refresh.sh executable (it may be rsynced afresh).
chmod +x "$LIVE_DIR/watcher/cron_refresh.sh" "$PREVIEW_DIR/watcher/cron_refresh.sh" 2>/dev/null || true

echo "$(date): $PROJECT deploy block done (preview updated; live unchanged)." >> "$LOG"
