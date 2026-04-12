## Current Task
Name:              timeshare-surveillance (initial build)
Status:            building
Spec approved:     yes (user-provided detailed spec, 2026-04-12)
Rollback tag:      n/a (new project, no prior live)
Branch:            claude/timeshare-surveillance-build-edgar-credit-surveillance-pipeline
Resume hint:       Read CLAUDE.md, LESSONS.md, RUNBOOK.md, then this file's Spec section before starting.

## Spec

**Goal:** Production credit surveillance system for timeshare receivables (HGV, VAC, TNL). Three layers: SEC EDGAR data pipeline, auto-update watcher daemon, and a Bloomberg-terminal-style React dashboard.

**Success criteria (what Playwright/QA verifies on preview):**
- https://casinv.dev/timeshare-surveillance/preview/ returns 200 at 390px and 1280px.
- Dashboard header shows "Timeshare Receivable Surveillance" and "HGV · VAC · TNL".
- KPI scorecard has 3 columns (HGV, VAC, TNL).
- Red-flag panel renders (empty state allowed when no data yet).
- All 6 charts render without JS console errors.
- Admin setup page at /timeshare-surveillance/preview/admin/ loads, has fields for SMTP_HOST, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL, ANTHROPIC_API_KEY, is protected by ADMIN_TOKEN basic auth, and writes to the preview `.env`.
- Landing page (http://159.223.127.125/) has the Timeshare Surveillance card and it returns 200.
- Pipeline unit test: running `pipeline/fetch_and_parse.py --ticker HGV --dry-run` uses a bundled fixture HTML and writes a valid JSON extract to `data/raw/` (no network needed for the test — fixture mode only).
- `pipeline/red_flag_diff.py` with fixture data returns correct NEW/ESCALATED/RESOLVED diff state.

### File layout (inside site-deploy repo, under `timeshare-surveillance/`)
```
timeshare-surveillance/
├── config/settings.py
├── pipeline/
│   ├── fetch_and_parse.py        # supports --ticker, --dry-run (fixture)
│   ├── merge.py
│   ├── red_flag_diff.py
│   ├── fixtures/hgv_10q_sample.html   # small fake filing for offline testing
│   └── requirements.txt
├── watcher/
│   ├── edgar_watcher.py
│   ├── watcher.service.template
│   ├── admin.service.template
│   └── cron_refresh.sh
├── alerts/email_alert.py
├── admin/
│   ├── app.py                    # Flask /setup page, basic auth via ADMIN_TOKEN
│   └── templates/setup.html      # mobile-first form
├── dashboard/index.html          # self-contained React + Recharts + Tailwind CDN
├── data/
│   ├── raw/                      # gitkeep
│   ├── combined.json             # empty array at bootstrap
│   └── flag_state.json           # empty object at bootstrap
├── deploy/nginx-snippet.conf     # reference only; real nginx is in site-deploy/deploy/update_nginx.sh
├── tests-unit/                   # pytest for pipeline/red_flag_diff
│   └── test_red_flag_diff.py
└── README.md
```

Deploy script location (NOT under timeshare-surveillance/ — sourced by main deploy):
```
/opt/site-deploy/deploy/timeshare-surveillance.sh
```

Playwright spec location:
```
/opt/site-deploy/tests/timeshare-surveillance.spec.ts
```

### Site-deploy adaptations vs. the user-provided spec
- Replace standalone `install.sh` with `deploy/timeshare-surveillance.sh` that follows the gym-intelligence / car-offers pattern: rsync to `/opt/timeshare-surveillance-{live,preview}/`, per-instance venv, write systemd units, restart preview only.
- Dashboard served by nginx as static (no Flask-served setup page on same port). Admin lives on a separate Flask process bound to 127.0.0.1:8510 (live) / 8511 (preview), proxied under `/timeshare-surveillance/admin/` and `/timeshare-surveillance/preview/admin/`.
- Two systemd units per instance: `timeshare-surveillance-watcher{,-preview}.service` and `timeshare-surveillance-admin{,-preview}.service`.
- `.env` lives in `/opt/timeshare-surveillance-{live,preview}/.env` — deploy script creates it with empty template on first install. User fills via the admin setup page.
- `ADMIN_TOKEN` — randomly generated on first install and written to both `.env` and `/var/log/timeshare-surveillance/ADMIN_TOKEN.txt` (chmod 600) so the orchestrator can retrieve it and send via notify.sh. Basic-auth gate on the admin page.
- Combined.json served to dashboard at relative path `./data/combined.json` (dashboard lives under `dashboard/`, pipeline writes into sibling `data/` dir; rsync includes data dir so nginx can serve it at `/timeshare-surveillance/preview/data/combined.json`).

### Non-goals (explicit)
- No HTTPS management in this task (casinv.dev already has Let's Encrypt via certbot — update_nginx.sh handles it).
- No auth beyond the ADMIN_TOKEN basic auth on /admin/. Dashboard is public (read-only research tool).
- No database — flat-file JSON is sufficient for this dataset.
- No historical backfill on first deploy — watcher's first run captures new filings going forward; the manual `fetch_and_parse.py` without `--dry-run` is what pulls history when creds are configured.

### Reference: user-provided spec

See the full original spec in this session's history. Key excerpts codified above. The user-provided metrics list (METRIC_SCHEMA), THRESHOLDS dict, chart list (6 charts + vintage + peer table + management commentary), EDGAR config (8 req/s, LOOKBACK_FILINGS=12), Claude extraction system prompt, and email alert format are all authoritative — the builder must reproduce them exactly.

## Builder Output
(pending)

## Reviewer Verdict
(pending)

## QA Result
(pending)

## Blockers
None at build time. After deploy, user must paste SMTP credentials + ANTHROPIC_API_KEY into the /admin/ setup page before the watcher can run productively. Dashboard renders empty-state without them.
