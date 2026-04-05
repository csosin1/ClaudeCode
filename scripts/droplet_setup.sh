#!/bin/bash
# droplet_setup.sh — Run on the droplet (via SSH) to complete harness setup.
# Covers: nginx hardening, observability (logging, uptime monitors, logrotate),
# and environment detection.
#
# Usage: ssh root@159.223.127.125 'bash -s' < scripts/droplet_setup.sh

set -euo pipefail

echo "=== Environment Detection ==="
echo "Node: $(node --version 2>/dev/null || echo 'not installed')"
echo "Python: $(python3 --version 2>/dev/null || echo 'not installed')"
echo "nginx: $(nginx -v 2>&1)"
echo "PM2: $(pm2 --version 2>/dev/null || echo 'not installed')"

echo ""
echo "=== nginx Hardening ==="

NGINX_CONF="/etc/nginx/sites-available/abs-dashboard"

if [ ! -f "$NGINX_CONF" ]; then
    echo "ERROR: nginx config not found at $NGINX_CONF"
    exit 1
fi

# Check if deny rules already exist
if grep -q 'deny all.*# harness-security' "$NGINX_CONF" 2>/dev/null; then
    echo "Deny rules already present, skipping."
else
    echo "Adding deny rules for .env, dotfiles, and .md files..."
    # Insert deny rules right after 'server {' line
    sed -i '/^server {/a\
\
    # Security: deny dotfiles, .env, and .md files (harness-security)\
    location ~ /\\.env { deny all; return 404; } # harness-security\
    location ~ /\\. { deny all; return 404; } # harness-security\
    location ~* \\.md$ { deny all; return 404; } # harness-security' "$NGINX_CONF"

    nginx -t && systemctl reload nginx
    echo "nginx hardened and reloaded."
fi

echo ""
echo "=== Observability Setup ==="

# Projects to monitor
declare -A PROJECTS=(
    ["landing"]="/"
    ["games"]="/games/"
    ["carvana"]="/CarvanaLoanDashBoard/"
)

for project in "${!PROJECTS[@]}"; do
    path="${PROJECTS[$project]}"
    logdir="/var/log/$project"

    # Create log directory and error.log
    mkdir -p "$logdir"
    touch "$logdir/error.log"
    touch "$logdir/uptime.log"
    echo "Created $logdir with error.log and uptime.log"

    # Add uptime cron if not already present
    CRON_LINE="*/5 * * * * curl -sf http://159.223.127.125${path} > /dev/null || echo \"\$(date) DOWN\" >> ${logdir}/uptime.log"
    if ! crontab -l 2>/dev/null | grep -qF "$logdir/uptime.log"; then
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo "Added uptime cron for $project"
    else
        echo "Uptime cron for $project already exists"
    fi

    # Configure logrotate
    cat > "/etc/logrotate.d/$project" << LOGEOF
${logdir}/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LOGEOF
    echo "Configured logrotate for $project"
done

echo ""
echo "=== Setup Complete ==="
echo "Run 'crontab -l' to verify cron jobs."
echo "Run 'nginx -t' to verify nginx config."
echo "Check /var/log/{landing,games,carvana}/ for log files."
