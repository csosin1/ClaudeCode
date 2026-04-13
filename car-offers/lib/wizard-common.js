/**
 * Shared helpers for the CarMax / Driveway wizards.
 *
 * This is NOT a single-flow replacement — both sites have unique
 * interstitials, layouts, and required-question sets — but several pieces
 * repeat verbatim from carvana.js:
 *   - screenshot(page, prefix, label)
 *   - isBlocked(page)  (generic CF / PerimeterX check)
 *   - humanInput(page, selector, value)  (type with drift + random per-char delay)
 *   - waitForBlockResolve(page, log, maxSec)
 *   - scanForOffer(page)  (looks for a $ amount in the DOM)
 *
 * Keeping these here means the site-specific modules stay focused on the
 * actual wizard logic.
 */

const fs = require('fs');
const path = require('path');
const {
  humanDelay, startMouseDrift, simulateHumanBehavior,
} = require('./browser');

async function screenshot(page, prefix, label) {
  try {
    const ts = Date.now();
    const filePath = path.join('/tmp', `${prefix}-${label}-${ts}.png`);
    await page.screenshot({ path: filePath, fullPage: false });
    return filePath;
  } catch {
    return null;
  }
}

/**
 * Generic challenge / access-denied detector. Returns true if the page
 * looks blocked by Cloudflare, PerimeterX, or a site-level access-deny.
 */
async function isBlocked(page) {
  let html;
  try { html = await page.content(); } catch { return false; }
  const lower = html.toLowerCase();
  const indicators = [
    'perimeterx', 'px-captcha', 'are you a human',
    'access denied', 'challenge-running', 'cf-browser-verification',
    'just a moment', 'enable javascript and cookies',
    'checking your browser', 'cf-chl-bypass', 'ray id',
    'incapsula', 'kasada', 'datadome',
    'unfortunately, we don\'t currently have an offer',
  ];
  return indicators.some((i) => lower.includes(i));
}

/**
 * Wait up to maxSec for an active challenge to auto-resolve.
 * Returns true if resolved, false if still blocked at timeout.
 */
async function waitForBlockResolve(page, log, maxSec = 60) {
  for (let waited = 0; waited < maxSec; waited += 5) {
    await humanDelay(4500, 5500);
    if (waited % 15 === 0) {
      try { await simulateHumanBehavior(page); } catch { /* ok */ }
    }
    if (!(await isBlocked(page))) {
      log(`[wizard] block resolved after ~${waited + 5}s`);
      return true;
    }
  }
  return false;
}

/**
 * Type into an element character by character with drift + jitter. Used for
 * VIN / mileage / zip inputs so the cadence doesn't look robotic.
 */
async function humanInput(page, el, value) {
  const stopDrift = startMouseDrift(page);
  try {
    try { await el.click(); } catch { /* already focused */ }
    try { await el.fill(''); } catch { /* readonly-clear */ }
    for (const c of String(value)) {
      await el.type(c, { delay: 0 });
      await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 80) + 40));
    }
  } finally { stopDrift(); }
}

/**
 * Look for a large dollar amount on the page. Returns an integer USD value
 * (e.g. 21000) or null. Ignores amounts < 500 to filter out shipping fees /
 * fine-print totals.
 */
async function scanForOffer(page) {
  try {
    const bodyText = await page.textContent('body');
    const matches = bodyText.match(/\$\s?\d{1,3}(?:[,]\d{3})+(?:\.\d{2})?|\$\s?\d{4,6}/g);
    if (!matches) return null;
    const amounts = matches
      .map((s) => parseInt(s.replace(/[$,\s]/g, ''), 10))
      .filter((n) => Number.isFinite(n) && n >= 500 && n < 250000);
    if (amounts.length === 0) return null;
    return Math.max(...amounts);
  } catch {
    return null;
  }
}

/**
 * Try a list of selectors in order. Return the first matching visible
 * element handle, or null.
 */
async function firstVisible(page, selectors, timeoutMs = 3000) {
  for (const sel of selectors) {
    try {
      const el = await page.waitForSelector(sel, { timeout: timeoutMs });
      if (el && await el.isVisible()) return { el, sel };
    } catch { continue; }
  }
  return null;
}

/**
 * Click the first button matching any of the given text labels.
 * Returns true if clicked, false otherwise.
 */
async function clickFirstByText(page, labels, timeoutMs = 2500) {
  for (const label of labels) {
    try {
      const selectors = [
        `button:has-text("${label}")`,
        `a:has-text("${label}")`,
        `label:has-text("${label}")`,
        `[role="button"]:has-text("${label}")`,
        `[role="radio"]:has-text("${label}")`,
        `[role="option"]:has-text("${label}")`,
      ];
      for (const sel of selectors) {
        try {
          const el = await page.waitForSelector(sel, { timeout: timeoutMs });
          if (el && await el.isVisible()) {
            await humanDelay(500, 1200);
            await el.click();
            return { clicked: true, label, selector: sel };
          }
        } catch { continue; }
      }
    } catch { continue; }
  }
  return { clicked: false };
}

/**
 * Detect account-wall / SMS-verification prompts. Returns a short reason
 * string if the site is demanding an account / phone / SMS verification,
 * else null. Callers STOP and return status='account_required' rather than
 * attempting to bypass.
 */
async function detectAccountWall(page) {
  let html;
  try { html = (await page.content()).toLowerCase(); } catch { return null; }
  const signals = [
    { re: /enter (?:your |the )?code (?:we|sent)/i, reason: 'sms_code_required' },
    { re: /verification code/i, reason: 'verification_code_required' },
    { re: /verify your (?:phone|identity)/i, reason: 'phone_verification_required' },
    { re: /sign in to (?:your )?carmax/i, reason: 'carmax_signin_required' },
    { re: /create (?:a |your )?(?:carmax )?account/i, reason: 'account_signup_required' },
    { re: /we texted you/i, reason: 'sms_code_required' },
    { re: /two-factor/i, reason: 'two_factor_required' },
  ];
  for (const s of signals) {
    if (s.re.test(html)) return s.reason;
  }
  return null;
}

module.exports = {
  screenshot,
  isBlocked,
  waitForBlockResolve,
  humanInput,
  scanForOffer,
  firstVisible,
  clickFirstByText,
  detectAccountWall,
};
