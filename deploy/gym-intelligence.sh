#!/bin/bash
# Deploy script for gym-intelligence — preview-first.
# Every push updates PREVIEW_DIR (port 8503, prefix /gym-intelligence/preview).
# Live (port 8502, prefix /gym-intelligence) only changes via promote.sh.
#
# Available variables from parent: $REPO_DIR, $LOG

PROJECT="gym-intelligence"
LIVE_DIR="/opt/$PROJECT"
PREVIEW_DIR="/opt/$PROJECT-preview"
LOG_DIR="/var/log/$PROJECT"

if [ ! -d "$REPO_DIR/$PROJECT" ]; then
    return 0 2>/dev/null || exit 0
fi

mkdir -p "$LIVE_DIR" "$PREVIEW_DIR" "$LOG_DIR"

# --- Sync code to PREVIEW only ---
rsync -a --delete \
    --exclude='venv' \
    --exclude='*.db' \
    --exclude='.env' \
    --exclude='__pycache__' \
    "$REPO_DIR/$PROJECT/" "$PREVIEW_DIR/"

# --- .env bootstrap (shared API key template) ---
write_env() {
    cat > "$1/.env" <<'ENVEOF'
ANTHROPIC_API_KEY=
ENVEOF
}
[ -f "$LIVE_DIR/.env" ]    || write_env "$LIVE_DIR"
[ -f "$PREVIEW_DIR/.env" ] || write_env "$PREVIEW_DIR"

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

# --- Ensure each instance has its own venv ---
ensure_venv() {
    local dir="$1"
    if [ ! -d "$dir/venv" ]; then
        "$PYTHON_BIN" -m venv "$dir/venv" >> "$LOG" 2>&1
        "$dir/venv/bin/pip" install --quiet --upgrade pip >> "$LOG" 2>&1
    fi
    if [ "$REPO_DIR/$PROJECT/requirements.txt" -nt "$dir/.deps_installed" ] || \
       ! "$dir/venv/bin/python" -c "import flask" 2>/dev/null; then
        "$dir/venv/bin/pip" install -q -r "$REPO_DIR/$PROJECT/requirements.txt" >> "$LOG" 2>&1
        "$dir/venv/bin/python" -c "import flask" 2>/dev/null && touch "$dir/.deps_installed"
    fi
}
ensure_venv "$PREVIEW_DIR"

# --- Bootstrap LIVE_DIR from preview's code if empty (first install only) ---
if [ ! -f "$LIVE_DIR/app.py" ]; then
    echo "$(date): Bootstrapping live from preview (first install)..." >> "$LOG"
    rsync -a --exclude='venv' --exclude='.env' --exclude='*.db' "$PREVIEW_DIR/" "$LIVE_DIR/"
fi
ensure_venv "$LIVE_DIR"

# --- systemd units ---
write_unit() {
    local name="$1" dir="$2" port="$3" prefix="$4" desc="$5"
    cat > /etc/systemd/system/$name.service <<EOF
[Unit]
Description=$desc
After=network.target

[Service]
Type=simple
WorkingDirectory=$dir
ExecStart=$dir/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=HOME=/root
Environment=URL_PREFIX=$prefix
Environment=PORT=$port
StandardOutput=append:$LOG_DIR/$name.log
StandardError=append:$LOG_DIR/$name.log

[Install]
WantedBy=multi-user.target
EOF
}
write_unit "$PROJECT"         "$LIVE_DIR"    8502 "/gym-intelligence"         "Gym Intelligence — LIVE"
write_unit "$PROJECT-preview" "$PREVIEW_DIR" 8503 "/gym-intelligence/preview" "Gym Intelligence — PREVIEW"
systemctl daemon-reload
systemctl enable $PROJECT $PROJECT-preview >> "$LOG" 2>&1

# Start live if deps ready AND not running (bootstrap only)
if "$LIVE_DIR/venv/bin/python" -c "import flask" 2>/dev/null && ! systemctl is-active $PROJECT >/dev/null 2>&1; then
    systemctl start $PROJECT >> "$LOG" 2>&1
fi
# Restart preview every deploy
if "$PREVIEW_DIR/venv/bin/python" -c "import flask" 2>/dev/null; then
    systemctl restart $PROJECT-preview >> "$LOG" 2>&1
    echo "$(date): $PROJECT preview restarted." >> "$LOG"
fi

# --- Observability (one-time) ---
if [ ! -f /opt/.gym_intelligence_logs_initialized ]; then
    touch "$LOG_DIR/$PROJECT.log" "$LOG_DIR/$PROJECT-preview.log"
    cat > /etc/logrotate.d/$PROJECT <<'LREOF'
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

# --- DB repair + data collection (on live only; preview shares read access via its own venv) ---
"$LIVE_DIR/venv/bin/python" -c "
import sys; sys.path.insert(0, '$LIVE_DIR')
from db import get_connection, init_db
from collect import assign_chains, update_chain_location_counts
init_db()
conn = get_connection()
inactive = conn.execute('SELECT COUNT(*) as n FROM locations WHERE active=0').fetchone()['n']
if inactive > 0:
    conn.execute('UPDATE locations SET active = 1')
    print(f'Reactivated {inactive} locations.')
unlinked = conn.execute('SELECT COUNT(*) as n FROM locations WHERE chain_id IS NULL').fetchone()['n']
if unlinked > 0:
    assign_chains(conn)
update_chain_location_counts(conn)
conn.commit()
conn.close()
" >> "$LOG" 2>&1 || true

echo "$(date): $PROJECT deploy block done (preview updated; live unchanged)." >> "$LOG"
