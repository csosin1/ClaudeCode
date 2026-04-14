/**
 * Ongoing-validation MTurk audit brief. Cheap, fast, volume: one worker
 * runs one VIN through one site and reports back the final offer dollar
 * amount and the URL of the final page. Used to spot-check our wizards
 * across time — if a dozen workers each see a different offer structure
 * than our scraper, we know the site changed.
 *
 * The brief's `site` field is a placeholder — the orchestrator that fires
 * this swaps it for the site-of-the-day before posting.
 */
module.exports = {
  title: 'Look up one car\'s trade-in offer and tell us the dollar amount (2 min)',
  description:
    "We'll give you a VIN (17-character vehicle ID) and a website. Visit the " +
    "site, enter the VIN and the mileage/ZIP we provide, and when the site " +
    "shows an instant offer dollar amount, type that dollar amount and the " +
    "URL of the page you saw it on into the response boxes. Takes 2-3 minutes.",
  steps: [
    'Open the website URL we provide at the top of this HIT.',
    'When asked, enter the VIN, mileage (48000), and ZIP (06880) we provide.',
    'Answer any condition / title / loan questions with sensible defaults (good condition, clean title, no loan).',
    'When the instant offer dollar amount appears, copy the full dollar amount and the browser URL.',
    'Paste both into the response boxes and submit.',
  ],
  success_criteria:
    'Offer dollar amount and final page URL are both filled in. Obvious ' +
    'mismatches (e.g. offer="$0" when the site is showing a real number) ' +
    'will be rejected.',
  reward_usd_cents: 300, // $3 — small task
  participants: 1,
  max_minutes: 10,
  prefer: 'volume', // MTurk
  external_url: 'https://casinv.dev/car-offers/preview/humanloop/audit',
  mturk_external_url: 'https://casinv.dev/car-offers/preview/humanloop/audit',
};
