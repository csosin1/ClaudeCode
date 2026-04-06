#!/bin/bash
# Deploy script for gym-intelligence (Flask on port 8502)
# OWNED BY: gym-intelligence chat. This file can be modified by the project chat directly.
# The main deploy script (auto_deploy_general.sh) sources this file.
#
# Available variables from parent: $REPO_DIR, $LOG

PROJECT="gym-intelligence"
PROJECT_DIR="/opt/$PROJECT"
LOG_DIR="/var/log/$PROJECT"

if [ ! -d "$REPO_DIR/$PROJECT" ]; then
    return 0 2>/dev/null || exit 0
fi

mkdir -p "$PROJECT_DIR"
mkdir -p "$LOG_DIR"

# Sync code (preserve venv, .env, *.db)
rsync -a --delete \
    --exclude='venv' \
    --exclude='*.db' \
    --exclude='.env' \
    --exclude='__pycache__' \
    "$REPO_DIR/$PROJECT/" "$PROJECT_DIR/"

# .env (one-time — user fills in API key via /gym-intelligence/ Admin tab)
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'ENVEOF'
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
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "$(date): Creating $PROJECT venv..." >> "$LOG"
    if ! "$PYTHON_BIN" -m venv --help > /dev/null 2>&1; then
        apt-get install -y python3-venv >> "$LOG" 2>&1
    fi
    "$PYTHON_BIN" -m venv "$PROJECT_DIR/venv" >> "$LOG" 2>&1
    "$PROJECT_DIR/venv/bin/pip" install --upgrade pip >> "$LOG" 2>&1
fi

# Re-install deps if requirements.txt changed or flask missing
if [ "$REPO_DIR/$PROJECT/requirements.txt" -nt /opt/.gym-intelligence-deps ] || \
   ! "$PROJECT_DIR/venv/bin/python" -c "import flask" 2>/dev/null; then
    echo "$(date): pip install for $PROJECT..." >> "$LOG"
    "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" >> "$LOG" 2>&1
    if "$PROJECT_DIR/venv/bin/python" -c "import flask" 2>/dev/null; then
        touch /opt/.gym-intelligence-deps
        echo "$(date): $PROJECT pip install complete." >> "$LOG"
    else
        echo "$(date): ERROR — $PROJECT pip install failed (flask missing)." >> "$LOG"
    fi
fi

# systemd service (always rewrite to pick up changes)
cat > /etc/systemd/system/$PROJECT.service << 'SVCEOF'
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
systemctl enable $PROJECT >> "$LOG" 2>&1

# Only start service if deps are ready (prevents 502 on first deploy)
if "$PROJECT_DIR/venv/bin/python" -c "import flask" 2>/dev/null; then
    systemctl restart $PROJECT >> "$LOG" 2>&1
    echo "$(date): $PROJECT service restarted." >> "$LOG"
else
    echo "$(date): $PROJECT deps not ready — skipping service start." >> "$LOG"
fi

# Observability (one-time)
if [ ! -f /opt/.gym_intelligence_logs_initialized ]; then
    touch "$LOG_DIR/app.log"
    cat > /etc/logrotate.d/$PROJECT << 'LREOF'
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

# Data collection: run until DB is populated
if [ -f "$PROJECT_DIR/test_collect.py" ]; then
    GYM_COUNT=$("$PROJECT_DIR/venv/bin/python" -c "
from db import get_connection
c = get_connection()
r = c.execute('SELECT COUNT(*) as n FROM locations WHERE active=1').fetchone()
print(r['n'])
c.close()
" 2>/dev/null || echo "0")
    if [ "$GYM_COUNT" -lt 10 ]; then
        echo "$(date): Running gym data collection (currently $GYM_COUNT locations)..." >> "$LOG"
        rm -f "$PROJECT_DIR/test_results.json"
        cd "$PROJECT_DIR"
        "$PROJECT_DIR/venv/bin/python" test_collect.py >> "$LOG" 2>&1
        echo "$(date): Collection script finished." >> "$LOG"
    fi
fi

# Write DB status for monitoring
cd "$PROJECT_DIR"
"$PROJECT_DIR/venv/bin/python" check_db.py >> "$LOG" 2>&1 || true

echo "$(date): $PROJECT deploy block done." >> "$LOG"
