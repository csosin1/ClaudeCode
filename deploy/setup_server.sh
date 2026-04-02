#!/bin/bash
# ============================================================
# Carvana ABS Dashboard — Server Setup Script
# Run this ONCE on a fresh Ubuntu 24.04 DigitalOcean droplet.
# ============================================================
set -e

echo "============================================================"
echo "  Carvana ABS Dashboard — Server Setup"
echo "============================================================"

# --- Config (edit these if needed) ---
REPO_URL="https://github.com/csosin1/ClaudeCode.git"
BRANCH="claude/carvana-loan-dashboard-4QMPM"
APP_DIR="/opt/abs-dashboard"
SEC_USER_AGENT="Clifford Sosin clifford.sosin@casinvestmentpartners.com"
DASHBOARD_PORT=8501
DASH_USER="abs"
DASH_PASS="carvana2020"  # Change this after setup!

echo ""
echo "Step 1/7: Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx apache2-utils git > /dev/null 2>&1
echo "  Done."

echo ""
echo "Step 2/7: Cloning repository..."
rm -rf "$APP_DIR"
git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
echo "  Done."

echo ""
echo "Step 3/7: Installing Python dependencies..."
cd "$APP_DIR/carvana_abs"
python3 -m venv /opt/abs-venv
/opt/abs-venv/bin/pip install --quiet -r requirements.txt
echo "  Done."

echo ""
echo "Step 4/7: Running initial data ingestion (this takes ~10 minutes)..."
export SEC_USER_AGENT="$SEC_USER_AGENT"
/opt/abs-venv/bin/python run_ingestion.py 2>&1 | tail -20
echo "  Done."

echo ""
echo "Step 5/7: Setting up Streamlit as a system service..."
cat > /etc/systemd/system/streamlit.service << 'SVCEOF'
[Unit]
Description=Streamlit ABS Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/abs-dashboard
Environment="SEC_USER_AGENT=Clifford Sosin clifford.sosin@casinvestmentpartners.com"
ExecStart=/opt/abs-venv/bin/python -m streamlit run carvana_abs/dashboard/app.py --server.port=8501 --server.address=127.0.0.1 --server.headless=true --server.fileWatcherType=none --browser.gatherUsageStats=false
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable streamlit
systemctl start streamlit
echo "  Streamlit service started."

echo ""
echo "Step 6/7: Setting up nginx with password protection..."
# Create password file for basic auth
htpasswd -cb /etc/nginx/.htpasswd "$DASH_USER" "$DASH_PASS"

# Copy games to web-servable location
mkdir -p /var/www/games
cp "$APP_DIR"/*.html /var/www/games/ 2>/dev/null || true

cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    # Dashboard — no auth
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Streamlit static assets (no auth needed for CSS/JS)
    location /_stcore/ {
        proxy_pass http://127.0.0.1:8501/_stcore/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Games — no password needed (for the kids)
    location /games/ {
        alias /var/www/games/;
        index index.html;
    }
}
NGXEOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/abs-dashboard /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx
echo "  Nginx configured."

echo ""
echo "Step 7/7: Setting up daily auto-ingestion cron job..."
cat > /opt/abs-dashboard/deploy/cron_ingest.sh << 'CRONEOF'
#!/bin/bash
# Daily SEC EDGAR ingestion — runs via cron
cd /opt/abs-dashboard/carvana_abs
export SEC_USER_AGENT="Clifford Sosin clifford.sosin@casinvestmentpartners.com"
/opt/abs-venv/bin/python run_ingestion.py >> /var/log/abs-ingestion.log 2>&1

# Pull latest code from GitHub (picks up dashboard changes)
cd /opt/abs-dashboard
git pull origin claude/carvana-loan-dashboard-4QMPM >> /var/log/abs-ingestion.log 2>&1

# Export dashboard DB and restart
/opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/export_dashboard_db.py >> /var/log/abs-ingestion.log 2>&1
systemctl restart streamlit
CRONEOF
chmod +x /opt/abs-dashboard/deploy/cron_ingest.sh

# Run at 6 AM UTC every day
(crontab -l 2>/dev/null; echo "0 6 * * * /opt/abs-dashboard/deploy/cron_ingest.sh") | sort -u | crontab -
echo "  Cron job set for 6 AM UTC daily."

echo ""
echo "============================================================"
echo "  SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "  Dashboard:  http://$(curl -s ifconfig.me)"
echo "  Username:   $DASH_USER"
echo "  Password:   $DASH_PASS"
echo ""
echo "  Games:      http://$(curl -s ifconfig.me)/games/"
echo ""
echo "  IMPORTANT: Change your password!"
echo "    Run: htpasswd /etc/nginx/.htpasswd $DASH_USER"
echo ""
echo "  Daily auto-ingestion runs at 6 AM UTC."
echo "  Logs: /var/log/abs-ingestion.log"
echo ""
echo "  To update the dashboard code:"
echo "    cd /opt/abs-dashboard && git pull && systemctl restart streamlit"
echo "============================================================"
