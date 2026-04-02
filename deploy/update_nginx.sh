#!/bin/bash
# Update nginx to serve static dashboard
cat > /etc/nginx/sites-available/abs-dashboard << 'NGXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    # Static dashboard (instant load)
    location / {
        alias /opt/abs-dashboard/carvana_abs/static_site/;
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

nginx -t && systemctl reload nginx
echo "Nginx updated — serving static dashboard."
