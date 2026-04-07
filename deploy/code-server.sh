#!/bin/bash
# Deploy script for code-server (VS Code in browser)
# OWNED BY: infrastructure chat
# Accessible at https://code.casinv.dev after HTTPS setup
#
# Available variables from parent: $REPO_DIR, $LOG, $NODE_BIN, $NPM_BIN, $NPX_BIN

PROJECT="code-server"
CODE_SERVER_PORT=8443
DOMAIN="casinv.dev"
CODE_DOMAIN="code.$DOMAIN"

# === ONE-TIME: Install code-server ===
if [ ! -f /opt/.code-server-installed ]; then
    echo "$(date): Installing code-server..." >> "$LOG"
    curl -fsSL https://code-server.dev/install.sh | sh >> "$LOG" 2>&1

    # Verify install actually worked before proceeding
    CS_BIN=$(command -v code-server 2>/dev/null || echo "")
    if [ -z "$CS_BIN" ]; then
        echo "$(date): ERROR — code-server binary not found after install. Skipping." >> "$LOG"
        return 0 2>/dev/null || exit 0
    fi

    # Generate a random password if none exists
    if [ ! -f /opt/.code-server-password ]; then
        CODE_PASS=$(openssl rand -base64 18)
        echo "$CODE_PASS" > /opt/.code-server-password
        chmod 600 /opt/.code-server-password
    fi

    # Configure code-server
    mkdir -p ~/.config/code-server
    cat > ~/.config/code-server/config.yaml << CSEOF
bind-addr: 127.0.0.1:$CODE_SERVER_PORT
auth: password
password: $(cat /opt/.code-server-password)
cert: false
CSEOF

    # systemd service — use discovered binary path
    cat > /etc/systemd/system/code-server.service << SVCEOF
[Unit]
Description=code-server (VS Code in browser)
After=network.target

[Service]
Type=exec
ExecStart=$CS_BIN
Restart=always
RestartSec=3
Environment=HOME=/root

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable code-server >> "$LOG" 2>&1
    systemctl start code-server >> "$LOG" 2>&1

    # Only set flag if service is actually running
    if systemctl is-active --quiet code-server; then
        touch /opt/.code-server-installed
        echo "$(date): code-server installed at $CS_BIN and running on port $CODE_SERVER_PORT." >> "$LOG"
    else
        echo "$(date): ERROR — code-server installed but service failed to start." >> "$LOG"
    fi
fi

# === ONE-TIME: Install Claude Code CLI ===
if [ ! -f /opt/.claude-code-installed ]; then
    echo "$(date): Installing Claude Code CLI..." >> "$LOG"
    curl -fsSL https://claude.ai/install.sh | sh >> "$LOG" 2>&1
    touch /opt/.claude-code-installed
    echo "$(date): Claude Code CLI installed." >> "$LOG"
fi

# === ONE-TIME: Install certbot and get HTTPS certificates ===
if [ ! -f /opt/.certbot-installed ]; then
    echo "$(date): Installing certbot for HTTPS..." >> "$LOG"
    apt-get update -qq >> "$LOG" 2>&1
    apt-get install -y certbot python3-certbot-nginx >> "$LOG" 2>&1
    touch /opt/.certbot-installed
    echo "$(date): certbot installed." >> "$LOG"
fi

# === ONE-TIME: Get SSL certificates for both domains ===
if [ ! -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "$(date): Requesting Let's Encrypt certificate for $DOMAIN and $CODE_DOMAIN..." >> "$LOG"

    # Need to temporarily allow HTTP on both domains for ACME challenge
    # certbot will handle nginx config for HTTPS
    certbot --nginx --non-interactive --agree-tos \
        --email admin@$DOMAIN \
        -d "$DOMAIN" -d "$CODE_DOMAIN" \
        --redirect >> "$LOG" 2>&1 || {
        echo "$(date): certbot failed — will retry on next deploy. DNS may not have propagated yet." >> "$LOG"
        # Don't set flag so it retries next deploy
    }

    # Set up auto-renewal
    if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
        # certbot auto-renew is handled by the certbot systemd timer (installed automatically)
        echo "$(date): HTTPS certificates obtained for $DOMAIN and $CODE_DOMAIN." >> "$LOG"
    fi
fi

# Ensure code-server is running
if ! systemctl is-active --quiet code-server; then
    systemctl start code-server >> "$LOG" 2>&1
    echo "$(date): code-server restarted." >> "$LOG"
fi

# === TEMPORARY: Serve password on a one-time setup page ===
# This page shows the code-server password so the user can see it from their phone.
# It auto-deletes after 1 hour via a background job.
if [ -f /opt/.code-server-password ] && [ ! -f /opt/.code-server-setup-done ]; then
    PASS=$(cat /opt/.code-server-password)
    mkdir -p /var/www/landing/cs-setup
    cat > /var/www/landing/cs-setup/index.html << SETUPEOF
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Code Server Setup</title>
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 400px; margin: 40px auto; padding: 20px; background: #0d1117; color: #e6edf3; }
        .password { font-size: 24px; font-family: monospace; background: #161b22; padding: 16px; border-radius: 8px; text-align: center; margin: 20px 0; user-select: all; -webkit-user-select: all; border: 1px solid #30363d; }
        h1 { font-size: 20px; }
        p { color: #8b949e; line-height: 1.5; }
        .step { background: #161b22; padding: 12px; border-radius: 6px; margin: 8px 0; border-left: 3px solid #58a6ff; }
        .warn { color: #f85149; font-weight: bold; margin-top: 24px; }
    </style>
</head>
<body>
    <h1>Code Server Password</h1>
    <p>Tap and hold to copy:</p>
    <div class="password">$PASS</div>
    <div class="step">1. Go to <b>https://$CODE_DOMAIN</b></div>
    <div class="step">2. Paste the password above</div>
    <div class="step">3. Bookmark the page</div>
    <div class="step">4. You won't need the password again (session lasts 30 days)</div>
    <p class="warn">This page auto-deletes in 1 hour.</p>
</body>
</html>
SETUPEOF

    # Schedule deletion of the setup page in 1 hour
    (sleep 3600 && rm -rf /var/www/landing/cs-setup && touch /opt/.code-server-setup-done) &
    echo "$(date): Setup page created at /cs-setup/ — expires in 1 hour." >> "$LOG"
fi

echo "$(date): code-server deploy block done." >> "$LOG"
