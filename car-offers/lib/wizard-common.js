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
 * Debug-mode dump: take a screenshot AND save the HTML to /tmp/wizard-debug/<site>/.
 * Only called when the wizard is run with { debug: true } so production runs
 * don't fill /tmp with HTML dumps. Returns { png, html } paths or null on error.
 */
async function debugDump(page, site, label) {
  try {
    const dir = path.join('/tmp', 'wizard-debug', site);
    fs.mkdirSync(dir, { recursive: true });
    const stamp = `${label}-${Date.now()}`;
    const png = path.join(dir, `${stamp}.png`);
    const html = path.join(dir, `${stamp}.html`);
    try { await page.screenshot({ path: png, fullPage: true }); } catch { /* ok */ }
    try {
      const content = await page.content();
      const url = page.url();
      fs.writeFileSync(html, `<!-- url: ${url} -->\n${content}`);
    } catch { /* ok */ }
    return { png, html };
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

/**
 * Best-effort selector finder that handles common modern-form patterns
 * where the input has no useful name/id/aria/placeholder. Tries:
 *   1. Each provided selector via firstVisible (existing behavior)
 *   2. Looks for a visible label whose text matches `labels`, then walks
 *      to the nearest input via several DOM relationships
 *   3. Falls back to a Playwright getByLabel locator
 *
 * Returns { el, sel } on success, null otherwise.
 */
async function findInputByLabelOrSelectors(page, selectors, labels, timeoutMs = 4000) {
  const direct = await firstVisible(page, selectors, Math.min(timeoutMs, 1500));
  if (direct) return direct;

  for (const labelText of labels) {
    // Try Playwright's accessible-name locator first
    try {
      const loc = page.getByLabel(new RegExp(labelText, 'i'));
      await loc.first().waitFor({ state: 'visible', timeout: 1500 });
      const el = await loc.first().elementHandle();
      if (el) return { el, sel: `getByLabel(/${labelText}/i)` };
    } catch { /* next */ }

    // Try input/textarea adjacent to a <label> matching this text.
    const adjacent = [
      `label:has-text("${labelText}") input`,
      `label:has-text("${labelText}") + input`,
      `label:has-text("${labelText}") + div input`,
      `:text("${labelText}") + input`,
      `:text("${labelText}") ~ input`,
      `:text("${labelText}") + div input`,
      // Modern Material Design: floating label sits inside a div next to input
      `div:has(> :text("${labelText}")) input`,
      `div:has(> label:has-text("${labelText}")) input`,
    ];
    for (const sel of adjacent) {
      try {
        const el = await page.waitForSelector(sel, { timeout: 800 });
        if (el && await el.isVisible()) return { el, sel };
      } catch { /* next */ }
    }
  }
  return null;
}

/**
 * Click an expandable section (CarMax/Driveway accordion-style) by its
 * heading text. Many modern forms hide subsequent fields behind a click-to-
 * expand region. Returns true if clicked, false otherwise.
 */
async function expandSectionByText(page, headings, timeoutMs = 1500) {
  for (const heading of headings) {
    const selectors = [
      `button:has-text("${heading}")`,
      `[role="button"]:has-text("${heading}")`,
      `[aria-expanded="false"]:has-text("${heading}")`,
      `summary:has-text("${heading}")`,
      `div[role="heading"]:has-text("${heading}")`,
      `h2:has-text("${heading}")`,
      `h3:has-text("${heading}")`,
      `h4:has-text("${heading}")`,
    ];
    for (const sel of selectors) {
      try {
        const el = await page.waitForSelector(sel, { timeout: timeoutMs });
        if (el && await el.isVisible()) {
          await humanDelay(300, 700);
          try { await el.click(); return { clicked: true, heading, sel }; }
          catch { /* try next */ }
        }
      } catch { /* next */ }
    }
  }
  return { clicked: false };
}

/**
 * Pick an option from a dropdown — handles native <select>, role=combobox,
 * MUI Select, and "click button → option list" patterns.
 *
 * `triggerSelectors` open the dropdown (or are a <select>).
 * `optionLabels` are the visible option strings to try, in order.
 * Returns true if an option was selected.
 */
async function pickDropdownOption(page, triggerSelectors, optionLabels, timeoutMs = 2000) {
  for (const sel of triggerSelectors) {
    try {
      const el = await page.waitForSelector(sel, { timeout: timeoutMs });
      if (!el || !(await el.isVisible())) continue;
      // Native <select>?
      const tag = await el.evaluate((n) => n.tagName).catch(() => '');
      if (tag === 'SELECT') {
        for (const lab of optionLabels) {
          try { await el.selectOption({ label: lab }); return { selected: true, sel, label: lab }; }
          catch { /* try next label */ }
        }
        // Last resort: pick first non-empty option
        try {
          const value = await el.evaluate((s) => {
            const opt = Array.from(s.options).find((o) => o.value && o.value !== '');
            if (opt) { s.value = opt.value; s.dispatchEvent(new Event('change', { bubbles: true })); return opt.textContent; }
            return null;
          });
          if (value) return { selected: true, sel, label: value };
        } catch { /* ok */ }
        continue;
      }
      // Click trigger to open the option list
      try { await el.click(); } catch { continue; }
      await humanDelay(300, 700);
      for (const lab of optionLabels) {
        const optSelectors = [
          `[role="option"]:has-text("${lab}")`,
          `li:has-text("${lab}")`,
          `[role="listbox"] *:has-text("${lab}")`,
          `[data-value]:has-text("${lab}")`,
          `div[role="menuitem"]:has-text("${lab}")`,
        ];
        for (const optSel of optSelectors) {
          try {
            const opt = await page.waitForSelector(optSel, { timeout: 800 });
            if (opt && await opt.isVisible()) {
              await opt.click();
              return { selected: true, sel, label: lab, optSel };
            }
          } catch { /* next */ }
        }
      }
      // Couldn't find a match — pick the first visible option
      try {
        const fallback = await page.$('[role="option"]:visible, [role="listbox"] li:visible');
        if (fallback) {
          const txt = await fallback.textContent().catch(() => '');
          await fallback.click();
          return { selected: true, sel, label: (txt || '').trim().slice(0, 40), fallback: true };
        }
      } catch { /* ok */ }
      // Close dropdown by clicking elsewhere
      try { await page.keyboard.press('Escape'); } catch { /* ok */ }
    } catch { /* next selector */ }
  }
  return { selected: false };
}

module.exports = {
  screenshot,
  debugDump,
  isBlocked,
  waitForBlockResolve,
  humanInput,
  scanForOffer,
  firstVisible,
  findInputByLabelOrSelectors,
  expandSectionByText,
  pickDropdownOption,
  clickFirstByText,
  detectAccountWall,
};
