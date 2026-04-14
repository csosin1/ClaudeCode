# CarMax — sell-my-car wizard knowledge

## Status: WORKING (first success 2026-04-14 14:15 UTC)

First confirmed real offer: **$25,200** for 2022 Honda Accord Touring (VIN `1HGCV2F9XNA008352`, 42k mi, zip 06880, condition Good).
- Offer code: `SK5Z9Z2Y`
- Final URL: `https://www.carmax.com/sell-my-car/offers/SK5Z9Z2Y?originPage=OfferDelivery`
- Expires: 2026-04-21
- Duration: 416 sec (6.9 min) — well inside the 8-10 min floor target.

## Step-by-step flow (from the successful trace)

Start: `https://www.carmax.com/sell-my-car`

1. **Landing page has hero VIN-entry form.** Fill VIN, click Continue/Get Offer.
2. **Offer-ID issued**, navigates to `/sell-my-car/offers/<code>`.
3. **Appraisal checkout** — ask a series of radio-group questions. Fill with defaults:
   - Accidents: No
   - Frame damage: No
   - Flood damage: No
   - Smoked in: No
   - Mechanical issues: No
   - Odometer issues: No
   - Paint/body work: No
   - Rust/hail damage: No
   - Interior parts broken: No
   - Interior rips/tears: No
   - Tires need replacement: No
   - Number of keys: 2 or more
   - Modifications: No
   - Other issues: No
   - Selling/Trading: Selling only
4. **Email capture** — use project email.
5. **Final offer page** — dollar amount + offer code displayed prominently.

**No SMS, no phone, no account creation required.** CarMax is the most cooperative of the three.

## Selectors observed (for future deterministic wizard)

- Hero VIN input on landing: (extract from trace or debug-capture for certainty)
- Continue button: `#ico-continue-button` (per prior Builder A's debug work)
- Radio groups use standard `input[type=radio]` with label text matching the question option
- Final offer dollar amount: prominent H1/H2 on `/sell-my-car/offers/<code>` page

## Consumers known good
- Consumer 1 (Westport CT 2022 Accord, zip 06880, fingerprint #0) — confirmed ok.

## Consumers not yet tried on CarMax
- Consumers 2–12 (all untested but no reason to expect failures).

## Known alternatives / branches if this ever fails
- If hero VIN form isn't visible on landing, scroll down — it may be below the fold.
- If Continue stays disabled, check for a required "best description" dropdown near top of offer questions.
- If `account_required` appears, check whether email entered matches a pre-existing CarMax account (retry with a fresh project email).
