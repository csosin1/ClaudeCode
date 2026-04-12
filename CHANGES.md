# Change Log

Builder appends a per-task entry here after each build. Format:

```
## [YYYY-MM-DD] [task name]
- **What was built:**
- **Files modified:**
- **Tests added:**
- **Assumptions:**
- **Things for the reviewer:**
```

## 2026-04-12 — timeshare-surveillance (frontend build)

- **What was built:**
  - `timeshare-surveillance/dashboard/index.html` — single-file React 18 + Recharts 2.12 + Tailwind (all via unpkg CDN) Bloomberg-terminal-style surveillance dashboard. Fetches `./data/combined.json` and renders 8 sections: Header (with latest period, parsed timestamp, active-flag pill), Red-flag panel (CRITICAL-before-WARNING eval, auto-expand + scroll on criticals, plain-English consequence per metric), KPI scorecard (3 ticker cards color-bordered, 8 rows each with QoQ delta + threshold-coloured badge), 2×3 chart grid (Total DPD, 90+ DPD, Coverage, Originations bars, GoS margin, FICO stacked mix) with threshold ReferenceLines, Vintage loss curves (shared x = months since origination assuming Q4 vintage, warns when newest vintage tracks above older at equal age; placeholder if `vintage_pools` all null), Peer comparison table (sortable headers, Δ vs HGV columns), Management commentary (per-ticker cards, red left border + tinted bg when `management_flagged_credit_concerns` true), Footer (EDGAR filing links, plain-text dashboard URL on its own line per CLAUDE.md, relative admin link). Empty/loading states: skeleton shimmer while loading; when `combined.json` is `[]` the header still renders and a placeholder card points to `./admin/`. Network/404 treated same as empty, no chart errors surface.
  - `timeshare-surveillance/admin/templates/setup.html` — Jinja2 template, mobile-first dark form. Inputs: `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_PORT` (optional 587), `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL`. Posts to relative `./save`. Status block at top loops over all six keys and shows ✓/✗ based on `status.set_keys`. Prominent `LIVE`/`PREVIEW` badge next to heading so creds don't land in the wrong instance. Flashes rendered by category. Helper text matches the spec (blank leaves values unchanged, password fields always blank after save).
  - `tests/timeshare-surveillance.spec.ts` — Playwright spec. Iterates `[390×844, 1280×800]`. Tests: dashboard 200 + header text + HGV/VAC/TNL + flags badge; KPI scorecard renders 3 `[data-ticker]`; charts-grid has 6 `[data-chart]`; flag-panel / peer-table / vintages / commentary / footer all visible + footer contains "SEC EDGAR" and the plain dashboard URL; no real console errors (favicon + combined.json 404 filtered — the empty-state path is legitimate when pipeline hasn't run). Also: admin `/admin/` must 401 with `WWW-Authenticate: Basic`; landing page has the `/timeshare-surveillance/` card.

- **Files modified:**
  - `timeshare-surveillance/dashboard/index.html` (new, ~30k)
  - `timeshare-surveillance/admin/templates/setup.html` (new)
  - `tests/timeshare-surveillance.spec.ts` (new)
  - `CHANGES.md` (this entry)

- **Tests added:** See list above. 6 per-viewport dashboard tests × 2 viewports = 12, plus 1 admin 401 test and 1 landing card test.

- **Assumptions:**
  - `combined.json` is an array of records each shaped `{ ticker, period_end (ISO), extracted_at, <metrics>, vintage_pools?: [{ vintage_year, cumulative_default_pct, ... }], management_credit_commentary, management_flagged_credit_concerns }`. Backend Builder owns that schema; this follows the user-provided METRIC_SCHEMA naming verbatim.
  - Vintage age assumes vintages originate at end of Q4 (Dec 31 of `vintage_year`); months-since-origination is computed from each record's `period_end`. If backend later emits explicit `months_seasoned`, swap the helper.
  - CRITICAL thresholds evaluated before WARNING so a single metric only produces one flag row at the highest tripped severity (per spec "CRITICAL before WARNING so a critical triggers only once").
  - Tailwind via `cdn.tailwindcss.com` (same as gym-intelligence/car-offers landing). Arbitrary-value classes (`bg-[#FF3B3B]/10` etc.) used inside pre-compiled `<script>` blocks — tailwind JIT reads the rendered DOM so they resolve at runtime.
  - Admin page 401 is produced by Flask basic-auth (the other Builder's code). This builder only owns the template — the 401 test exists so QA fails loudly if the other Builder's auth gate regresses.

- **Things for the reviewer:**
  - **Recharts UMD access:** destructured once at top of the `type="text/babel"` script — `const { LineChart, Line, … } = Recharts;` — per the spec note. No bare `<LineChart>` usage.
  - **Mobile 390px:** every grid collapses to `grid-cols-1` on `<md`. Header flex wraps. Peer table wrapped in `.scroll-x` for overflow. Verify in the QA screenshots at 390×844.
  - **Empty-state rendering:** `combined.json = []` currently bootstrapped in the repo. The Playwright tests MUST pass in this state — they only assert the presence of testids and 6 chart slots, not chart paths. Placeholders in chart cards say "Awaiting first filing." rather than rendering broken charts.
  - **No JS console errors filter:** excludes `favicon` and `combined.json` — `combined.json` is filtered because a 404 or empty response is an expected first-deploy state. If the Reviewer thinks filtering is too lenient, the fix is to `await fetch` with `cache: 'no-store'` and swallow 404s silently (already done) and drop the filter. Either is fine; the current filter is defensive belt-and-suspenders.
  - **Plain URLs:** dashboard URL and admin URL in the footer are plain text (no markdown) per the CLAUDE.md iOS rule.
  - **Babel preset:** using `data-presets="react"` only (no TS). `<>...</>` fragments used in one place (VintagePanel); Babel standalone supports them.
  - **Scope boundary:** this builder touched only the three files above and this CHANGES.md section. No Python, no deploy scripts, no settings.py, no nginx. Backend Builder owns all of that.

## 2026-04-12 — timeshare-surveillance — backend build

- **What was built:**
  - `config/settings.py` — TARGETS (HGV/VAC/TNL with CIKs), EDGAR_USER_AGENT, EDGAR_RATE_LIMIT_PER_SEC=8, FILING_TYPES, LOOKBACK_FILINGS=12, ANTHROPIC_MODEL=claude-opus-4-5, chunking constants, full THRESHOLDS dict (CRITICAL + WARNING with comparator tuples per metric). Secrets read via `os.environ.get` so import never crashes; `require()` helper raises at call-sites. `missing_secrets()` returns the env var checklist. `BASE_DIR = Path(__file__).parent.parent`.
  - `pipeline/fetch_and_parse.py` — EDGAR submissions-API discovery, rate-limited (8 req/s global + exponential backoff on 429/503, max 30s), primary-doc fetch from `sec.gov/Archives/...`. HTML lightly stripped (scripts/styles/tags) then either passed whole (≤80k tokens) or split into 75k-token overlapping chunks (5k overlap). Claude extraction uses METRIC_SCHEMA (every field in the user spec, including `vintage_pools`, `management_flagged_credit_concerns`, `management_credit_commentary`) + the strict credit-analyst SYSTEM_PROMPT. `_strip_json_fences` + one corrective retry on parse failure; second failure logs `PARSE_ERROR` and writes an all-nulls record with `extraction_error: true`. Multi-chunk merge = first non-null per field. Per-filing record augmented with `ticker`, `filing_type`, `period_end`, `accession`, `filed_date`, `source_url`, `extracted_at`. `--dry-run` (supports both `--ticker X` and `--all`) skips all network/Anthropic calls and writes pre-baked plausible stub extracts for HGV / VAC / TNL into `data/raw/` so the dashboard renders offline. `fixtures/hgv_10q_sample.html` is shipped for completeness (used as reference content in dry-run logs).
  - `pipeline/merge.py` — loads every `data/raw/*.json`, sorts (ticker, period_end) asc, derives `allowance_coverage_pct_qoq_delta`, `new_securitization_advance_rate_qoq`, `originations_mm_yoy_change_pct`, `provision_yoy_change_pct` per ticker sequence. Writes `data/combined.json` atomically. If `DASHBOARD_SERVE_DIR` env var set, also mirrors to `$DASHBOARD_SERVE_DIR/data/combined.json` (deploy script sets this to each instance's `dashboard/` dir so nginx can serve it).
  - `pipeline/red_flag_diff.py` — evaluates THRESHOLDS (CRITICAL checked first; once a metric is CRITICAL it doesn't also get marked WARNING). Compares against prior `data/flag_state.json`, emits NEW / ESCALATED / RESOLVED / UNCHANGED. Prints structured JSON summary to stdout; writes new state. Exit 0 when unchanged, 1 on changes. `--force-email` forces exit 1 and marks `weekly:true`.
  - `alerts/email_alert.py` — reads JSON diff on stdin, renders HTML with severity color bar (CRITICAL #FF3B3B, WARNING #FFB800, RESOLVED #00D48A) and NEW / ESCALATED / RESOLVED / ACTIVE sections. Subject varies per mode (weekly digest vs event-driven). SMTP over port 587 STARTTLS with SMTP_USER/SMTP_PASSWORD. Footer includes `https://casinv.dev/timeshare-surveillance/` (plain) and SEC-source / not-advice disclaimer. Exits 2 when SMTP vars missing so the watcher can log and continue.
  - `watcher/edgar_watcher.py` — long-running loop, 15-min cycles, 5s stagger between tickers. Polls both `type=10-Q` and `type=10-K` Atom feeds per CIK, extracts accession numbers via regex (namespace-tolerant xml.etree), diffs against `data/seen_accessions.json`. First cycle seeds seen-set silently (no false alerts for historical filings); subsequent new accessions subprocess `fetch_and_parse.py --ticker X`, then `merge.py`, then `red_flag_diff.py`; exit 1 pipes summary into `email_alert.py`. Subprocesses launched with `$PYTHON_EXE` (set by the systemd unit). SIGINT/SIGTERM clean shutdown. Logs to stdout + `/var/log/timeshare-surveillance/watcher.log`.
  - `watcher/watcher.service.template` and `watcher/admin.service.template` — systemd unit templates with `__PROJECT_DIR__` / `__VENV__` placeholders. Both set `EnvironmentFile=__PROJECT_DIR__/.env`, `Restart=always`, `RestartSec=10`, `User=root`, stdout/err appended to `/var/log/timeshare-surveillance/{watcher,admin}.log`. Watcher unit also sets `Environment=PYTHON_EXE=__VENV__/bin/python` for subprocess dispatch.
  - `watcher/cron_refresh.sh` — weekly fallback; runs `fetch_and_parse.py --all`, `merge.py`, then `red_flag_diff.py --force-email | email_alert.py --weekly`. Sources `.env` first. Logs to `/var/log/timeshare-surveillance/cron_refresh.log`. Executable.
  - `admin/app.py` — Flask app factory. Routes `/admin/`, `/admin/save`, `/admin/status`. Basic auth via `ADMIN_TOKEN` env (username `admin`, `hmac.compare_digest`). 503 on every endpoint if `ADMIN_TOKEN` is absent. `/save` strips, rejects newline (`\r`/`\n`) and control characters, leaves blank fields untouched, merges submissions onto existing env, writes atomically (`.env.tmp` → `os.replace`), chmod 600. `/admin/` renders `templates/setup.html` (owned by the other Builder) with a `status` dict of `(set)`/`(not set)` flags — never returns plaintext secrets. Logs to `/var/log/timeshare-surveillance/admin.log`. Binds to 127.0.0.1 on port `ADMIN_PORT` (default 8510).
  - `pipeline/requirements.txt` — anthropic>=0.25.0, requests>=2.31.0, python-dateutil>=2.8.0, flask>=3.0.0.
  - Bootstrap data files: `data/combined.json=[]`, `data/flag_state.json={}`, `data/seen_accessions.json={}`, `data/raw/.gitkeep`.
  - `tests-unit/test_red_flag_diff.py` — pytest covering: CRITICAL trigger on high delinquency, WARNING fall-through, no-flag below threshold, NEW flag detection + state write, ESCALATED (WARNING→CRITICAL) + RESOLVED diff categories, `--force-email` always reports changed=True and marks `weekly:true`. Uses `tmp_path` + monkeypatched settings paths so tests don't touch repo data.
  - `README.md` — env var checklist, manual/dry-run commands, service names, admin URLs.
  - `.gitignore` — `.env`, `__pycache__`, `venv/`, `*.pyc`, `data/raw/*.json` (keeps `.gitkeep`), `*.log`.
  - `deploy/timeshare-surveillance.sh` — rsyncs `$REPO_DIR/timeshare-surveillance/` to `/opt/timeshare-surveillance-preview/` (excludes venv/.env/__pycache__/*.pyc/*.log/data/raw/*, preserves `.gitkeep`). Per-instance venv via `python3 -m venv`, installs `pipeline/requirements.txt`, detects re-install via `.deps_installed` sentinel. `.env` bootstrap generates `ADMIN_TOKEN` with `openssl rand -hex 24` (fallback `/dev/urandom | xxd`), writes full template with `ADMIN_PORT`, `DASHBOARD_SERVE_DIR`, `DASHBOARD_URL`, chmod 600, and mirrors the token to `/var/log/timeshare-surveillance/ADMIN_TOKEN_{live,preview}.txt` chmod 600. Live dir bootstrapped from preview on first install (when `pipeline/fetch_and_parse.py` absent). Renders four systemd units from templates (substituting `__PROJECT_DIR__` / `__VENV__`), `daemon-reload`, `enable` all four. Bootstraps live services on first install only; restarts preview services on every deploy. One-time observability: logrotate config, 5-min uptime cron against `http://127.0.0.1/timeshare-surveillance/`, weekly refresh cron against `/opt/timeshare-surveillance-live/watcher/cron_refresh.sh`. `chmod +x cron_refresh.sh` on both instances every deploy.

- **Files modified / created (absolute paths):**
  - `/opt/site-deploy/timeshare-surveillance/config/__init__.py` (new, empty)
  - `/opt/site-deploy/timeshare-surveillance/config/settings.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/__init__.py` (new, empty)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/fetch_and_parse.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/merge.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/red_flag_diff.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/requirements.txt` (new)
  - `/opt/site-deploy/timeshare-surveillance/pipeline/fixtures/hgv_10q_sample.html` (new)
  - `/opt/site-deploy/timeshare-surveillance/watcher/__init__.py` (new, empty)
  - `/opt/site-deploy/timeshare-surveillance/watcher/edgar_watcher.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/watcher/watcher.service.template` (new)
  - `/opt/site-deploy/timeshare-surveillance/watcher/admin.service.template` (new)
  - `/opt/site-deploy/timeshare-surveillance/watcher/cron_refresh.sh` (new, +x)
  - `/opt/site-deploy/timeshare-surveillance/alerts/__init__.py` (new, empty)
  - `/opt/site-deploy/timeshare-surveillance/alerts/email_alert.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/admin/__init__.py` (new, empty)
  - `/opt/site-deploy/timeshare-surveillance/admin/app.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/data/raw/.gitkeep` (new)
  - `/opt/site-deploy/timeshare-surveillance/data/combined.json` (new, `[]`)
  - `/opt/site-deploy/timeshare-surveillance/data/flag_state.json` (new, `{}`)
  - `/opt/site-deploy/timeshare-surveillance/data/seen_accessions.json` (new, `{}`)
  - `/opt/site-deploy/timeshare-surveillance/tests-unit/test_red_flag_diff.py` (new)
  - `/opt/site-deploy/timeshare-surveillance/README.md` (new)
  - `/opt/site-deploy/timeshare-surveillance/.gitignore` (new)
  - `/opt/site-deploy/deploy/timeshare-surveillance.sh` (new, +x)

- **Tests added:** 6 pytest cases in `tests-unit/test_red_flag_diff.py`, all passing locally (`python3 -m pytest tests-unit/ -q` → `6 passed in 0.04s`). Also `py_compile` passes for every Python source file (pipeline/watcher/alerts/admin/config).

- **Dry-run pipeline verification:**
  - `python3 pipeline/fetch_and_parse.py --ticker HGV --dry-run` wrote `data/raw/HGV_10-Q_2025-03-31.json` with the full METRIC_SCHEMA populated (delinquent_90_plus_days_pct=0.062, allowance_coverage_pct=0.11, fico=720, three vintage pools).
  - `python3 pipeline/merge.py` produced a combined.json with 1 record and the four derived delta fields set to `null` (expected for a single record).
  - `python3 pipeline/fetch_and_parse.py --all --dry-run` + merge produced 3 records. `python3 pipeline/red_flag_diff.py` returned exit 1 with `has_changes:true` — correctly flagged HGV/VAC/TNL WARNINGs on 90+-day delinquency and TNL CRITICAL on `management_flagged_credit_concerns`.
  - After verification, `data/raw/*.json`, `data/combined.json`, `data/flag_state.json` reset to empty bootstrap state so nothing committed is polluted with fake data. `.gitkeep` preserved.

- **Assumptions:**
  - CIKs for HGV (0001674168), VAC (0001524358), TNL (0000052827) — zero-padded to 10 digits for the submissions API. Verified against public EDGAR search during scaffolding in earlier task #2.
  - THRESHOLDS dict is my best reproduction of the user spec since that specific block wasn't pasted verbatim into TASK_STATE — chose industry-reasonable defaults (CRITICAL 90+ DPD ≥ 7%, WARNING ≥ 5%, etc.). Reviewer should check these against the original user message if that's still in scope; they live in `config/settings.py` and are easy to tune.
  - Email STARTTLS on port 587 is hard-coded default but `SMTP_PORT` env var allows override.
  - Watcher's first cycle seeds `seen_accessions.json` without firing alerts — prevents a torrent of false alerts on fresh deploy. Reviewer: verify this is acceptable vs spec (spec says "watcher's first run captures new filings going forward" — this matches).
  - Admin `/save` accepts any UTF-8 token for API keys (SMTP passwords may contain `!@#$%`). Only `\n`, `\r`, and control chars 0x00-0x1F (excluding tab/newline already handled) are rejected. This prevents `.env` injection without being overly restrictive.
  - `config/settings.py` reads env vars at import time; restarting the watcher / admin service is required after editing `.env` via the admin page. README documents this.

- **Things for the reviewer:**
  - `settings.py` imports must not crash when env vars are missing — verified: `from config import settings` succeeds in the dry-run path where no `.env` is present. All secret access is via `os.environ.get(...)` defaults; `require("KEY")` is only called inside `process_ticker()` non-dry-run path.
  - EDGAR User-Agent is exactly `"CAS Investment Partners research@casinvestmentpartners.com"` per spec — SEC will reject requests without it.
  - The 8 req/s rate limit is global per-process (not per-ticker), so even though tickers are processed sequentially, back-to-back GETs still space themselves by 125ms. Exponential backoff caps at 30s and tries 6 attempts.
  - Admin app never logs the secrets themselves — only key names ("saved keys: ANTHROPIC_API_KEY,SMTP_USER").
  - Atomic env write: `_write_env` writes `.env.tmp` → `chmod 600` → `os.replace`. No window where `.env` is world-readable.
  - ADMIN_TOKEN is generated on first deploy only (check `[ -f "$env_path" ]`). Re-running the deploy script preserves it. Mirror file `/var/log/timeshare-surveillance/ADMIN_TOKEN_{live,preview}.txt` chmod 600 so orchestrator can `cat` it and notify the user.
  - Watcher subprocess model: each new-filing cycle invokes four separate Python processes (fetch / merge / red_flag / email). This is heavier than a single-process call graph but (a) matches spec, (b) isolates extraction crashes from the watcher loop, (c) keeps imports cheap since Anthropic SDK only loads inside `fetch_and_parse.py` when not in dry-run.
  - `merge.py` mirrors combined.json to `DASHBOARD_SERVE_DIR` — the deploy script sets this to `<instance>/dashboard` so nginx can serve it at `./data/combined.json` relative to the dashboard page (consistent with the frontend builder's expectation).
  - Scope boundary: this builder did NOT modify `dashboard/index.html`, `admin/templates/setup.html`, or `tests/timeshare-surveillance.spec.ts` — all owned by the frontend builder. Also did NOT touch `update_nginx.sh`, `auto_deploy_general.sh`, `landing.html`, or `CLAUDE.md` (already scaffolded in task #2).
