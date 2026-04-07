#!/bin/bash
# Deploy script for web terminal (ttyd) + Claude Code CLI
# Accessible at https://code.casinv.dev
#
# Available variables from parent: $REPO_DIR, $LOG, $NODE_BIN, $NPM_BIN, $NPX_BIN

TTYD_PORT=7681
PASSWORD_FILE="/opt/.code-server-password"

# === ONE-TIME: Install ttyd ===
if ! command -v ttyd >/dev/null 2>&1; then
    echo "$(date): Installing ttyd..." >> "$LOG"
    apt-get update -qq >> "$LOG" 2>&1
    apt-get install -y ttyd >> "$LOG" 2>&1
    echo "$(date): ttyd installed." >> "$LOG"
fi

# === ONE-TIME: Install Claude Code CLI ===
if ! command -v claude >/dev/null 2>&1; then
    echo "$(date): Installing Claude Code CLI..." >> "$LOG"
    curl -fsSL https://claude.ai/install.sh | sh >> "$LOG" 2>&1
    echo "$(date): Claude Code CLI installed." >> "$LOG"
fi

# === Generate password if none exists ===
if [ ! -f "$PASSWORD_FILE" ]; then
    openssl rand -base64 18 > "$PASSWORD_FILE"
    chmod 600 "$PASSWORD_FILE"
fi
PASS=$(cat "$PASSWORD_FILE")

# === Stop code-server if running (replaced by ttyd) ===
if systemctl is-active --quiet code-server 2>/dev/null; then
    systemctl stop code-server >> "$LOG" 2>&1
    systemctl disable code-server >> "$LOG" 2>&1
    echo "$(date): Stopped code-server (replaced by ttyd)." >> "$LOG"
fi

# === systemd service for ttyd ===
cat > /etc/systemd/system/web-terminal.service << SVCEOF
[Unit]
Description=Web Terminal (ttyd + Claude Code)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/ttyd \
    -i 127.0.0.1 \
    -p $TTYD_PORT \
    -c admin:$PASS \
    -t fontSize=16 \
    -t fontFamily=monospace \
    -t cursorBlink=true \
    bash
Restart=always
RestartSec=3
Environment=HOME=/root
Environment=PATH=/root/.claude/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable web-terminal >> "$LOG" 2>&1

# Start or restart
if systemctl is-active --quiet web-terminal; then
    systemctl restart web-terminal >> "$LOG" 2>&1
else
    systemctl start web-terminal >> "$LOG" 2>&1
fi

if systemctl is-active --quiet web-terminal; then
    echo "$(date): web-terminal running on port $TTYD_PORT." >> "$LOG"
else
    echo "$(date): ERROR — web-terminal failed to start." >> "$LOG"
fi

echo "$(date): web-terminal deploy block done." >> "$LOG"
