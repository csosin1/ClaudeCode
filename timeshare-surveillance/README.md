# Timeshare Surveillance

Automated credit-surveillance pipeline for timeshare receivables at Hilton
Grand Vacations (HGV), Marriott Vacations Worldwide (VAC), and Travel +
Leisure Co. (TNL). Pulls 10-K / 10-Q filings from SEC EDGAR, extracts credit
metrics via Claude, diffs against prior thresholds, and emails alerts on
credit deterioration.

## Components

- `pipeline/fetch_and_parse.py` — pulls filings, runs Claude extraction,
  writes per-filing JSON to `data/raw/`.
- `pipeline/merge.py` — merges raw extracts into `data/combined.json` and
  mirrors to the dashboard's static data dir.
- `pipeline/red_flag_diff.py` — evaluates CRITICAL / WARNING thresholds,
  diffs against prior `flag_state.json`, emits a JSON diff summary.
- `alerts/email_alert.py` — renders HTML email (severity color bar, sections)
  and sends via SMTP STARTTLS on port 587.
- `watcher/edgar_watcher.py` — long-running daemon that polls EDGAR Atom
  feeds every 15 min (staggered 5s between tickers) and triggers the
  pipeline on new accessions.
- `admin/app.py` — Flask setup page (Basic auth via `ADMIN_TOKEN`) for
  pasting API keys / SMTP credentials from a phone.

## Env vars

Populated via the `/admin/` page (writes to `/opt/timeshare-surveillance-{live,preview}/.env`):

| Name | Purpose |
|------|---------|
| `ANTHROPIC_API_KEY` | Claude extraction |
| `SMTP_HOST` | e.g. `smtp.gmail.com` |
| `SMTP_USER` | SMTP account |
| `SMTP_PASSWORD` | App password / SMTP password |
| `ALERT_EMAIL` | Destination address for alerts |
| `ADMIN_TOKEN` | auto-generated on deploy; Basic-auth password |
| `ADMIN_PORT` | 8510 (live) / 8511 (preview) |
| `DASHBOARD_SERVE_DIR` | set by deploy; merge.py mirrors combined.json here |
| `DASHBOARD_URL` | public URL shown in email footer |

## Manual refresh

From the project root (`/opt/timeshare-surveillance-live/`):

```
venv/bin/python pipeline/fetch_and_parse.py --all
venv/bin/python pipeline/merge.py
venv/bin/python pipeline/red_flag_diff.py --force-email | venv/bin/python alerts/email_alert.py --weekly
```

## Dry-run (offline — no network, no Anthropic)

```
venv/bin/python pipeline/fetch_and_parse.py --all --dry-run
venv/bin/python pipeline/merge.py
venv/bin/python pipeline/red_flag_diff.py
```

Populates `data/raw/` with plausible synthetic values for HGV/VAC/TNL so the
dashboard renders during development.

## Admin page

- Live: https://casinv.dev/timeshare-surveillance/admin/
- Preview: https://casinv.dev/timeshare-surveillance/preview/admin/

Basic auth: username `admin`, password = `ADMIN_TOKEN` (written to
`/var/log/timeshare-surveillance/ADMIN_TOKEN_{live,preview}.txt` on first
deploy, chmod 600).

## Unit tests

```
cd /opt/site-deploy/timeshare-surveillance
python -m pytest tests-unit/ -q
```

## Services

- `timeshare-surveillance-watcher.service` / `-preview.service` — EDGAR watcher.
- `timeshare-surveillance-admin.service` / `-preview.service` — Flask admin app.
- Weekly cron: `0 6 * * 0 /opt/timeshare-surveillance-live/watcher/cron_refresh.sh`.

Health check: `curl -sf https://casinv.dev/timeshare-surveillance/ | grep -q Timeshare`
