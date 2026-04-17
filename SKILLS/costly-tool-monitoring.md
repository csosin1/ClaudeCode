# Skill: Costly-Tool Monitoring

## When To Use

Any time a project calls a **paid external API** where each call or byte has a real-dollar cost: residential proxies (Decodo, Smartproxy), captcha solvers (CapSolver, 2Captcha), LLM APIs (Anthropic, OpenAI), SMS/voice (Twilio), email (AWS SES), participant panels (Prolific, MTurk), cloud-browser services (Browserbase), paid data APIs, or similar.

This skill is defensive, not advisory: getting it wrong burns real money in the background. We learned the hard way on 2026-04-17 (see LESSONS) when a two-line startup diagnostic using the Decodo proxy burned through credits over multiple service restarts before anyone noticed.

## The four rules

### 1. **No paid API call in a startup diagnostic, ever.**

Startup code runs on every service restart, every deploy, every redeploy cycle. Restarts can happen for reasons you don't control (systemd unit changes, rsync hooks, OOM, manual restarts). If your startup function hits a paid endpoint, each restart is a charge you didn't plan for.

Allowed on startup: curl to free endpoints (`httpbin.org`, `ipinfo.io` free tier), DNS lookups, TCP connectivity tests, parsing local config. **Not** allowed on startup: anything that routes through a paid proxy, any auth'd POST to a rate-metered API, any LLM call.

If a diagnostic *must* hit a paid endpoint, gate it behind a **one-shot sentinel file**: run once on first-ever startup of the service, write `/var/run/<project>-geo-check.done`, don't run again. If the diagnostic result becomes stale, the user explicitly re-runs via a CLI flag or /setup button — not an automatic restart.

### 2. **Every paid-API call site has a hard cap.**

For each service that calls a paid API, the `.env` or /setup page must define `<VENDOR>_HARD_CAP_USD` (per-session or per-day, whichever matches the vendor's billing granularity). The code path that makes the call checks an in-memory or on-disk accumulator before each call and **refuses to call if cumulative spend + next-call cost would exceed the cap**. Failing closed is cheaper than failing open.

Precedent: `car-offers` already has `CAPSOLVER_HARD_CAP_USD` (default $20 per session) — the same pattern should extend to every paid API the project touches.

### 3. **A service that calls paid APIs logs every such call** with a distinguishable prefix, to a file that's persistent across restarts. Example line: `PAID-CALL decodo residential-proxy req=1.2MB est=$0.004 cumulative=$0.47`. This makes retrospective forensics possible — without it, you find out you burned credits only when the vendor's dashboard shows a zero balance.

### 4. **Visibility is non-negotiable.** For every paid vendor you integrate:
   - Register in `account.sh` with the spend-check mechanism: API endpoint, dashboard URL, CLI tool, or — if none of those — a user-action reminder to check manually weekly.
   - Add a row to `https://casinv.dev/tokens.json` or equivalent for the platform-level vendor balance dashboard (one-tap visibility from the user's phone).
   - If the vendor exposes a spend/balance API, a cron polls it hourly and writes to `/var/www/landing/tool-spend.json`; the landing page surfaces `status: OK | APPROACHING_CAP | OVER_CAP`. Alerts fire at 50%/75%/90% of budget.

## Startup-diagnostic anti-pattern (the 2026-04-17 class)

```javascript
// BAD — burns credits on every restart
run('curl_decodo_geo', `curl --proxy ${geoProxyUrl} https://ip.decodo.com/json`);
```

```javascript
// OK — free endpoint, no proxy credits
run('dns_decodo', `dig +short gate.decodo.com`);
run('tcp_decodo',  `nc -z gate.decodo.com 7000`);

// OK — paid call, but only first-ever startup
if (!fs.existsSync('/var/run/car-offers-geo-check.done')) {
  run('curl_decodo_geo_firstrun', `curl --proxy ${geoProxyUrl} https://ip.decodo.com/json`);
  fs.writeFileSync('/var/run/car-offers-geo-check.done', new Date().toISOString());
}
```

The first-run sentinel lives in `/var/run/` (tmpfs — resets on reboot, which is acceptable; if you want it to survive reboots, use `/var/lib/<project>/geo-check.done`). Manual re-run: `rm /var/run/car-offers-geo-check.done && systemctl restart car-offers`.

## Prevention — what reviewers must check

Added to `.claude/agents/infra-reviewer.md` checklist:
- **Costly-tool review**: does this diff add or modify a call to any paid external API? If yes: (a) is the call gated by a hard cap + cumulative accumulator? (b) if the call is in startup code, is it sentinel-gated or demonstrably free? (c) is the call logged with a `PAID-CALL` prefix? Any "no" is a FAIL regardless of what else the diff does.

## Detection — the on-platform telemetry

Per-service: log grep `PAID-CALL` and tally. Platform-wide: `/usr/local/bin/tool-spend-poll.sh` (to be built) runs hourly, hits each registered vendor's spend/balance endpoint, writes the result, and fires ntfy at 50/75/90% thresholds. If a vendor has no API, falls through to "stale data, user must check manually, reminder surfaces at capacity.html."

## Mitigation — when something goes wrong

- **Suspected burn in progress**: stop the suspect service first (`systemctl stop <unit>`), investigate log for `PAID-CALL` pattern, cross-check against vendor dashboard. Do not restart until the burn path is identified and gated.
- **Budget exceeded**: the cap code path should refuse new calls gracefully — the service stays up but degrades to the free fallback or skips the paid step. Not silent failure: it logs `PAID-CALL-BLOCKED <vendor> cap_hit cumulative=$X` and fires ntfy high.
- **Credits exhausted (vendor dashboard shows $0)**: rotate to the backup vendor if configured; otherwise hard-pause the service and ntfy urgent to the user.

## Registry of paid APIs in current use

(Snapshot 2026-04-17. Keep current.)

| Vendor | Project | Env var | Spend-check | Cap |
|---|---|---|---|---|
| Decodo (residential proxy) | car-offers | `PROXY_HOST`, `PROXY_USER`, `PROXY_PASS` | Dashboard at decodo.com (no public API yet — ua-TBD) | No code-level cap yet (GAP) |
| CapSolver (Turnstile) | car-offers | `CAPSOLVER_API_KEY` | `getBalance` API | `CAPSOLVER_HARD_CAP_USD` default $20/session |
| Anthropic API | multiple | `ANTHROPIC_API_KEY` | console.anthropic.com | Token-level; platform budget via Claude Code limits |
| OpenAI (if used) | — | — | — | — |
| Prolific | car-offers | `PROLIFIC_TOKEN` | API GET /me balance | `PROLIFIC_BALANCE_USD` user-declared |
| MTurk | car-offers | `MTURK_ACCESS_KEY_ID`, `MTURK_SECRET_ACCESS_KEY` | `GetAccountBalance` | `MTURK_BALANCE_USD` user-declared |
| AWS SES | car-offers (planned) | AWS creds | `GetSendQuota` | Account-level |
| Twilio | car-offers (planned) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | `GET /2010-04-01/Accounts/{SID}/Balance` | None |

Every GAP row is a pending hardening task.

## Related

- `SKILLS/accounts-registry.md` — every paid API has an account.sh entry
- `SKILLS/secrets.md` — credentials live in .env, never in docs
- `SKILLS/capacity-monitoring.md` — platform-level resource monitoring (distinct from $-spend monitoring)
- `LESSONS.md` 2026-04-17 — the incident that motivated this skill
