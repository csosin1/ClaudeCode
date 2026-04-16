# Migration Inventory — Gym Intelligence

_Generated 2026-04-16 by Gym Intelligence session._

## Systemd units

| Unit | Description | Port | Working dir |
|---|---|---|---|
| `gym-intelligence.service` | Flask app — LIVE | 8502 | `/opt/gym-intelligence` |
| `gym-intelligence-preview.service` | Flask app — PREVIEW | 8503 | `/opt/gym-intelligence-preview` |

Unit files: `/etc/systemd/system/gym-intelligence.service` and `gym-intelligence-preview.service`.
Written by `deploy/gym-intelligence.sh` on every deploy.

## nginx location blocks

In `deploy/update_nginx.sh` lines 82–96:

```
location = /gym-intelligence       → 301 /gym-intelligence/
location = /gym-intelligence/preview → 301 /gym-intelligence/preview/
location /gym-intelligence/preview/  → proxy_pass http://127.0.0.1:8503/gym-intelligence/preview/
location /gym-intelligence/          → proxy_pass http://127.0.0.1:8502/gym-intelligence/
```

Both include proxy headers (Host, X-Real-IP, X-Forwarded-For/Proto).

## Cron entries

None. No scheduler cron configured for gym-intelligence. The APScheduler in `scheduler.py` is a quarterly run invoked manually, not via crontab.

## Logs

| Path | Size | Note |
|---|---|---|
| `/var/log/gym-intelligence/` | 7.6 MB total | app.log, collection.log, classify-ge4.log, preview.log, service stdout logs |

Logrotate config: `/etc/logrotate.d/gym-intelligence` — weekly, rotate 4, compress.

## Database files (need rsync during migration)

| Path | Size | Note |
|---|---|---|
| `/opt/gym-intelligence/gyms.db` | 23 MB | Live DB — present-day locations + chains + snapshots (17 quarters of OHSOME backfill) |
| `/opt/gym-intelligence-preview/gyms.db` | 58 MB | Preview DB — same schema, has the full 17-quarter OHSOME backfill + ownership + reclassified chains |
| `/opt/gym-intelligence/gyms.db.pre-promote-20260414-050012.gz` | 6.9 MB | Pre-promote backup (gzipped). Safe to discard if disk is tight. |

**Note:** Preview DB has materially more data than live (OHSOME backfill ran on preview, not promoted to live). The preview DB is the more valuable artifact.

## Static assets served from disk

| Path | Total size | Note |
|---|---|---|
| `/opt/gym-intelligence/` | 96 MB | Live runtime (code + venv + DB) |
| `/opt/gym-intelligence-preview/` | 180 MB | Preview runtime (code + venv + DB + writeup) |

Venvs: 66 MB (live, post-orphan-purge), 123 MB (preview, has extra deps: markdown + weasyprint for thesis PDF).

The writeup directory (`writeup/thesis.md` + `writeup/data/*.json`) lives in source at `/opt/site-deploy/gym-intelligence/writeup/` and is rsynced to preview. ~100 KB total.

## .env location + env var names

| Path | Vars |
|---|---|
| `/opt/gym-intelligence/.env` | `ANTHROPIC_API_KEY` |
| `/opt/gym-intelligence-preview/.env` | `ANTHROPIC_API_KEY` |

Both are 127 bytes, same key. Created by `deploy/gym-intelligence.sh` if missing (empty template).

## External API dependencies

| Service | Protocol | Endpoint | Used for |
|---|---|---|---|
| Anthropic API | HTTPS | `api.anthropic.com` | Chain classification + Wayback HTML extraction |
| OpenStreetMap Overpass | HTTPS | `overpass-api.de`, `lz4.overpass-api.de`, `z.overpass-api.de` | Present-day gym collection |
| OHSOME API | HTTPS | `api.ohsome.org` | Historical OSM data (quarterly backfill) |
| Wayback Machine | HTTPS | `web.archive.org` | Validation of OHSOME accuracy (CDX API + archived HTML) |

All outbound HTTPS (port 443). No inbound connections beyond nginx proxy on 8502/8503. No private-networking dependencies.

## Deploy script

`/opt/site-deploy/deploy/gym-intelligence.sh` — rsyncs source to preview, manages venvs, writes systemd units, runs DB repair/migration, restarts preview service. Triggered by general auto-deploy on every push to main.

Promote: `deploy/promote.sh gym-intelligence` — rsyncs preview code to live (excludes venv, .env, *.db, __pycache__), restarts live service.

## Rollback tags

Latest: `rollback-gym-20260414-045932`. Pre-promote DB backup at path listed above.

## Known issues for migration

1. **Preview DB is the valuable one.** Live DB missed the reclassification + ownership + OHSOME backfill data that's in preview. If migrating only live, you'd lose the 17-quarter backfill. Migrate preview DB alongside live.
2. **weasyprint in preview venv** has system-level deps: `libcairo2`, `libpango-1.0-0`, `libpangocairo-1.0-0`. The new droplet needs these apt packages for the `/thesis.pdf` endpoint.
3. **No cron to restore** — the uptime-check cron mentioned in the New Project Checklist was never set up. Low priority.
