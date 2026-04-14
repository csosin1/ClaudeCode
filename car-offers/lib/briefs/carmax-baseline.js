/**
 * CarMax baseline recording — see carvana-baseline.js for the pattern.
 * CarMax's offer flow is a little different (license plate OR VIN entry,
 * appointment scheduling at the end), so the brief reflects that.
 */
module.exports = {
  title: '10-minute car-selling website walkthrough (screen recording + narration)',
  description:
    "You'll visit CarMax's sell-or-trade page, enter a VIN we provide, and " +
    "complete the full instant-offer flow while screen-recording and " +
    "narrating aloud. No real car is being sold. We need to see every screen " +
    "and hear your thinking at every step.",
  steps: [
    'Start a screen recording with microphone audio (Loom free tier is fine).',
    'Open https://www.carmax.com/sell-my-car in a regular desktop browser window.',
    'Choose "Enter VIN" when offered the VIN-vs-plate choice.',
    'Enter the VIN we provide in the study instructions (17 characters).',
    'Enter mileage = 48000 and ZIP = 06880 when asked.',
    'Answer every condition / title / loan / keys question truthfully for the vehicle.',
    'When the instant offer appears, read the dollar amount aloud and the offer-expiration date aloud.',
    'If the site asks you to schedule an appointment or create an account, STOP the recording there.',
    'Upload the recording to the link we provide at the end, then enter the final offer dollar amount in the box.',
  ],
  success_criteria:
    'Video is at least 5 minutes long, every step is narrated aloud, the ' +
    'final offer dollar amount AND expiration date are typed into the ' +
    'response boxes. Silent or truncated recordings will be rejected.',
  reward_usd_cents: 1000,
  participants: 5,
  max_minutes: 20,
  prefer: 'quality',
  external_url: 'https://casinv.dev/car-offers/preview/humanloop/baseline/carmax',
};
