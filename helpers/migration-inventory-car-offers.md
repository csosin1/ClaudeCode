# Migration Inventory — Car Offers

## Systemd units
- `car-offers.service` — LIVE, port 3100, WorkingDirectory=/opt/car-offers, ExecStart=node server.js
- `car-offers-preview.service` — PREVIEW, port 3101, WorkingDirectory=/opt/car-offers-preview, ExecStart=node server.js
- `xvfb.service` — shared Xvfb :99 (used by car-offers + any headed-Chromium project), ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
- Override file: `/etc/systemd/system/car-offers-preview.service.d/override.conf` (sets SKIP_STARTUP_AUTORUN=1, suppresses boot-time Carvana auto-run while wizards are being debugged)

## nginx location blocks
File: `/etc/nginx/sites-available/abs-dashboard` (shared config)
- `location = /car-offers { return 301 /car-offers/; }`
- `location /car-offers/preview/ { proxy_pass http://127.0.0.1:3101/; ... }`
- `location /car-offers/ { proxy_pass http://127.0.0.1:3100/; ... }`
Both have proxy_http_version 1.1, proxy_read_timeout 180s, standard X-Real-IP/X-Forwarded-For headers.

## Cron entries (in root crontab)
```
# Uptime check (duplicated — should be deduped on migration)
*/5 * * * * curl -sf http://159.223.127.125/car-offers/ > /dev/null || echo "$(date) DOWN" >> /var/log/car-offers/uptime.log

# DB backup (10-min, 7-day retention)
*/10 * * * * cp /opt/car-offers-preview/offers.db /opt/car-offers-data/db-backups/offers-backup-$(date -u +\%Y\%m\%d-\%H\%M).db 2>/dev/null && find /opt/car-offers-data/db-backups/ -mtime +7 -delete 2>/dev/null

# Panel hourly cron (fires on LIVE only; currently no-op since panel isn't producing data yet)
0 * * * * curl -sf -X POST http://127.0.0.1:3100/api/panel/run > /dev/null 2>&1
```

## /var/log directories + logrotate
- `/var/log/car-offers/` — 560 KB (uptime.log, error.log, car-offers.log, car-offers-preview.log)
- Logrotate config: `/etc/logrotate.d/car-offers` (weekly, rotate 4, compress)

## SQLite/DB files (need rsync during migration)
- `/opt/car-offers-preview/offers.db` — 52 KB (6 CarMax offers, consumers table with 29 rows, panel_runs table). **This is the canonical data store.** journal_mode=DELETE, synchronous=FULL.
- `/opt/car-offers/offers.db` — 0 bytes (live instance, never populated because live hasn't been promoted since panel was built)
- `/opt/car-offers-data/db-backups/` — 17 MB (rolling 10-min snapshots, 7-day retention)

## Runtime directories (NOT in git, need rsync)
- `/opt/car-offers/` — live runtime (node_modules, .env, .chrome-profile, startup-results.json). ~200 MB.
- `/opt/car-offers-preview/` — preview runtime (node_modules, .env, .chrome-profiles/, offers.db, public-debug/). ~250 MB.
- `/opt/car-offers-data/` — DB backups only. 17 MB.
- `/opt/site-deploy/car-offers/llm-nav/` — LLM-nav harness (run_site.py, vin_enrich.py, capsolver.py, knowledge/*.md, enrichment/*.json, logs/). ~500 MB total but most is .venv (~400 MB) which can be recreated. Actual code + data ~60 MB.

## .env location + var names (NOT values)
Both `/opt/car-offers/.env` and `/opt/car-offers-preview/.env` contain:
```
PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS
PROJECT_EMAIL
PORT
PROLIFIC_TOKEN, PROLIFIC_BALANCE_USD
MTURK_ACCESS_KEY_ID, MTURK_SECRET_ACCESS_KEY, MTURK_BALANCE_USD
HUMANLOOP_DAILY_CAP_USD
```
(CAPSOLVER_API_KEY, TWILIO_*, CLOUDFLARE_TOKEN not yet provisioned — placeholders for future)

## External API dependencies (firewall / network needs)
- **Decodo residential proxy**: gate.decodo.com port 10001 (outbound HTTPS via proxy; Chromium connects here)
- **Anthropic API**: api.anthropic.com (LLM calls from browser-use harness + future humanloop)
- **NHTSA vPIC**: vpic.nhtsa.dot.gov (VIN decode, free, no auth)
- **NHTSA Recalls**: api.nhtsa.gov (recalls lookup, free, no auth)
- **EPA fuel economy**: fueleconomy.gov (MPG data, free, no auth)
- **GitHub**: github.com (git push/pull, webhook deploy)
- **Carvana**: www.carvana.com (target site — Chromium via proxy)
- **CarMax**: www.carmax.com (target site — Chromium via proxy)
- **Driveway**: www.driveway.com (target site — Chromium via proxy)
- **CapSolver** (future): api.capsolver.com (Turnstile solver, pending signup)
- **Prolific** (future): api.prolific.com (human-loop, pending token)
- **AWS MTurk** (future): mturk-requester.us-east-1.amazonaws.com (crowd tasks, pending funding)

## Packages / dependencies
- **Node.js 22.x** — main service runtime
- **Python 3.12** — LLM-nav harness + VIN enrichment
- **Chromium** (Patchright-installed) — at `/root/.cache/ms-playwright/chromium-1217/` (~400 MB)
- **Xvfb** — apt package `xvfb`
- **Microsoft core fonts** — `ttf-mscorefonts-installer` (for fingerprint realism)
- **better-sqlite3** — npm native module (needs build tools on install)
- **@aws-sdk/client-mturk** — npm (for future MTurk integration)
- **browser-use** — pip (Python, in llm-nav/.venv)

## Unmerged branches on origin (can be cleaned up post-migration)
Most are stale from prior builder iterations. Only `claude/car-offers-llm-nav-harness` has WIP worth keeping (knowledge files + persona SKILLS). All others' meaningful work was already cherry-picked to main.

## Known cleanup items for migration
1. Deduplicate the uptime-check cron (appears twice in root crontab).
2. Live offers.db is 0 bytes — once panel is working, promote preview → live and this populates.
3. The override.conf (SKIP_STARTUP_AUTORUN) should be carried to new droplet if wizards are still being debugged; remove once stable.
4. llm-nav/.venv (~400 MB) is recreatable via `python3 -m venv .venv && pip install browser-use openpyxl pandas` — can be excluded from rsync and rebuilt on target.
5. `car-offers/llm-nav/profiles/` was purged during memory hygiene but will regrow on next LLM-nav run. Exclude from rsync.
