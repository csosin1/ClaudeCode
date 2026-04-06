# Runbook
Last updated: 2026-04-06

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
- Deploy method: auto-deploy (syncs deploy/landing.html → /var/www/landing/index.html)
- Last deployed: 2026-04-06
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

### Carvana Hub
- URL: http://159.223.127.125/carvana/
- Directory: /var/www/carvana/
- Process: static (nginx)
- Dependencies: none
- Deploy method: auto-deploy (syncs carvana/ → /var/www/carvana/)
- Last deployed: 2026-04-06
- Health check: http://159.223.127.125/carvana/

### Car Offer Comparison Tool
- URL: http://159.223.127.125/car-offers/
- Directory: /opt/car-offers/
- Process: systemd (car-offers.service → node server.js on port 3100)
- Dependencies: playwright-extra, puppeteer-extra-plugin-stealth, dotenv, express
- Env vars required: PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, PROJECT_EMAIL, PORT
- Deploy method: auto-deploy (deploy/car-offers.sh — project-owned)
- Last deployed: 2026-04-06
- Health check: http://159.223.127.125/car-offers/

### Gym Intelligence
- URL: http://159.223.127.125/gym-intelligence/
- Directory: /opt/gym-intelligence/
- Process: systemd (gym-intelligence.service → Flask app.py on port 8502)
- Dependencies: flask, anthropic, httpx, thefuzz
- Env vars required: ANTHROPIC_API_KEY
- Deploy method: auto-deploy (deploy/gym-intelligence.sh — project-owned)
- Last deployed: 2026-04-06
- Health check: http://159.223.127.125/gym-intelligence/

### Games (Static)
- URL: http://159.223.127.125/games/
- Directory: /var/www/games/
- Process: static (nginx)
- Games: banana-blaster, button-test, dice-roller, dino-dash, sky-barons, snake, spidy-climb
- Dependencies: none (single-file HTML games)
- Env vars required: none
- Deploy method: auto-deploy (syncs games/ → /var/www/games/)
- Last deployed: 2026-04-06
- Health check: http://159.223.127.125/games/

## How to Rebuild From Scratch
1. Provision Ubuntu 22.04 LTS droplet on DigitalOcean
2. Install nginx, node 22, python3
3. Clone repo to /opt/site-deploy/
4. Copy deploy/auto_deploy_general.sh to /opt/auto_deploy_general.sh
5. Set up systemd timer or cron to run /opt/auto_deploy_general.sh every 5 min
6. Set up webhook listener (webhook_deploy.py) on port 9000
7. Run deploy/update_nginx.sh to configure nginx routes
8. Push to main to trigger first deploy (installs deps, creates services)
9. Push again after deps install to start services (two-deploy rule)
10. Verify all URLs return 200

## nginx
Config location: /etc/nginx/sites-available/abs-dashboard
Reload: sudo systemctl reload nginx
NGINX_VERSION file: deploy/NGINX_VERSION (currently v5)

## Auto-Deploy
- **Primary:** GitHub webhook → nginx → Python listener on 127.0.0.1:9000 → instant deploy (2-3s)
- **Fallback:** timer runs every 5 min
- Main script: /opt/auto_deploy_general.sh (copied from deploy/auto_deploy_general.sh)
- Project scripts: deploy/car-offers.sh, deploy/gym-intelligence.sh (sourced by main script)
- Webhook listener: /opt/webhook_deploy.py (systemd: webhook-deploy.service)
- Webhook secret: /opt/.webhook_secret (chmod 600)
- Repo clone: /opt/site-deploy/
- Deploy log: /var/log/general-deploy.log
- Webhook log: /var/log/webhook-deploy.log
- Watches: main branch only

## Server Check
- Post `/check` on GitHub issue #4 to run diagnostics without pushing
- Or trigger "Server Check" workflow from GitHub Actions UI
- Results posted as issue comment within ~30s
- status.json available at http://159.223.127.125/status.json (updated on every deploy)

## Automated QA
- Trigger: every push to main (GitHub Actions)
- Workflow: .github/workflows/qa.yml
- Tests: tests/qa-smoke.spec.ts (Playwright)
- Viewports: 390px mobile, 1280px desktop
- Results: GitHub Actions tab, screenshots as artifacts
- Covers: page loads, link integrity, JS errors, security, performance, service health
