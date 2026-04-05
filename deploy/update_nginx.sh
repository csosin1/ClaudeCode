#!/bin/bash
# Update nginx for multi-project layout.
# Each project is served from its own isolated directory.

# Ensure landing page directory exists
mkdir -p /var/www/landing
cp /opt/abs-dashboard/deploy/landing.html /var/www/landing/index.html

cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;

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
}
NGXEOF

nginx -t && systemctl reload nginx
echo "Nginx updated — multi-project layout active."
