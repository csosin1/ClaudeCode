/**
 * Driveway baseline recording. Driveway is Lithia's used-car site — the
 * sell-your-car funnel is simpler than Carvana/CarMax but has some
 * vehicle-history upsell branches we want to watch for.
 */
module.exports = {
  title: '10-minute car-selling website walkthrough (screen recording + narration)',
  description:
    "You'll visit Driveway's sell-your-car page, enter a VIN we provide, and " +
    "complete the full offer flow while screen-recording and narrating aloud. " +
    "No real car is being sold. We need to see every screen, field, and " +
    "optional upsell, and hear what you think at each step.",
  steps: [
    'Start a screen recording with microphone audio (Loom free tier is fine).',
    'Open https://www.driveway.com/sell in a regular desktop browser window.',
    'Enter the VIN we provide in the study instructions (17 characters).',
    'Enter mileage = 48000 and ZIP = 06880 when asked.',
    'Answer every condition / title / loan question truthfully for the vehicle.',
    'If the site offers a vehicle-history upsell or carfax link, narrate what you see but DO NOT pay for anything.',
    'When an offer appears, read the dollar amount aloud.',
    'If the site asks you to enter contact info or schedule pickup, STOP the recording there.',
    'Upload the recording to the link we provide at the end, then enter the final offer dollar amount in the box.',
  ],
  success_criteria:
    'Video is at least 5 minutes long, every step is narrated aloud, and the ' +
    'final offer dollar amount is typed into the response box.',
  reward_usd_cents: 1000,
  participants: 5,
  max_minutes: 20,
  prefer: 'quality',
  external_url: 'https://casinv.dev/car-offers/preview/humanloop/baseline/driveway',
};
