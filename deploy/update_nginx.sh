#!/bin/bash
# Update nginx for multi-project layout.
# Each project is served from its own isolated directory.

# Ensure landing page directory exists
mkdir -p /var/www/landing
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/landing.html" /var/www/landing/index.html 2>/dev/null || true

cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name casinv.dev 159.223.127.125;

    # Landing page — project index
    location / {
        alias /var/www/landing/;
        index index.html;
    }

    # Trailing-slash redirects
    location = /CarvanaLoanDashBoard {
        return 301 /CarvanaLoanDashBoard/;
    }
    location = /CarvanaLoanDashBoard/preview {
        return 301 /CarvanaLoanDashBoard/preview/;
    }

    # Carvana ABS Dashboard — preview (must come before live for longest-prefix match)
    location /CarvanaLoanDashBoard/preview/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/preview/;
        index index.html;
        try_files $uri $uri/ /CarvanaLoanDashBoard/preview/index.html;
    }

    # Carvana ABS Dashboard — live
    location /CarvanaLoanDashBoard/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/live/;
        index index.html;
        try_files $uri $uri/ /CarvanaLoanDashBoard/index.html;
    }

    # Carvana hub — static page with cards for ABS Dashboard + Car Offers
    location = /carvana { return 301 /carvana/; }
    location /carvana/ {
        alias /var/www/carvana/;
        index index.html;
    }

    # Car Offers — reverse proxy to Express on port 3100
    location = /car-offers { return 301 /car-offers/; }
    location /car-offers/ {
        proxy_pass http://127.0.0.1:3100/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;
    }

    # Gym Intelligence — reverse proxy to Streamlit on port 8502
    location = /gym-intelligence { return 301 /gym-intelligence/; }
    location /gym-intelligence/ {
        proxy_pass http://127.0.0.1:8502/gym-intelligence/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;

        # WebSocket support (required by Streamlit)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Streamlit internal paths (health check, static assets, API)
    location /gym-intelligence/_stcore/ {
        proxy_pass http://127.0.0.1:8502/gym-intelligence/_stcore/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Games — isolated to /var/www/games/
    location /games/ {
        alias /var/www/games/;
        index index.html;
    }

    # Webhook deploy endpoint (proxied to localhost Python listener)
    location = /webhook/deploy {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
        proxy_read_timeout 120s;
        limit_except POST { deny all; }
    }

    # Webhook health check
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
echo "Nginx updated — multi-project layout active."

# Re-apply SSL certificates if certbot is installed and certs exist
if command -v certbot >/dev/null 2>&1; then
    if [ -d "/etc/letsencrypt/live/casinv.dev" ]; then
        echo "Re-applying SSL certificates..."
        certbot --nginx --non-interactive --agree-tos --expand --email admin@casinv.dev \
            -d casinv.dev -d code.casinv.dev --redirect 2>&1 || echo "certbot re-apply failed (non-fatal)"
    fi
fi
