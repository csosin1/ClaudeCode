# Migration Inventory — Timeshare Credit Dashboard

_Project slug: `timeshare-dashboard`. Infrastructure slug: `timeshare-surveillance`._
_Generated: 2026-04-16._

## Systemd units (4 total)

| Unit | Description | Path |
|------|-------------|------|
| `timeshare-surveillance-watcher.service` | EDGAR Atom feed poller (live) | `/etc/systemd/system/timeshare-surveillance-watcher.service` |
| `timeshare-surveillance-watcher-preview.service` | EDGAR Atom feed poller (preview) | `/etc/systemd/system/timeshare-surveillance-watcher-preview.service` |
| `timeshare-surveillance-admin.service` | Flask setup page (live, port 8510) | `/etc/systemd/system/timeshare-surveillance-admin.service` |
| `timeshare-surveillance-admin-preview.service` | Flask setup page (preview, port 8511) | `/etc/systemd/system/timeshare-surveillance-admin-preview.service` |

Templates are rendered from source by `deploy/timeshare-surveillance.sh`:
- `timeshare-surveillance/watcher/watcher.service.template`
- `timeshare-surveillance/watcher/admin.service.template`

## nginx location blocks

In `/etc/nginx/sites-available/abs-dashboard` (shared config, lines 97-131):
- `/timeshare-surveillance/` → live static dashboard (`/opt/timeshare-surveillance-live/dashboard/`)
- `/timeshare-surveillance/preview/` → preview static dashboard (`/opt/timeshare-surveillance-preview/dashboard/`)
- `/timeshare-surveillance/admin/` → proxy to `127.0.0.1:8510` (live Flask admin)
- `/timeshare-surveillance/preview/admin/` → proxy to `127.0.0.1:8511` (preview Flask admin)

Note: the nginx config is managed by `deploy/update_nginx.sh` and version-controlled via `deploy/NGINX_VERSION`.

## Cron entries

```
*/5 * * * * curl -sf http://127.0.0.1/timeshare-surveillance/ > /dev/null || echo "$(date) DOWN timeshare" >> /var/log/timeshare-surveillance/uptime.log
0 6 * * 0 /opt/timeshare-surveillance-live/watcher/cron_refresh.sh
```

## Log directories + logrotate

- `/var/log/timeshare-surveillance/` (2.5 MB total, 8 log files)
- Logrotate: `/etc/logrotate.d/timeshare-surveillance` (weekly, 4 rotations, compressed)
- ADMIN_TOKEN mirror files: `/var/log/timeshare-surveillance/ADMIN_TOKEN_{live,preview}.txt` (chmod 600)

## SQLite / database files

| Path | Size | Notes |
|------|------|-------|
| `/opt/timeshare-surveillance-preview/data/surveillance.db` | 299 KB | Main extraction DB. WAL mode. rsync must include `-wal` and `-shm` if present. |

Live instance has no DB (never promoted).

## Static assets served from disk

| Path | Size | Notes |
|------|------|-------|
| `/opt/timeshare-surveillance-preview/dashboard/` | 244 KB | Single `index.html` + `data/combined.json` |
| `/opt/timeshare-surveillance-live/dashboard/` | 64 KB | Stale (never promoted from preview) |

## Disk caches (important for rsync — saves $5+ of re-extraction per run)

| Path | Size | Notes |
|------|------|-------|
| `/opt/timeshare-surveillance-preview/data/sec_cache/` | 33 MB | Gzipped SEC filings (96 .html.gz) + 3 companyfacts JSON + 3 submissions JSON. Immutable except for TTL-refreshed xbrl/submissions. |
| `/opt/timeshare-surveillance-live/data/sec_cache/` | 4 KB | Empty (never used) |

## Data files to rsync (total ~33 MB for preview)

```
/opt/timeshare-surveillance-preview/data/
  surveillance.db          299 KB    (+ any -wal/-shm)
  combined.json            340 KB
  sec_cache/               33 MB     (gzipped SEC filings, companyfacts, submissions)
  seen_accessions.json     4 KB
  flag_state.json          4 KB
  raw/                     16 KB     (legacy, negligible)
```

## Python venvs (can be rebuilt from requirements.txt instead of rsynced)

| Path | Size |
|------|------|
| `/opt/timeshare-surveillance-preview/venv/` | 60 MB |
| `/opt/timeshare-surveillance-live/venv/` | 46 MB |

Rebuilding: `python3 -m venv /opt/timeshare-surveillance-preview/venv && /opt/timeshare-surveillance-preview/venv/bin/pip install -r /opt/site-deploy/timeshare-surveillance/pipeline/requirements.txt`

## .env files (secrets — NOT in git)

| Path | Env vars |
|------|----------|
| `/opt/timeshare-surveillance-preview/.env` | `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL`, `ADMIN_TOKEN`, `ADMIN_PORT`, `INSTANCE_LABEL`, `DASHBOARD_SERVE_DIR`, `DASHBOARD_URL` |
| `/opt/timeshare-surveillance-live/.env` | Same vars |

Note: SMTP vars are currently empty (user-action ua-7378631 filed for setup). ANTHROPIC_API_KEY is populated.

## External API dependencies (for firewall sizing)

| Service | Endpoint | Protocol | Notes |
|---------|----------|----------|-------|
| SEC EDGAR | `data.sec.gov`, `www.sec.gov`, `efts.sec.gov` | HTTPS (443) | Rate-limited to 8 req/s. User-Agent header required. |
| Anthropic API | `api.anthropic.com` | HTTPS (443) | For Claude-based narrative extraction. Usage-based billing. |
| Gmail SMTP | `smtp.gmail.com:587` | STARTTLS (587) | For weekly alert emails. Not yet configured. |

## Ports used

| Port | Service |
|------|---------|
| 8510 | Flask admin (live) |
| 8511 | Flask admin (preview) |

## Migration checklist (specific to this project)

1. rsync `/opt/timeshare-surveillance-{preview,live}/` excluding `venv/` and `__pycache__/`
2. rsync `.env` files separately (chmod 600)
3. Rebuild venvs from requirements.txt (faster than rsyncing 106 MB of .so files across architectures)
4. Re-render systemd units via `deploy/timeshare-surveillance.sh` (templates adjust paths)
5. Reload nginx after `deploy/update_nginx.sh`
6. Restore cron entries (or let deploy script recreate on first push)
7. Verify: `curl -sf https://casinv.dev/timeshare-surveillance/ | grep -q Timeshare`
