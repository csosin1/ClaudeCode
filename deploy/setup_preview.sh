#!/bin/bash
# Set up preview system: /preview/ shows candidate, / shows approved live version
# Run once on the server.

mkdir -p /opt/abs-dashboard/carvana_abs/static_site/preview

# Update nginx to serve both live and preview
cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    # Live dashboard (approved version)
    location / {
        alias /opt/abs-dashboard/carvana_abs/static_site/live/;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Preview dashboard (candidate version)
    location /preview/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/preview/;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Games
    location /games/ {
        alias /var/www/games/;
        index index.html;
    }
}
NGXEOF

# Move current index.html to live/
mkdir -p /opt/abs-dashboard/carvana_abs/static_site/live
if [ -f /opt/abs-dashboard/carvana_abs/static_site/index.html ]; then
    cp /opt/abs-dashboard/carvana_abs/static_site/index.html /opt/abs-dashboard/carvana_abs/static_site/live/index.html
fi

nginx -t && systemctl reload nginx
echo "Preview system set up!"
echo "  Live:    http://159.223.127.125/"
echo "  Preview: http://159.223.127.125/preview/"
