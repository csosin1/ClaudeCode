#!/bin/bash
# Update nginx for multi-project layout with preview/live separation.
# Each project has two URLs: /project/ (live) and /project/preview/ (preview).

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure landing page directory structure exists (live + preview + diagnostic root)
mkdir -p /var/www/landing/live /var/www/landing/preview
# Bootstrap: ensure live has an index; if missing, seed from repo
[ -s /var/www/landing/live/index.html ] || cp "$SCRIPT_DIR/landing.html" /var/www/landing/live/index.html 2>/dev/null || true
# Preview always gets the latest from the repo
cp "$SCRIPT_DIR/landing.html" /var/www/landing/preview/index.html 2>/dev/null || true

# Ensure games + carvana preview/live dirs exist
mkdir -p /var/www/games/live /var/www/games/preview
mkdir -p /var/www/carvana/live /var/www/carvana/preview

cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name casinv.dev 159.223.127.125;

    # Landing page — live at /, preview at /preview/, diagnostic JSON files at root
    location = /preview { return 301 /preview/; }
    location /preview/ {
        alias /var/www/landing/preview/;
        index index.html;
    }
    location / {
        root /var/www/landing;
        try_files /live$uri /live$uri/index.html $uri =404;
    }

    # Carvana ABS Dashboard — preview (must come before live for longest-prefix match)
    location = /CarvanaLoanDashBoard { return 301 /CarvanaLoanDashBoard/; }
    location = /CarvanaLoanDashBoard/preview { return 301 /CarvanaLoanDashBoard/preview/; }
    location /CarvanaLoanDashBoard/preview/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/preview/;
        index index.html;
        try_files $uri $uri/ /CarvanaLoanDashBoard/preview/index.html;
    }
    location /CarvanaLoanDashBoard/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/live/;
        index index.html;
        try_files $uri $uri/ /CarvanaLoanDashBoard/index.html;
    }

    # Carvana hub — preview + live
    location = /carvana { return 301 /carvana/; }
    location = /carvana/preview { return 301 /carvana/preview/; }
    location /carvana/preview/ {
        alias /var/www/carvana/preview/;
        index index.html;
    }
    location /carvana/ {
        alias /var/www/carvana/live/;
        index index.html;
    }

    # Car Offers — preview (port 3101) + live (port 3100)
    location = /car-offers { return 301 /car-offers/; }
    location = /car-offers/preview { return 301 /car-offers/preview/; }
    location /car-offers/preview/ {
        proxy_pass http://127.0.0.1:3101/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;
    }
    location /car-offers/ {
        proxy_pass http://127.0.0.1:3100/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;
    }

    # Gym Intelligence — preview (port 8503, prefix /gym-intelligence/preview) + live (port 8502)
    location = /gym-intelligence { return 301 /gym-intelligence/; }
    location = /gym-intelligence/preview { return 301 /gym-intelligence/preview/; }
    location /gym-intelligence/preview/ {
        proxy_pass http://127.0.0.1:8503/gym-intelligence/preview/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
    location /gym-intelligence/ {
        proxy_pass http://127.0.0.1:8502/gym-intelligence/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    # Games — preview + live
    location = /games/preview { return 301 /games/preview/; }
    location /games/preview/ {
        alias /var/www/games/preview/;
        index index.html;
    }
    location /games/ {
        alias /var/www/games/live/;
        index index.html;
    }

    # Webhook deploy endpoint
    location = /webhook/deploy {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
        proxy_read_timeout 120s;
        limit_except POST { deny all; }
    }
    location = /webhook/health {
        proxy_pass http://127.0.0.1:9000/health;
    }

    # Security: block dotfiles, .env, .md
    location ~ /\. { deny all; }
    location ~* \.md$ { deny all; }
    location ~* \.env$ { deny all; }
}

# Web terminal (ttyd) on code.casinv.dev
server {
    listen 80;
    listen [::]:80;
    server_name code.casinv.dev;

    location / {
        proxy_pass http://127.0.0.1:7681;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
NGXEOF

nginx -t && systemctl reload nginx
echo "Nginx updated — multi-project layout with preview/live."

# Make HTTP (port 80) always redirect to HTTPS for any host, not 404 for non-casinv.dev.
# Needed so requests to http://159.223.127.125/ (QA, Playwright, bare-IP access) work.
# This is idempotent — safe to run every time.
sed -i 's|return 404; # managed by Certbot|return 301 https://casinv.dev$request_uri;|g' /etc/nginx/sites-available/abs-dashboard
nginx -t && systemctl reload nginx

# Re-apply SSL certificates if certbot is installed and certs exist
if command -v certbot >/dev/null 2>&1; then
    if [ -d "/etc/letsencrypt/live/casinv.dev" ]; then
        echo "Re-applying SSL certificates..."
        certbot --nginx --non-interactive --agree-tos --expand --email admin@casinv.dev \
            -d casinv.dev -d code.casinv.dev --redirect 2>&1 || echo "certbot re-apply failed (non-fatal)"
    fi
fi
