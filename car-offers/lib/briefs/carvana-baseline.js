/**
 * Carvana baseline: a paid participant records themselves getting a real
 * Carvana instant offer from start to finish. We use the recording as the
 * ground-truth walkthrough — every selector, every prompt, every offer
 * screen — so the wizard builder can target the exact DOM the participant
 * saw, not what we guess.
 *
 * Fire via: POST /api/humanloop/fire-baseline/carvana
 */
module.exports = {
  title: '10-minute car-selling website walkthrough (screen recording + narration)',
  description:
    "You'll visit Carvana's sell-my-car page, fill in a VIN we provide, and " +
    "complete the full offer flow while screen-recording and narrating aloud " +
    "what you see at each step. No real car is being sold. We just need to " +
    "see every screen, every field, and hear what you think at each step.",
  steps: [
    'Start a screen recording with microphone audio (Loom free tier is fine).',
    'Open https://www.carvana.com/sell-my-car in a regular desktop browser window.',
    'When prompted for a VIN, enter the VIN we will provide in the study instructions (17 characters).',
    'Fill in mileage = 48000 and ZIP = 06880 when asked.',
    'Answer every follow-up question truthfully for the vehicle (condition, title, loan status, etc.).',
    'When an offer appears, read the dollar amount aloud and hover over any "how did we calculate this" link.',
    'If the site asks for an email address or to create an account, STOP the recording there — do NOT create an account.',
    'Upload the recording to the link we provide at the end of the study, then enter the final offer dollar amount in the box.',
  ],
  success_criteria:
    'Video is at least 5 minutes long, every step above is narrated aloud, ' +
    'and the final offer dollar amount is typed into the response box. ' +
    'Recordings that skip steps or have no audio will be rejected.',
  reward_usd_cents: 1000, // $10 — quality job, deserves real pay
  participants: 5,
  max_minutes: 20,
  prefer: 'quality', // Prolific
  // The orchestrator swaps this for the actual qualtrics URL when it fires.
  external_url: 'https://casinv.dev/car-offers/preview/humanloop/baseline/carvana',
};
