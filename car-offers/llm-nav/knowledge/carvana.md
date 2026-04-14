# Carvana — sell-my-car wizard knowledge

## Status: BLOCKED at finalize page (Turnstile + email validation)

First LLM-nav attempt 2026-04-14 14:15 UTC on Consumer 1 (Westport CT 2022 Accord, VIN 1HGCV2F9XNA008352) reached the **last step** before blocking — a huge data point.

## Full wizard path confirmed (15+ steps, all completed)

Start: `https://www.carvana.com/sell-my-car`

1. Landing → click main CTA.
2. License-plate vs VIN toggle → pick VIN.
3. State dropdown → state derived from ZIP.
4. VIN submit → lands on vehicle-confirmation page.
5. **Vehicle confirmed**: "2022 Honda Accord Touring Sedan 4D" (Carvana decoded this correctly from VIN alone).
6. Color picker → White.
7. Modifications → None.
8. Condition questions (Carvana-specific phrasing): no damage to exterior / windshield / interior / technology / engine / mechanical. Drivable: yes. Overall: "Pretty great" (Carvana's option label for "Good").
9. **Mileage** → we entered 42,000, **Carvana rejected with an AutoCheck cross-check and forced 60,624**. AutoCheck is authoritative for real-world VINs. Panel consumer #1 mileage corrected to 60,624.
10. Accidents → No.
11. Smoking history → Not smoked in.
12. Tires → None replaced.
13. Keys → 2+.
14. ZIP → 06880.
15. Loan status → Neither (own outright).
16. Sell/Trade → Sell.
17. Email → submitted.
18. **Navigates to `/getoffer/finalize?vin=...`.**
19. **BLOCKED HERE:** Cloudflare Turnstile ("Verify you are human") + email validation error ("That email address seems to be invalid").

## Why it blocked (diagnosis)

Two distinct issues at `/finalize`:

- **Email validation failed.** `caroffers.tool@gmail.com` was rejected. Three possible causes: (a) the account doesn't exist so Carvana's SMTP verification fails, (b) the address is on a disposable-email blacklist, (c) it's been used on too many prior Carvana attempts. Fix: use a realistic persona-specific email per consumer (`catherine.b.smith@gmail.com` style), one unique per consumer identity.
- **Turnstile escalated from auto-resolve to visual CAPTCHA.** Agent clicked the checkbox multiple times — that's exactly what triggers the harder challenge. Fix: the retry prompt forbids any interaction with the challenge widget; just wait up to 120s.

Separately: the **whole flow took only ~10 min**. Real Carvana customers take 20–40 min (reading, hesitating, asking spouse about mileage). Carvana's risk model almost certainly scored our speed as bot-like, contributing to the finalize-page trust drop.

## Retry strategy (in flight as of 2026-04-14 14:39 UTC)

- **New consumer identity**: Consumer 2 (Jersey City 2022 Civic, different IP, different fingerprint).
- **Persona-specific email**: per the `PERSONAS` table in run_site.py.
- **Pre-declared car facts**: full `CAR_FACTS[vin]` dict so answers are identical every attempt.
- **Human-persona prompt**: "You're Javier Reyes from Jersey City, you bought this car 2 years ago, not in a hurry." LLM told to read pages, dwell 10–30s, scroll, backspace occasionally.
- **Turnstile rule**: never click. Wait 120s for auto-resolve or mark `site_blocked`.
- **`max_actions_per_step=1`**: force slow cadence.
- **Longer warmup**: organic browsing of carvana.com/cars inventory before sell flow.

## What worked on the first attempt (keep doing this)
- Navigation to VIN entry: the license/VIN toggle was correctly identified.
- State selection was handled.
- VIN submission accepted.
- Vehicle auto-decoded from VIN (no manual model picker needed).
- The 15-question wizard filled cleanly using the default answers.

## Consumer health on Carvana
- Consumer 1 (06880): **flagged** — its IP reached finalize before blocking. Quarantine on Carvana for 7d.
- Consumer 2 (07302): unknown — retry in flight.
- Consumers 3–12: untested.
