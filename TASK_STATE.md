## Current Task
Name:              Goal 1 — One Carvana Offer, End-to-End
CLAUDE.md version: 1.0
Status:            deploying
Spec approved:     yes
Rollback tag:      (set before merge to main)

## Spec
Get one real Carvana offer for a 2022 Honda Accord Touring (VIN 1HGCV2F9XNA008352), zip 06880, ~48k miles. Playwright automates the sell-my-car flow. Express server lets user trigger from iPhone.

## Builder Output
- car-offers/package.json — deps: playwright-extra, stealth plugin, dotenv, express
- car-offers/.env.example — proxy + email + port template
- car-offers/lib/config.js — env loader
- car-offers/lib/browser.js — stealth Chromium launcher with proxy, human delays
- car-offers/lib/carvana.js — full sell flow with multi-selector fallbacks, PerimeterX detection
- car-offers/index.js — CLI entry point
- car-offers/server.js — Express + mobile-first HTML form on port 3100

## Reviewer Verdict
PASS WITH NOTES — ready to deploy.
Notes: add rate limiting (one request at a time), stricter input validation, helmet middleware. Non-blocking for initial deploy.

## QA Result
Pending — deploy first, then QA on live URL.

## Blockers
- User needs to SSH to droplet and fill in .env (proxy creds + email)
- Carvana selectors may need tuning on real site

## Cost
Builder: ~37k tokens, 24 tool uses. Reviewer: ~29k tokens, 12 tool uses.
