/**
 * Shared offer-request shape + per-site condition mapping.
 *
 * Every site handler (carvana, carmax, driveway) takes the SAME normalized
 * input:
 *   { vin, mileage, zip, condition }
 *
 * This is the apples-to-apples seatbelt: same VIN + mileage + zip + canonical
 * condition goes through all three buyers so the prices are directly
 * comparable. Where a buyer asks additional required questions that we can't
 * keep constant through condition alone (accident history, title status,
 * etc.), EXTRA_ANSWERS below provides defensible defaults that are held
 * identical across all three sites. Any deviation MUST be recorded so the
 * comparison row stays transparent.
 *
 * Canonical condition vocabulary: 'Excellent' | 'Good' | 'Fair' | 'Poor'
 *   - Excellent: no cosmetic flaws, no mechanical issues, clean title,
 *                recent inspection, no accidents, well-kept interior
 *   - Good:      (DEFAULT) a few cosmetic issues, all functions work, may
 *                have 1 minor past accident with no frame damage
 *   - Fair:      multiple cosmetic flaws, maybe 1 mechanical item needing
 *                attention, but drives
 *   - Poor:      significant cosmetic + mechanical issues; may not pass
 *                inspection without work
 */

const VALID_CONDITIONS = ['Excellent', 'Good', 'Fair', 'Poor'];
const DEFAULT_CONDITION = 'Good';

/**
 * Per-site vocabulary map. Maps our canonical condition to the exact label
 * the site's wizard uses. If a site forces an additional question (accident
 * history, features, etc.) that we can't derive from condition alone, the
 * answer lives in EXTRA_ANSWERS below so all three handlers read from the
 * same source.
 *
 * Carvana uses "Excellent / Good / Fair / Rough" — "Poor" maps to "Rough".
 * CarMax uses Excellent / Good / Fair / Poor — 1:1 with our canonical set.
 * Driveway uses Excellent / Good / Fair / Poor — also 1:1 (verify at
 * build time; they may use "Average" for Fair depending on release).
 *
 * Each site handler should read `CONDITION_MAP[site][canonical]` to get the
 * exact string to click/select.
 */
const CONDITION_MAP = {
  carvana: {
    Excellent: 'Excellent',
    Good: 'Good',
    Fair: 'Fair',
    Poor: 'Rough',
  },
  carmax: {
    Excellent: 'Excellent',
    Good: 'Good',
    Fair: 'Fair',
    Poor: 'Poor',
  },
  driveway: {
    Excellent: 'Excellent',
    Good: 'Good',
    Fair: 'Fair',
    Poor: 'Poor',
  },
};

/**
 * Held-constant answers to additional forced questions. Every site handler
 * gives the same answer so the comparison is apples-to-apples. If a site's
 * wizard adds a new question not covered here, the handler should either
 * (a) answer with the most common "clean" default and log it, or (b) fail
 * with status='needs_answer' so the builder can add it here explicitly.
 */
const EXTRA_ANSWERS = {
  accidentHistory: 'None',       // no accidents reported
  titleStatus: 'Clean',          // clean title, not salvage / rebuilt
  loanStatus: 'Own outright',    // fully paid off, no payoff to worry about
  ownership: 'I own it',         // primary owner (not leased)
  modifications: 'None',         // stock vehicle
  sellingReason: 'Just selling', // not trading in
};

/**
 * Normalize and validate a raw request. Throws on bad input.
 * Returns: { vin, mileage, zip, condition }
 */
function normalizeOfferRequest(raw) {
  if (!raw || typeof raw !== 'object') {
    throw new Error('offer request must be an object');
  }
  const vin = String(raw.vin || '').trim().toUpperCase();
  const mileage = String(raw.mileage || '').trim();
  const zip = String(raw.zip || '').trim();
  const condition = String(raw.condition || DEFAULT_CONDITION).trim();

  if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) {
    throw new Error(`invalid VIN: must be 17 chars (no I, O, Q). got: ${JSON.stringify(vin)}`);
  }
  if (!/^\d{1,7}$/.test(mileage)) {
    throw new Error(`invalid mileage: must be digits only. got: ${JSON.stringify(mileage)}`);
  }
  if (!/^\d{5}$/.test(zip)) {
    throw new Error(`invalid zip: must be 5 digits. got: ${JSON.stringify(zip)}`);
  }
  if (!VALID_CONDITIONS.includes(condition)) {
    throw new Error(`invalid condition: must be one of ${VALID_CONDITIONS.join('/')}. got: ${JSON.stringify(condition)}`);
  }

  return { vin, mileage, zip, condition };
}

/** Site-specific condition label. Throws if the site/condition combo is unknown. */
function siteConditionLabel(site, canonical) {
  const map = CONDITION_MAP[site];
  if (!map) throw new Error(`unknown site: ${site}`);
  const label = map[canonical];
  if (!label) throw new Error(`unknown canonical condition: ${canonical}`);
  return label;
}

module.exports = {
  VALID_CONDITIONS,
  DEFAULT_CONDITION,
  CONDITION_MAP,
  EXTRA_ANSWERS,
  normalizeOfferRequest,
  siteConditionLabel,
};
