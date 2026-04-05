# Runbook
Last updated: 2026-04-05

## Droplet
IP: 159.223.127.125
SSH: key-based only
Backups: DigitalOcean automated backups

## Projects

### Landing Page
- URL: http://159.223.127.125/
- Directory: /var/www/landing/
- Process: static (nginx)
- Dependencies: none
- Env vars required: none
- Deploy method: auto-deploy (general-deploy.timer syncs deploy/landing.html → /var/www/landing/index.html)
- Last deployed: 2026-04-05
- Health check: http://159.223.127.125/

### Carvana ABS Loan Dashboard
- URL: http://159.223.127.125/CarvanaLoanDashBoard/
- Directory: /opt/abs-dashboard/carvana_abs/static_site/live/
- Process: static (nginx)
- Dependencies: unknown — has its own separate auto-deploy
- Env vars required: unknown
- Deploy method: separate auto-deploy (not general-deploy)
- Last deployed: unknown
- Health check: http://159.223.127.125/CarvanaLoanDashBoard/

### Carvana Dashboard — Preview
- URL: http://159.223.127.125/CarvanaLoanDashBoard/preview/
- Directory: /opt/abs-dashboard/carvana_abs/static_site/preview/
- Process: static (nginx)
- Dependencies: same as live
- Deploy method: separate auto-deploy
- Health check: http://159.223.127.125/CarvanaLoanDashBoard/preview/

### Games (Static)
- URL: http://159.223.127.125/games/
- Directory: /var/www/games/
- Process: static (nginx)
- Games: banana-blaster, dino-dash, go-yankees, hello-world, sky-barons, snake, spidy-climb
- Dependencies: none (single-file HTML games)
- Env vars required: none
- Deploy method: auto-deploy (general-deploy.timer syncs games/ → /var/www/games/)
- Last deployed: 2026-04-05
- Health check: http://159.223.127.125/games/

## How to Rebuild From Scratch
1. Provision Ubuntu 22.04 LTS droplet on DigitalOcean
2. Install nginx, node, python3
3. Clone repo to /opt/site-deploy/
4. Run deploy/setup_general_deploy.sh to install the auto-deploy timer
5. Run deploy/update_nginx.sh to configure nginx routes
6. Set up /opt/abs-dashboard/ for Carvana dashboard (separate deploy)
7. Run scripts/droplet_setup.sh for observability + nginx hardening
8. Verify all URLs return 200

## nginx
Config location: /etc/nginx/sites-available/abs-dashboard
Reload: sudo systemctl reload nginx
NGINX_VERSION file: deploy/NGINX_VERSION (currently v2)

## Auto-Deploy
- Timer: general-deploy.timer (runs every 30s)
- Script: /opt/auto_deploy_general.sh (copied from deploy/auto_deploy_general.sh)
- Repo clone: /opt/site-deploy/
- Log: /var/log/general-deploy.log
- Watches: main branch only
