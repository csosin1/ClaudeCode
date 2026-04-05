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

    # Security: block .env, dotfiles, and .md files
    location ~ /\.env { deny all; return 404; }
    location ~ /\. { deny all; return 404; }
    location ~* \.md$ { deny all; return 404; }

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
}
NGXEOF

nginx -t && systemctl reload nginx
echo "Nginx updated — multi-project layout active."
