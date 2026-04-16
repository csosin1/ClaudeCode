# abs-dashboard — project-specific rules

_Master rules at /root/.claude/CLAUDE.md + /opt/site-deploy/SKILLS/ apply globally. This file adds only what's unique to this project._

## Runtime
- **Python venv: `/opt/abs-venv/`** (shared across projects, not owned by us). `/opt/abs-venv/bin/python` for all scripts.
- Live URL: https://casinv.dev/CarvanaLoanDashBoard/
- Deploy branch (auto-deploys via webhook): `claude/carvana-loan-dashboard-4QMPM`
- Daily ingest cron: **14:17 UTC** (`deploy/cron_ingest.sh`) — pulls new filings, rebuilds summaries, re-exports dashboard.db, reruns model, regenerates + promotes preview→live.

## Data architecture
Source of truth → DB → read-replica → rendered site:
1. **SEC EDGAR** (10-D servicer certs for pool-level, ABS-EE XML for loan-level)
2. → Parsed into `carvana_abs/db/carvana_abs.db` (3.6 GB) and `carmax_abs/db/carmax_abs.db` (29 GB) — authoritative
3. → `export_dashboard_db.py` produces lean `dashboard.db` (read-only slice for the renderer)
4. → `generate_preview.py` renders static HTML → `static_site/preview/` → `promote` → `static_site/live/` → served by nginx

**Rule:** never edit `dashboard.db` directly; it's regenerable in ~30 sec from the source DBs. Source DBs are precious (6 hr Carvana / 7 hr CarMax to rebuild from EDGAR, rate-limited).

## Deal-naming conventions
- **Carvana Prime:** `YYYY-P1..P4` (e.g. `2022-P1`, `2024-P3`)
- **Carvana Non-Prime:** `YYYY-N1..N4` — treat as separate credit tier. Has its own Markov model.
- **CarMax:** `YYYY-1..4` (no P/N suffix; all prime-ish). 12 deals from 2014-2016 are pre-Reg-AB-II → pool-level only, never loan-level.

## Filing cache
- Gzip-compressed HTML certs in `<issuer>_abs/filing_cache/*.gz`. Transparent reads via `edgar_client.py`.
- **XML loan-level cache was intentionally deleted** to free disk. Re-downloadable from EDGAR but rate-limited (hours).

## Known source-faithful data quirks (not bugs — real issuer behavior)
- CarMax 2014-2015 certs genuinely lack 5 columns: `recoveries`, `cumulative_gross_losses`, `cumulative_liquidation_proceeds`, `delinquent_121_plus_balance/count`, `delinquency_trigger_actual`. NULL in these cells is correct.
- Carvana "liquidation_proceeds" is net of liquidation-expenses per issuer formula, so early-cycle months can legitimately be negative and `net > gross` can hold. Relaxed invariant: `cum_net ≤ cum_gross + |cum_liq_proceeds|`.
- 80 rows across ~38 deals have servicer-restated cumulative_net_losses (legit, not parser bug). Dashboard shows restatement markers + monotone envelope.

## Sort / query gotchas
- **Always use `dist_date_iso` (not `distribution_date` text) for chronological ordering.** The raw text field is `M/D/YYYY` and lex-sorts wrong (`'9/12/2022' > '9/10/2025'`). Any `ORDER BY distribution_date DESC LIMIT 1` query is a silent-staleness bug. Fixed repo-wide in commit 1037f00 but be vigilant on new queries.

## Memory discipline
- 4 GB droplet; ~1-1.5 GB headroom at best (other tenants eat 2+ GB). Any batch operation on loan-level data MUST stream. `loan_performance` has 99M rows — never load into pandas. Use chunked cursor iteration. Per-deal chunks in Markov training: 5 deals/chunk keeps peak RSS < 1 GB.
- If launching a job expected to run >15 min, use systemd-run + heartbeat + watchdog per SKILLS/long-running-jobs.md. Never `nohup bash &` for multi-hour work.

## External deps
- SEC EDGAR (rate-limited 10 req/sec, requires `SEC_USER_AGENT` env var — set to `"Clifford Sosin clifford.sosin@casinvestmentpartners.com"`).
- Cloudflare API for cache-purge (pending user-action ua-3eba7411; currently `?v=N` cache-bust workaround).

## Audit trail
- `AUDIT_FINDINGS.md` is the canonical log of every data-quality issue found + fix commit. Always append, never overwrite.
- `PROJECT_STATE.md` has current focus + resume playbook; keep it current per session-resilience rule.
