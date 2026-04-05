# Change Log
# Webhook test 1775397948

## 2026-04-05 Goal 1: Carvana Offer Automation
- What was built: Full Carvana "Sell My Car" automation — stealth browser launcher, Carvana flow script, CLI entry point, and Express web UI for iPhone use
- Files created:
  - `car-offers/package.json` — project manifest with playwright-extra, stealth plugin, dotenv, express
  - `car-offers/.env.example` — template for proxy, email, and port config
  - `car-offers/lib/config.js` — loads .env, exports all config vars
  - `car-offers/lib/browser.js` — stealth Chromium launcher with proxy support, humanDelay, humanType, randomMouseMove
  - `car-offers/lib/carvana.js` — full Carvana sell flow automation (VIN entry, mileage, conditions, zip, email, offer extraction)
  - `car-offers/index.js` — CLI: `node index.js carvana <vin> <mileage> <zip>`
  - `car-offers/server.js` — Express server with mobile-first HTML UI and POST /api/carvana endpoint
- Assumptions made:
  - Carvana form selectors are based on reasonable guesses (placeholder text, input types, button text) since we can't test from the sandbox. Multiple fallback selectors used for resilience.
  - Condition questions default to "Good" / "None" / "Clean" / "Excellent" options
  - The stealth plugin (puppeteer-extra-plugin-stealth) works with playwright-extra to bypass PerimeterX
  - A residential proxy is required — datacenter IPs will be blocked by Carvana
  - 120-second total timeout for the entire flow; 45-second wait for offer calculation
- Things the reviewer should check:
  - No credentials or emails are hardcoded — all come from .env
  - The HTML UI is mobile-first and works at 390px (dark theme, large touch targets)
  - Browser is always closed in finally blocks
  - CAPTCHA/block detection returns immediately without retrying
  - The offer extraction scans both specific selectors and full body text for dollar amounts

## 2026-04-05 Dice Roller App
- What was built: A single-file dice roller game with a Roll button, Unicode die face display, numeric result, and a rolling history of the last 10 rolls. Dark theme, mobile-first layout matching button-test style.
- Files modified:
  - `games/dice-roller/index.html` (new) — the complete app
  - `tests/qa-smoke.spec.ts` — added "Dice Roller App" test.describe block
- Tests added:
  - "page loads with correct heading" — verifies 200 status and h1 text
  - "clicking roll produces a number 1-6 and updates history" — clicks roll twice, verifies both results are 1-6, verifies history has at least 2 entries, logs values for debugging
  - "no JS errors on page" — loads page, clicks roll, checks for JS errors
- Assumptions:
  - Used Unicode dice characters (U+2680 to U+2685) for die faces — these render on all modern browsers/phones
  - History shows most recent roll first
  - History capped at 10 entries as specified
- Things the reviewer should check:
  - Unicode dice characters render correctly at the chosen font size
  - History items wrap properly on narrow (390px) screens
  - The #result element contains only the numeric value (no extra text) for test compatibility
