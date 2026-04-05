#!/bin/bash
# Set up preview system: /CarvanaLoanDashBoard/preview/ shows candidate,
# /CarvanaLoanDashBoard/ shows approved live version.
# Run once on the server.

mkdir -p /opt/abs-dashboard/carvana_abs/static_site/preview

# Update nginx for multi-project layout
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

    # Carvana ABS Dashboard — preview
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

# Set up landing page
mkdir -p /var/www/landing
cp /opt/abs-dashboard/deploy/landing.html /var/www/landing/index.html

# Move current index.html to live/
mkdir -p /opt/abs-dashboard/carvana_abs/static_site/live
if [ -f /opt/abs-dashboard/carvana_abs/static_site/index.html ]; then
    cp /opt/abs-dashboard/carvana_abs/static_site/index.html /opt/abs-dashboard/carvana_abs/static_site/live/index.html
fi

nginx -t && systemctl reload nginx
echo "Preview system set up!"
echo "  Live:    http://159.223.127.125/CarvanaLoanDashBoard/"
echo "  Preview: http://159.223.127.125/CarvanaLoanDashBoard/preview/"
