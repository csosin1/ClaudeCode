---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Security Baseline

## When To Use

Before shipping anything user-facing. Before any auth, payment, data-exposure, or inbound-request handling. As the Reviewer subagent's mandatory checklist.

## The Baseline

These are non-negotiable. Failing any of these is a Reviewer FAIL.

- **Sanitize user input.** No string-concat into shell commands or SQL. Use parameterized queries, `subprocess.run([...])` lists (never `shell=True` with user data), and proper escape layers.
- **Dependency audit after adding deps.** `npm audit` / `pip-audit` runs on add; block on high/critical. Do not waive without a LESSONS.md note explaining why.
- **No custom auth.** Auth0, Clerk, or Supabase Auth only. HTTPS (Let's Encrypt) before any login ships.
- **Stripe for payments.** Checkout or Payment Links only — never custom card forms. Verify webhook signatures with the Stripe SDK, not by hand.
- **Row-level scoping on user-data queries.** A missing `WHERE user_id=…` is a critical failure. Code review checks this explicitly.
- **Firewall:** 80, 443, 22 only. Root SSH disabled, key auth only.
- **Secrets** per `SKILLS/secrets.md`.

## Reviewer Subagent Hook

The Reviewer reads this list before approving any PR. A PR that:
- Adds a new endpoint that handles POST without CSRF / auth,
- Adds a SQL query without parameterization,
- Introduces a new dep without `audit` output,
- Commits a `.env` or file matching credential patterns,

gets FAIL with the specific line and rule number violated.

## Common Omissions

- **No rate limiting** on public endpoints that hit an external API or DB. Add at nginx (`limit_req_zone`) or at the app layer.
- **Error messages leaking internals.** User-facing errors should be generic; detail goes to logs with a correlation ID.
- **Missing CSRF** on state-changing forms when sessions are cookie-based.
- **Assuming HTTPS** without HSTS on the response.
- **Logs containing PII or credentials.** Redact before writing.

## Integration

- `SKILLS/secrets.md` — secrets-specific rules.
- `SKILLS/accounts-registry.md` — every auth provider / payment processor gets registered.
- `SKILLS/root-cause-analysis.md` — security incidents always get RCA + LESSONS.md; preventive rules go into this skill file.
