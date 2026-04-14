const {
  launchBrowser, humanDelay, microDelay, humanType, randomMouseMove, bezierMouseMove,
  closeBrowser, simulateHumanBehavior, simulateBlurFocus, startMouseDrift,
  markProfileWarmed, profileIsWarm,
} = require('./browser');
const { fullWarmup, miniBrowse } = require('./shopper-warmup');
const { debugDump, pickDropdownOption } = require('./wizard-common');
const config = require('./config');
const path = require('path');
const fs = require('fs');

const CARVANA_URL = 'https://www.carvana.com/sell-my-car';
// Longer timeout — shopper warmup + sell flow + Turnstile can reach 12+ min.
const TOTAL_TIMEOUT = 900_000;
// How long a profile stays "warm" before we re-run the full shopper warmup.
const WARMUP_TTL_HOURS = 24;

// Persistent user-data-dir means only one Carvana flow can run at a time —
// Chromium enforces a singleton lock on the profile. Serialize runs.
let activeRun = null;

/**
 * Take a timestamped screenshot for debugging.
 */
async function screenshot(page, label) {
  try {
    const ts = Date.now();
    const filePath = path.join('/tmp', `carvana-${label}-${ts}.png`);
    await page.screenshot({ path: filePath, fullPage: false });
    console.log(`  [screenshot] ${filePath}`);
    return filePath;
  } catch {
    return null;
  }
}

/**
 * Check if the page shows a CAPTCHA or bot-block screen.
 */
async function isBlocked(page) {
  let html;
  try {
    html = await page.content();
  } catch (err) {
    console.error(`[carvana] isBlocked check failed (page may have crashed): ${err.message}`);
    return false; // Can't check — let the flow continue and fail at the next step
  }
  const blockedIndicators = [
    'perimeterx',
    'px-captcha',
    'are you a human',
    'access denied',
    'challenge-running',
    'cf-browser-verification',
    'just a moment',
    'enable javascript and cookies',
    'checking your browser',
    'cf-chl-bypass',
    'ray id',
  ];
  const lower = html.toLowerCase();
  return blockedIndicators.some((indicator) => lower.includes(indicator));
}

/**
 * Automate the Carvana "Sell My Car" flow.
 *
 * @param {Object} params
 * @param {string} params.vin - 17-character VIN
 * @param {string} params.mileage - Current mileage
 * @param {string} params.zip - Zip code
 * @param {string} [params.email] - Email for the offer (falls back to config)
 * @returns {{ offer?: string, details?: object, error?: string }}
 */
/**
 * Simple ZIP -> US state map by ZIP prefix. Covers all 50 states via the
 * first one or two digits. Used to pick the "State" option on Carvana's
 * getoffer/entry page when the VIN mode requires a state dropdown.
 * Source: USPS ZIP code ranges. Intentionally rough — the panel's 12 zips
 * are all in populous metros so the prefix is unambiguous.
 */
function zipToState(zip) {
  const z = String(zip || '').replace(/[^0-9]/g, '').padStart(5, '0').slice(0, 5);
  const p3 = z.slice(0, 3);
  const p2 = z.slice(0, 2);
  const p1 = z.slice(0, 1);
  // Some 3-digit prefixes land in a single state; check those first.
  const p3Map = {
    '006': 'PR', '007': 'PR', '009': 'PR',
    '200': 'DC', '202': 'DC', '203': 'DC', '204': 'DC', '205': 'DC',
  };
  if (p3Map[p3]) return p3Map[p3];
  const p2Map = {
    // Northeast
    '00': 'CT', '01': 'MA', '02': 'MA', '03': 'NH', '04': 'ME', '05': 'VT',
    '06': 'CT', '07': 'NJ', '08': 'NJ', '09': 'NJ',
    '10': 'NY', '11': 'NY', '12': 'NY', '13': 'NY', '14': 'NY',
    '15': 'PA', '16': 'PA', '17': 'PA', '18': 'PA', '19': 'PA',
    // Mid-Atlantic / South
    '20': 'DC', '21': 'MD', '22': 'VA', '23': 'VA', '24': 'VA',
    '25': 'WV', '26': 'WV', '27': 'NC', '28': 'NC', '29': 'SC',
    '30': 'GA', '31': 'GA', '32': 'FL', '33': 'FL', '34': 'FL',
    '35': 'AL', '36': 'AL', '37': 'TN', '38': 'TN', '39': 'MS',
    // Midwest
    '40': 'KY', '41': 'KY', '42': 'KY', '43': 'OH', '44': 'OH', '45': 'OH',
    '46': 'IN', '47': 'IN', '48': 'MI', '49': 'MI',
    '50': 'IA', '51': 'IA', '52': 'IA', '53': 'WI', '54': 'WI',
    '55': 'MN', '56': 'MN', '57': 'SD', '58': 'ND', '59': 'MT',
    '60': 'IL', '61': 'IL', '62': 'IL', '63': 'MO', '64': 'MO', '65': 'MO',
    '66': 'KS', '67': 'KS', '68': 'NE', '69': 'NE',
    // South-central
    '70': 'LA', '71': 'LA', '72': 'AR', '73': 'OK', '74': 'OK',
    '75': 'TX', '76': 'TX', '77': 'TX', '78': 'TX', '79': 'TX',
    // Mountain / West
    '80': 'CO', '81': 'CO', '82': 'WY', '83': 'ID', '84': 'UT',
    '85': 'AZ', '86': 'AZ', '87': 'NM', '88': 'NM', '89': 'NV',
    '90': 'CA', '91': 'CA', '92': 'CA', '93': 'CA', '94': 'CA', '95': 'CA', '96': 'CA',
    '97': 'OR', '98': 'WA', '99': 'AK',
  };
  if (p2Map[p2]) return p2Map[p2];
  return p1 === '0' ? 'MA' : 'NY'; // generic fallback, rarely hit
}

async function _getCarvanaOfferImpl({ vin, mileage, zip, email, consumerId, fingerprintProfileId, proxyZip, debug }) {
  const offerEmail = email || config.PROJECT_EMAIL || 'caroffers.tool@gmail.com';
  const stateCode = zipToState(zip);
  let browser = null;
  const startTime = Date.now();
  const wizardLog = []; // Capture wizard diagnostics for return value
  if (!offerEmail) {
    return { error: 'No email configured. Set PROJECT_EMAIL in .env', wizardLog };
  }

  function log(msg) {
    console.log(msg);
    wizardLog.push(`${Math.round((Date.now() - startTime) / 1000)}s: ${msg}`);
  }

  function elapsed() {
    return Date.now() - startTime;
  }

  function checkTimeout() {
    if (elapsed() > TOTAL_TIMEOUT) {
      throw new Error('Total timeout exceeded (300s)');
    }
  }

  try {
    log(`[carvana] Starting offer flow for VIN=${vin} mileage=${mileage} zip=${zip}`);
    log(`[carvana] Proxy: host=${config.PROXY_HOST} port=${config.PROXY_PORT} user=${config.PROXY_USER} pass=${config.PROXY_PASS ? config.PROXY_PASS.length + 'chars' : 'NONE'}`);

    // --- Launch browser ---
    let result;
    let page;
    let launchMethod = 'unknown';
    try {
      result = await launchBrowser({
        consumerId,
        fingerprintProfileId,
        proxyZip: proxyZip || zip,
      });
    } catch (launchErr) {
      console.error(`[carvana] Browser launch failed: ${launchErr.message}`);
      throw launchErr;
    }
    browser = result.browser;
    page = result.page;
    launchMethod = result.launchMethod || 'unknown';
    log(`[carvana] Browser: ${launchMethod} | headed: ${!!process.env.DISPLAY}`);

    // --- Step 1: Shopper warmup — act like a real used-car shopper BEFORE
    // the sell flow. Cloudflare Turnstile's interactive score grades
    // pre-submission behavior; a cold jump to /sell-my-car looks robotic.
    // If profile was warmed within WARMUP_TTL_HOURS, do a short mini-browse;
    // otherwise run the full 10-15 min warmup once and mark it.
    const isWarm = profileIsWarm(consumerId, WARMUP_TTL_HOURS);
    log(`[carvana] Profile warm state: ${isWarm ? 'fresh (mini browse)' : 'cold (full warmup)'}`);
    try {
      if (isWarm) {
        await miniBrowse(page, log);
      } else {
        await fullWarmup(page, log);
        markProfileWarmed(consumerId);
      }
    } catch (warmErr) {
      log(`[carvana] Warmup error (non-fatal): ${warmErr.message}`);
    }
    await humanDelay(2000, 5000);

    // --- Navigate to Carvana sell page. Referer is naturally carvana.com
    // because the warmup just browsed there. ---
    log('[carvana] Navigating to Carvana sell page...');

    let carvanaLoaded = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await page.goto(CARVANA_URL, {
          waitUntil: 'domcontentloaded',
          timeout: 60000,
        });
      } catch (navErr) {
        log(`[carvana] Navigation attempt ${attempt} failed: ${navErr.message}`);
        if (attempt === 2) {
          await screenshot(page, '00-nav-failure');
          throw navErr;
        }
        await humanDelay(10000, 15000);
        continue;
      }

      // Wait for page to fully settle (Cloudflare JS challenge needs time)
      await humanDelay(5000, 8000);
      await simulateHumanBehavior(page);
      await humanDelay(3000, 5000);
      await screenshot(page, `01-landing-attempt-${attempt}`);

      // Log page state
      try {
        const pageTitle = await page.title();
        const pageUrl = page.url();
        const bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 500)).catch(() => '');
        log(`[carvana] Landing — title: "${pageTitle}", url: ${pageUrl}`);
        log(`[carvana] Body: ${bodySnippet.substring(0, 200)}`);
      } catch (_) {}

      // Wait for networkidle — Cloudflare challenges resolve during this phase
      try {
        await page.waitForLoadState('networkidle', { timeout: 30000 });
      } catch {
        log('[carvana] networkidle timeout — checking if blocked...');
      }

      if (!(await isBlocked(page))) {
        carvanaLoaded = true;
        log(`[carvana] Carvana loaded successfully on attempt ${attempt}`);
        break;
      }

      // Cloudflare JS challenge detected — in headed mode, these typically
      // auto-resolve within 5-15s if the browser passes fingerprint checks.
      // DON'T click randomly — just wait patiently like a real user would.
      log(`[carvana] Cloudflare challenge detected (attempt ${attempt})`);
      await screenshot(page, `blocked-attempt-${attempt}`);

      // Strategy: wait up to 60s for the challenge to auto-resolve.
      // Check every 5s if the challenge page has changed.
      const maxWait = [30, 45, 60][attempt] || 60;
      log(`[carvana] Waiting up to ${maxWait}s for challenge auto-resolution...`);

      let resolved = false;
      for (let waited = 0; waited < maxWait; waited += 5) {
        await humanDelay(4500, 5500);

        // Gentle mouse movement (real users move their mouse while waiting)
        if (waited % 15 === 0) {
          await simulateHumanBehavior(page);
        }

        // Check if Cloudflare Turnstile checkbox appeared — click it
        try {
          const cfFrames = page.frames().filter(f =>
            f.url().includes('challenges.cloudflare.com') ||
            f.url().includes('turnstile') ||
            f.url().includes('cf-chl')
          );
          for (const frame of cfFrames) {
            try {
              const checkbox = await frame.$('input[type="checkbox"], .cb-i, #challenge-stage');
              if (checkbox) {
                log('[carvana] Turnstile checkbox found — clicking...');
                await humanDelay(500, 1500);
                await checkbox.click();
                await humanDelay(3000, 5000);
              }
            } catch { /* ignore frame errors */ }
          }
        } catch { /* ignore */ }

        // Check if challenge resolved
        if (!(await isBlocked(page))) {
          resolved = true;
          log(`[carvana] Cloudflare resolved after ~${waited + 5}s`);
          break;
        }
        log(`[carvana] Still blocked after ${waited + 5}s...`);
      }

      if (resolved) {
        carvanaLoaded = true;
        break;
      }

      // If not resolved, try a fresh navigation on next attempt
      if (attempt < 2) {
        log('[carvana] Challenge not resolved — will retry with fresh navigation...');
        await humanDelay(10000, 15000);
      }
    }

    if (!carvanaLoaded) {
      const ssPath = await screenshot(page, 'blocked-final');
      const pageTitle = await page.title().catch(() => 'unknown');
      const bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 500)).catch(() => '');
      const pageUrl = page.url();
      log(`[carvana] BLOCKED after all attempts — title: ${pageTitle}, url: ${pageUrl}`);
      return { error: 'blocked', details: { pageTitle, bodySnippet, screenshot: ssPath, url: pageUrl, launchMethod }, wizardLog };
    }

    // --- Set up network interception to capture API responses ---
    // Carvana's frontend makes API calls that return offer data as JSON.
    // Capturing these lets us extract offers even if page selectors change.
    const capturedResponses = [];
    page.on('response', async (response) => {
      const url = response.url();
      // Capture any API responses that might contain offer data
      if (url.includes('/api/') || url.includes('/offer') || url.includes('/appraisal') ||
          url.includes('/vehicle') || url.includes('/valuation') || url.includes('graphql')) {
        try {
          const status = response.status();
          if (status >= 200 && status < 300) {
            const contentType = response.headers()['content-type'] || '';
            if (contentType.includes('json')) {
              const body = await response.text().catch(() => null);
              if (body) {
                capturedResponses.push({ url, status, body: body.substring(0, 5000) });
                // Check for offer-like values in the response
                if (body.includes('offer') || body.includes('price') || body.includes('value') || body.includes('amount')) {
                  log(`[carvana] Captured API response with offer keywords: ${url.substring(0, 100)}`);
                }
              }
            }
          }
        } catch { /* ignore response read errors */ }
      }
    });

    // --- Step 2: Navigate to entry page (license/VIN toggle) and switch to VIN ---
    console.log('[carvana] Step 2: Getting to VIN-entry page...');
    checkTimeout();

    // Carvana's flow is: landing page -> click "Get My Offer" / "Get Started" ->
    // /sell-my-car/getoffer/entry. That entry page has:
    //   - a radio toggle: "License Plate" (default) vs "VIN"
    //   - ONE text input (reused for whichever mode is selected)
    //   - sometimes a "State" dropdown (required in both modes)
    //   - a "Get My Offer" submit button
    //
    // The old wizard detected the single input and immediately tried to fill
    // it with the VIN, failing because License Plate was still selected.
    //
    // Fix strategy:
    //   1. If we're still on /sell-my-car (landing), click Get My Offer to
    //      advance to /getoffer/entry.
    //   2. On /getoffer/entry, click the VIN radio BEFORE touching the input.
    //   3. If a State dropdown is present, pick the consumer's state derived
    //      from their home zip.
    //   4. Fill VIN, then click Get My Offer.
    async function clickLandingGetOffer() {
      const landingCtaSelectors = [
        'a[href*="/getoffer"]',
        'button:has-text("Get My Offer")',
        'button:has-text("Get Started")',
        'a:has-text("Get My Offer")',
        'a:has-text("Get Started")',
      ];
      for (const sel of landingCtaSelectors) {
        try {
          const el = await page.waitForSelector(sel, { timeout: 3000 });
          if (el && await el.isVisible()) {
            await randomMouseMove(page, sel).catch(() => {});
            await humanDelay(600, 1300);
            await el.click();
            log(`[carvana] Clicked landing CTA: ${sel}`);
            return true;
          }
        } catch { /* try next */ }
      }
      return false;
    }

    if (debug) await debugDump(page, 'carvana', 'step1-landing');

    if (page.url().includes('/sell-my-car') && !page.url().includes('/getoffer')) {
      await clickLandingGetOffer();
      await humanDelay(2000, 4000);
      try { await page.waitForURL(/getoffer/i, { timeout: 15000 }); } catch { /* continue anyway */ }
      await screenshot(page, '02-after-landing-cta');
      if (debug) await debugDump(page, 'carvana', 'step2-after-landing-cta');
    }

    // On /getoffer/entry — select the VIN radio BEFORE filling the input.
    // Carvana ships several DOM shapes; try all of them before giving up.
    // The radio group uses role="radio" with aria-label or <label> text.
    const vinRadioSelectors = [
      // Direct radio inputs
      'input[type="radio"][value="VIN"]',
      'input[type="radio"][value="vin"]',
      'input[type="radio"][id*="vin" i]',
      'input[type="radio"][name*="lookup" i][value*="vin" i]',
      // ARIA-based
      '[role="radio"]:has-text("VIN")',
      '[role="tab"]:has-text("VIN")',
      '[role="button"]:has-text("VIN")',
      // Label wrappers
      'label:has-text("VIN")',
      'label[for*="vin" i]',
      // data-testid variants we've seen on Carvana
      '[data-testid*="vin-toggle" i]',
      '[data-testid*="vin-radio" i]',
      '[data-testid*="toggle-vin" i]',
      'button:has-text("VIN")',
    ];

    let vinRadioClicked = false;
    for (const sel of vinRadioSelectors) {
      try {
        const el = await page.waitForSelector(sel, { timeout: 2000 });
        if (el && await el.isVisible()) {
          log(`[carvana] Clicking VIN radio: ${sel}`);
          await randomMouseMove(page, sel).catch(() => {});
          await humanDelay(400, 900);
          // Some radios are hidden-input + styled-label; force check first.
          try { await el.check({ force: true }); vinRadioClicked = true; }
          catch {
            try { await el.click(); vinRadioClicked = true; } catch { /* next */ }
          }
          if (vinRadioClicked) {
            await humanDelay(700, 1500);
            await screenshot(page, '02a-vin-radio-clicked');
            break;
          }
        }
      } catch { /* next */ }
    }
    if (!vinRadioClicked) {
      log('[carvana] VIN radio not found — proceeding (some layouts default to VIN already)');
    }
    if (debug) await debugDump(page, 'carvana', 'step3-vin-radio-state');

    // State dropdown (may or may not be present). Pick consumer's state.
    const stateSelectSelectors = [
      'select[name*="state" i]',
      'select[id*="state" i]',
      'select[aria-label*="state" i]',
      '[data-testid*="state" i] select',
    ];
    for (const sel of stateSelectSelectors) {
      try {
        const dd = await page.waitForSelector(sel, { timeout: 1500 });
        if (dd && await dd.isVisible()) {
          try {
            await dd.selectOption({ value: stateCode });
            log(`[carvana] Selected state by value: ${stateCode}`);
          } catch {
            try {
              await dd.selectOption({ label: stateCode });
              log(`[carvana] Selected state by label: ${stateCode}`);
            } catch (selErr) {
              log(`[carvana] State select failed for ${stateCode}: ${selErr.message}`);
            }
          }
          await humanDelay(500, 1000);
          break;
        }
      } catch { /* no state dropdown; may not be required */ }
    }

    // Custom (non-<select>) state picker: listbox with a button.
    try {
      const stateBtn = await page.$('[aria-label*="state" i][role="button"], button:has-text("Select State"), button:has-text("Choose State")');
      if (stateBtn && await stateBtn.isVisible()) {
        await stateBtn.click();
        await humanDelay(500, 1000);
        const opt = await page.$(`[role="option"]:has-text("${stateCode}"), li:has-text("${stateCode}")`);
        if (opt) {
          await opt.click();
          log(`[carvana] Picked custom state widget: ${stateCode}`);
          await humanDelay(500, 1000);
        }
      }
    } catch { /* no custom state widget */ }

    // Now look for the VIN input field
    const vinSelectors = [
      'input[placeholder*="VIN"]',
      'input[placeholder*="vin"]',
      'input[placeholder*="vehicle identification"]',
      'input[name="vin"]',
      'input[data-testid="vin-input"]',
      'input[data-testid*="vin"]',
      'input[aria-label*="VIN"]',
      '#vin-input',
      '#vin',
    ];

    let vinInput = null;
    for (const sel of vinSelectors) {
      try {
        vinInput = await page.waitForSelector(sel, { timeout: 3000 });
        if (vinInput && await vinInput.isVisible()) {
          console.log(`  [carvana] Found VIN input with selector: ${sel}`);
          break;
        }
        vinInput = null;
      } catch {
        continue;
      }
    }

    // If no specific VIN input found, try the general text input (but only if we see VIN-related content)
    if (!vinInput) {
      // Fallback: try Playwright locator methods
      try {
        const byPlaceholder = page.getByPlaceholder(/vin/i);
        await byPlaceholder.waitFor({ timeout: 5000 });
        vinInput = await byPlaceholder.elementHandle();
      } catch {
        // last resort
      }
    }

    if (!vinInput) {
      await screenshot(page, 'no-vin-input');
      log('[carvana] FAIL: no VIN input element found at /getoffer/entry');
      return { error: 'Could not find VIN input field. Selectors may need updating.', wizardLog };
    }

    await randomMouseMove(page, vinSelectors[0]).catch(() => {});
    await humanDelay(1000, 2000);
    await vinInput.click();
    // Type VIN character by character with background mouse drift — typing
    // while the mouse is frozen is a strong robot signal.
    const stopDrift = startMouseDrift(page);
    try {
      for (const char of vin) {
        await vinInput.type(char, { delay: 0 });
        await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 100) + 50));
      }
    } finally {
      stopDrift();
    }
    await humanDelay(1000, 2000);
    await screenshot(page, '02-vin-entered');

    // Submit VIN — try button click or Enter key
    const vinSubmitSelectors = [
      'button[type="submit"]',
      'button:has-text("Get Offer")',
      'button:has-text("Next")',
      'button:has-text("Continue")',
      'button:has-text("Get My Offer")',
      'button:has-text("Get Started")',
    ];

    let submitted = false;
    for (const sel of vinSubmitSelectors) {
      try {
        const btn = await page.waitForSelector(sel, { timeout: 3000 });
        if (btn) {
          await randomMouseMove(page, sel).catch(() => {});
          await humanDelay(500, 1000);
          await btn.click();
          submitted = true;
          console.log(`  [carvana] Submitted VIN with button: ${sel}`);
          break;
        }
      } catch {
        continue;
      }
    }

    if (!submitted) {
      await page.keyboard.press('Enter');
      console.log('  [carvana] Submitted VIN with Enter key');
    }

    await humanDelay(4000, 7000);
    await screenshot(page, '03-after-vin-submit');
    if (debug) await debugDump(page, 'carvana', 'step4-after-vin-submit');
    checkTimeout();

    // Cloudflare commonly re-challenges after form POST with an interactive
    // Turnstile ("Verify you are human"). Click the checkbox via real pixel
    // coordinates on the main page — cross-origin iframe DOM access is blocked,
    // but a mouse event at the iframe's bounding box still lands inside it.
    if (await isBlocked(page)) {
      await screenshot(page, 'blocked-after-vin');
      log('[carvana] Cloudflare challenge after VIN submit — attempting click + wait up to 90s...');
      let postVinResolved = false;
      let clickAttempts = 0;
      for (let waited = 0; waited < 90; waited += 5) {
        await humanDelay(4500, 5500);
        if (waited % 15 === 0) {
          await simulateHumanBehavior(page);
        }

        // On first iteration, dump iframe diagnostics so we know what we're
        // dealing with — CF full-page managed challenges proxy the iframe
        // via the target domain (e.g. carvana.com/cdn-cgi/...), not the
        // challenges.cloudflare.com domain.
        if (waited === 0) {
          try {
            const iframeInfo = await page.$$eval('iframe', (els) =>
              els.map((el) => ({
                src: (el.src || '').substring(0, 120),
                title: (el.title || '').substring(0, 60),
                id: el.id || '',
                name: el.name || '',
                w: el.getBoundingClientRect().width,
                h: el.getBoundingClientRect().height,
                x: el.getBoundingClientRect().x,
                y: el.getBoundingClientRect().y,
              }))
            );
            log(`[carvana] Post-VIN iframe dump: ${JSON.stringify(iframeInfo)}`);
          } catch (diagErr) { log(`[carvana] iframe dump failed: ${diagErr.message}`); }
        }

        // Try pixel-coordinate click on the challenge iframe (max 3 attempts,
        // spaced out — clicking repeatedly can trigger "too many attempts").
        // Broadened detection: CF managed-challenge iframes are often served
        // via the target domain (same-origin), not challenges.cloudflare.com.
        if (clickAttempts < 3) {
          try {
            let iframeHandle = await page.$(
              'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], iframe[src*="cdn-cgi/challenge"], iframe[title*="Widget containing"], iframe[title*="challenge"]'
            );
            // Fallback: any visible iframe small enough to be a widget (not
            // a full-page tracking iframe — those are 0x0 or very large).
            if (!iframeHandle) {
              const candidates = await page.$$('iframe');
              for (const cand of candidates) {
                const box = await cand.boundingBox().catch(() => null);
                if (box && box.width > 200 && box.width < 500 && box.height > 40 && box.height < 150) {
                  iframeHandle = cand;
                  log(`[carvana] Fallback iframe candidate: ${Math.round(box.width)}x${Math.round(box.height)} at (${Math.round(box.x)},${Math.round(box.y)})`);
                  break;
                }
              }
            }
            if (iframeHandle) {
              const box = await iframeHandle.boundingBox();
              if (box && box.width > 50 && box.height > 20) {
                // Checkbox sits ~30px from left, vertically centered in the widget
                const clickX = box.x + 30 + Math.random() * 6;
                const clickY = box.y + box.height / 2 + (Math.random() * 4 - 2);
                log(`[carvana] Turnstile iframe at (${Math.round(box.x)},${Math.round(box.y)}) ${Math.round(box.width)}x${Math.round(box.height)} — clicking checkbox at (${Math.round(clickX)},${Math.round(clickY)})`);
                await page.mouse.move(clickX - 200, clickY - 80, { steps: 8 });
                await humanDelay(400, 900);
                await page.mouse.move(clickX - 40, clickY - 10, { steps: 6 });
                await humanDelay(200, 500);
                await page.mouse.move(clickX, clickY, { steps: 4 });
                await humanDelay(150, 350);
                await page.mouse.down();
                await humanDelay(60, 140);
                await page.mouse.up();
                clickAttempts++;
                await screenshot(page, `turnstile-click-${clickAttempts}`);
                // Give Cloudflare ~6s to verify after the click before next check
                await humanDelay(5500, 6500);
              }
            }
          } catch (clickErr) {
            log(`[carvana] Turnstile click attempt failed: ${clickErr.message}`);
          }
        }

        if (!(await isBlocked(page))) {
          postVinResolved = true;
          log(`[carvana] Post-VIN challenge cleared after ~${waited + 5}s (${clickAttempts} click attempt(s))`);
          break;
        }
        log(`[carvana] Post-VIN still blocked after ${waited + 5}s (clicks=${clickAttempts})...`);
      }
      if (!postVinResolved) {
        await screenshot(page, 'blocked-after-vin-final');
        return { error: 'blocked', details: { at: 'post-vin', clickAttempts }, wizardLog };
      }
      await screenshot(page, '03b-after-vin-unblocked');
    }

    // --- Steps 3-7: Navigate through Carvana's multi-step wizard ---
    // The flow is URL-based: /getoffer/vehicle, /getoffer/mileage, etc.
    // Instead of hardcoded steps, we adaptively handle whatever page appears.
    console.log('[carvana] Steps 3-7: Navigating wizard...');

    const submitSelectors = [
      'button[type="submit"]',
      'button:has-text("Get Offer")',
      'button:has-text("Next")',
      'button:has-text("Continue")',
      'button:has-text("Get My Offer")',
      'button:has-text("Get Started")',
      'button:has-text("Submit")',
      'button:has-text("Confirm")',
      'button:has-text("Yes")',
      'button:has-text("See Offer")',
      'button:has-text("View Offer")',
    ];

    // Generic "click through the wizard" loop — handles up to 18 pages.
    // Track per-build-page "did we satisfy required fields" so we don't loop
    // clicking a disabled Continue button (Carvana's /getoffer/build flow has
    // 4 sub-pages: color → features → modifications → keys/title — each
    // requires its own answers before Continue enables).
    let stuckCount = 0;
    const buildPagesAnswered = new Set();
    for (let step = 0; step < 18; step++) {
      checkTimeout();
      const currentUrl = page.url();
      log(`[carvana] Wizard step ${step}: URL = ${currentUrl}`);
      await screenshot(page, `wizard-${step}`);
      if (debug) await debugDump(page, 'carvana', `wizard-${step}`);

      // Log all visible buttons and inputs for diagnostics
      try {
        const buttons = await page.$$eval('button:visible, a[role="button"]:visible', els =>
          els.slice(0, 15).map(e => e.textContent.trim().substring(0, 60))
        );
        const inputs = await page.$$eval('input:visible, select:visible, textarea:visible', els =>
          els.slice(0, 10).map(e => `${e.tagName}[name=${e.name||'?'},type=${e.type||'?'},placeholder=${(e.placeholder||'').substring(0,30)}]`)
        );
        log(`  Visible buttons: ${JSON.stringify(buttons)}`);
        log(`  Visible inputs: ${JSON.stringify(inputs)}`);
      } catch (diagErr) {
        log(`  Diag error: ${diagErr.message}`);
      }

      // Check if we've reached the offer page (contains dollar amount)
      try {
        const bodyText = await page.textContent('body');
        const dollarMatch = bodyText.match(/\$\s?[\d,]{3,}/g);
        if (dollarMatch && dollarMatch.length > 0) {
          const amounts = dollarMatch.map((s) => parseInt(s.replace(/[$,\s]/g, ''), 10));
          const maxAmount = Math.max(...amounts);
          if (maxAmount > 500) {
            log(`[carvana] OFFER FOUND on wizard step ${step}: $${maxAmount.toLocaleString()}`);
            break; // Exit wizard loop — we have an offer
          }
        }
      } catch {
        // Continue
      }

      if (await isBlocked(page)) {
        log('[carvana] Cloudflare challenge detected mid-wizard — waiting for resolution...');
        await screenshot(page, `blocked-wizard-${step}`);
        // Wait up to 30s for it to resolve
        let wizardResolved = false;
        for (let w = 0; w < 6; w++) {
          await humanDelay(4500, 5500);
          if (!(await isBlocked(page))) { wizardResolved = true; break; }
        }
        if (!wizardResolved) {
          return { error: 'blocked', details: { vin, mileage, zip, blockedAtStep: step }, wizardLog };
        }
        log('[carvana] Challenge resolved mid-wizard, continuing...');
      }

      // Try to detect and fill the current page's form
      let interacted = false;

      // Look for a mileage input
      const mileageInput = await page.$('input[placeholder*="ileage"], input[placeholder*="miles"], input[name="mileage"], input[data-testid*="mileage"], input[aria-label*="ileage"]');
      if (mileageInput && await mileageInput.isVisible()) {
        log(`  Found mileage input — entering ${mileage}`);
        await mileageInput.click();
        await mileageInput.fill('');
        for (const char of String(mileage)) {
          await mileageInput.type(char, { delay: 0 });
          await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 80) + 40));
        }
        interacted = true;
        await humanDelay(1000, 2000);
      }

      // Look for a zip code input
      const zipInput = await page.$('input[placeholder*="ip"], input[placeholder*="zip"], input[name="zip"], input[name="zipCode"], input[data-testid*="zip"], input[maxlength="5"][inputmode="numeric"]');
      if (zipInput && await zipInput.isVisible()) {
        log(`  Found zip input — entering ${zip}`);
        await zipInput.click();
        await zipInput.fill('');
        for (const char of String(zip)) {
          await zipInput.type(char, { delay: 0 });
          await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 80) + 40));
        }
        interacted = true;
        await humanDelay(1000, 2000);
      }

      // Look for an email input
      const emailInput = await page.$('input[type="email"], input[placeholder*="mail"], input[name="email"]');
      if (emailInput && await emailInput.isVisible()) {
        log(`  Found email input — entering ${offerEmail}`);
        await emailInput.click();
        await emailInput.fill('');
        for (const char of offerEmail) {
          await emailInput.type(char, { delay: 0 });
          await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 60) + 30));
        }
        interacted = true;
        await humanDelay(1000, 2000);
      }

      // Look for select/dropdown elements (trim, color, etc.)
      try {
        const selects = await page.$$('select:visible');
        for (const sel of selects) {
          const options = await sel.$$eval('option', opts => opts.map(o => ({ value: o.value, text: o.textContent.trim() })));
          if (options.length > 1) {
            // Select the first non-empty option
            const pick = options.find(o => o.value && o.value !== '') || options[1];
            if (pick) {
              await sel.selectOption(pick.value);
              log(`  Selected dropdown option: "${pick.text}"`);
              interacted = true;
              await humanDelay(500, 1000);
            }
          }
        }
      } catch {
        // Continue
      }

      // Carvana /getoffer/build sub-pages — they ALL render Exit/Back/Continue
      // buttons + various widgets per step. Detect by URL + heading.
      // Step A: "Vehicle build" → color dropdown (custom widget) +
      //         "No modifications" button. Pick gray/silver as a safe default.
      // Step B: "Vehicle features" → checkboxes (leave unchecked = stock).
      // Step C: "Vehicle condition" → mileage, accident, key count, title.
      // Step D: "Mileage / Final touches" → mileage input + zip if missing.
      if (currentUrl.includes('/getoffer/build') && !buildPagesAnswered.has(currentUrl + '|' + step)) {
        try {
          const headingText = await page.textContent('h1, h2, [class*="title"], [class*="heading"]')
            .then(t => (t || '').trim().slice(0, 80))
            .catch(() => '');
          log(`  /getoffer/build heading: "${headingText}"`);

          // Color picker: look for a custom dropdown trigger
          const pageText = (await page.textContent('body').catch(() => '') || '').toLowerCase();
          if (pageText.includes('color') || pageText.includes('exterior color')) {
            const colorPicked = await pickDropdownOption(page, [
              'select[name*="color" i]',
              'select[id*="color" i]',
              'select[aria-label*="color" i]',
              '[role="combobox"][aria-label*="color" i]',
              'button[aria-label*="color" i]',
              'button:has-text("Exterior color")',
              'button:has-text("Select color")',
              'div[role="button"]:has-text("Exterior color")',
              // generic combobox/select on the page
              '[role="combobox"]',
              'select:visible',
            ], ['Gray', 'Silver', 'White', 'Black', 'Blue', 'Red'], 1500);
            if (colorPicked.selected) {
              log(`  Carvana color picked: ${colorPicked.label}`);
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|color');
              await humanDelay(500, 1000);
            }
          }

          // Modifications question — pick "No modifications".
          if (pageText.includes('modifications') || pageText.includes('modified')) {
            const modBtn = await page.$('button:has-text("No modifications"), button:has-text("No Modifications"), button:has-text("No"), label:has-text("No modifications")');
            if (modBtn && await modBtn.isVisible()) {
              await humanDelay(400, 900);
              await modBtn.click();
              log('  Carvana: clicked "No modifications"');
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|mods');
              await humanDelay(500, 1000);
            }
          }

          // Keys question — pick "2 keys" (most common stock answer).
          if (pageText.includes('how many keys') || pageText.includes('number of keys')) {
            const keysBtn = await page.$('button:has-text("2"), button:has-text("Two")');
            if (keysBtn && await keysBtn.isVisible()) {
              await humanDelay(400, 900);
              await keysBtn.click();
              log('  Carvana: keys = 2');
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|keys');
              await humanDelay(500, 1000);
            }
          }

          // Title status — pick clean
          if (pageText.includes('title') && (pageText.includes('clean') || pageText.includes('salvage'))) {
            const titleBtn = await page.$('button:has-text("Clean"), label:has-text("Clean")');
            if (titleBtn && await titleBtn.isVisible()) {
              await humanDelay(400, 900);
              await titleBtn.click();
              log('  Carvana: title = clean');
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|title');
              await humanDelay(500, 1000);
            }
          }

          // Accident history — pick None / no accidents
          if (pageText.includes('accident') || pageText.includes('been in')) {
            const noAccBtn = await page.$('button:has-text("No accidents"), button:has-text("None"), button:has-text("No, no accidents"), label:has-text("No accidents")');
            if (noAccBtn && await noAccBtn.isVisible()) {
              await humanDelay(400, 900);
              await noAccBtn.click();
              log('  Carvana: accidents = none');
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|accidents');
              await humanDelay(500, 1000);
            }
          }

          // Loan / payoff — pick "Own outright" / "No loan"
          if (pageText.includes('loan') || pageText.includes('payoff')) {
            const ownBtn = await page.$('button:has-text("Own outright"), button:has-text("Own it"), button:has-text("No loan"), button:has-text("Paid off")');
            if (ownBtn && await ownBtn.isVisible()) {
              await humanDelay(400, 900);
              await ownBtn.click();
              log('  Carvana: ownership = own outright');
              interacted = true;
              buildPagesAnswered.add(currentUrl + '|own');
              await humanDelay(500, 1000);
            }
          }
        } catch (buildErr) {
          log(`  /getoffer/build interaction error: ${buildErr.message}`);
        }
      }

      // Look for vehicle confirmation buttons (after VIN submit, Carvana shows vehicle details)
      // Must come before generic condition buttons to avoid false matches
      const confirmSelectors = [
        'button:has-text("This is my")', 'button:has-text("Looks right")',
        'button:has-text("Yes, this")', 'button:has-text("That\'s my")',
        'button:has-text("Correct")', 'button:has-text("Confirm")',
        'a:has-text("This is my")', 'a:has-text("Looks right")',
        // Carvana-specific: clickable cards/tiles for trim or vehicle selection
        '[data-testid*="vehicle"] button', '[data-testid*="trim"] button',
        '[data-testid*="confirm"]', '[data-testid*="vehicle-card"]',
        // Generic card/tile patterns (React-based auto sites often use these)
        '[class*="vehicle-card"]', '[class*="trim-card"]', '[class*="selection-card"]',
        'div[role="button"]', 'li[role="option"]',
      ];
      for (const sel of confirmSelectors) {
        try {
          const btn = await page.$(sel);
          if (btn && await btn.isVisible()) {
            await humanDelay(800, 1500);
            await btn.click();
            log(`  Confirmed vehicle: ${sel}`);
            interacted = true;
            break;
          }
        } catch { continue; }
      }

      // If still no interaction on /getoffer/vehicle, try clicking any clickable card-like element
      if (!interacted && currentUrl.includes('/getoffer/vehicle')) {
        try {
          // Look for clickable cards that contain vehicle info (year/make/model text)
          const cards = await page.$$('[class*="card"]:visible, [class*="tile"]:visible, [class*="option"]:visible, [class*="select"]:visible');
          for (const card of cards) {
            const text = await card.textContent().catch(() => '');
            // Click the first card that looks like vehicle info
            if (text && (text.match(/\d{4}/) || text.match(/accord|honda|touring/i))) {
              await humanDelay(800, 1500);
              await card.click();
              log(`  Clicked vehicle card: "${text.trim().substring(0, 60)}"`);
              interacted = true;
              break;
            }
          }
        } catch { /* continue */ }
      }

      // Look for condition/selection buttons — use specific phrases to avoid false matches
      if (!interacted) {
        const conditionKeywords = ['Good', 'Excellent', 'No accidents', 'No damage', 'Clean title', 'None', 'No issues'];
        for (const keyword of conditionKeywords) {
          try {
            const btns = await page.$$(`button:has-text("${keyword}"), label:has-text("${keyword}"), [role="radio"]:has-text("${keyword}"), [role="option"]:has-text("${keyword}")`);
            for (const btn of btns) {
              if (await btn.isVisible()) {
                await humanDelay(800, 1500);
                await btn.click();
                log(`  Selected condition: "${keyword}"`);
                interacted = true;
                break;
              }
            }
            if (interacted) break;
          } catch {
            continue;
          }
        }
      }

      // Look for "sell" option (Carvana asks: sell, trade-in, or not sure)
      if (!interacted) {
        const sellKeywords = ['Just sell', 'Sell', 'Sell my car', 'Not sure'];
        for (const keyword of sellKeywords) {
          try {
            const btns = await page.$$(`button:has-text("${keyword}"), label:has-text("${keyword}"), [role="radio"]:has-text("${keyword}"), a:has-text("${keyword}")`);
            for (const btn of btns) {
              if (await btn.isVisible()) {
                await humanDelay(800, 1500);
                await btn.click();
                log(`  Selected sell option: "${keyword}"`);
                interacted = true;
                break;
              }
            }
            if (interacted) break;
          } catch {
            continue;
          }
        }
      }

      // Look for loan/payoff question (common wizard step)
      if (!interacted) {
        const loanKeywords = ['No loan', 'No, I own', 'Paid off', 'I own it', 'No payoff'];
        for (const keyword of loanKeywords) {
          try {
            const btn = await page.$(`button:has-text("${keyword}"), label:has-text("${keyword}"), [role="radio"]:has-text("${keyword}")`);
            if (btn && await btn.isVisible()) {
              await humanDelay(800, 1500);
              await btn.click();
              log(`  Selected loan option: "${keyword}"`);
              interacted = true;
              break;
            }
          } catch { continue; }
        }
      }

      // Try to click a submit/next/continue button — but skip disabled ones
      // (the build flow disables Continue until required fields are answered).
      let clickedSubmit = false;
      for (const sel of submitSelectors) {
        try {
          // Use :not([disabled]) and aria-disabled exclusion to dodge greyed-out CTAs
          const enabledSel = `${sel}:not([disabled]):not([aria-disabled="true"])`;
          const btn = await page.waitForSelector(enabledSel, { timeout: 2000 });
          if (btn && await btn.isVisible()) {
            await randomMouseMove(page, enabledSel).catch(() => {});
            await humanDelay(800, 1500);
            await btn.click();
            clickedSubmit = true;
            log(`  Clicked submit: ${enabledSel}`);
            break;
          }
        } catch {
          continue;
        }
      }
      if (!clickedSubmit) {
        // Diagnostic: report disabled buttons so we know what we're stuck on
        try {
          const disabledBtns = await page.$$eval('button[disabled], button[aria-disabled="true"]', els =>
            els.slice(0, 5).map(e => e.textContent.trim().slice(0, 40))
          );
          if (disabledBtns.length > 0) {
            log(`  No enabled submit. Disabled buttons present: ${JSON.stringify(disabledBtns)}`);
          }
        } catch { /* ok */ }
      }

      // If we didn't interact at all, try pressing Enter as last resort
      if (!interacted && !clickedSubmit) {
        // Look for any visible primary-looking button
        try {
          const anyButton = await page.$('button:visible');
          if (anyButton) {
            const btnText = await anyButton.textContent();
            log(`  Clicking visible button: "${btnText.trim().substring(0, 50)}"`);
            await anyButton.click();
            clickedSubmit = true;
          }
        } catch {
          await page.keyboard.press('Enter');
          log('  Pressed Enter (no buttons found)');
        }
      }

      // Wait for page navigation or content update
      await humanDelay(3000, 6000);

      // Check if URL changed (wizard progressed to next step)
      const newUrl = page.url();
      if (newUrl !== currentUrl) {
        log(`  Page navigated: ${newUrl}`);
        stuckCount = 0; // Reset stuck counter on progress
      } else if (!interacted && !clickedSubmit) {
        stuckCount++;
        log(`  No progress (stuck count: ${stuckCount})`);
        if (stuckCount >= 3) {
          log('  Stuck 3 times — breaking to offer check');
          break;
        }
      } else {
        // We interacted but URL didn't change — might be filling a multi-field form
        log('  Interacted but URL unchanged (multi-field page?)');
      }
    }

    checkTimeout();
    await screenshot(page, '08-pre-offer');

    // --- Step 8: Wait for offer ---
    console.log('[carvana] Step 8: Waiting for offer calculation...');

    // Wait up to 45 seconds for the offer to appear
    const offerSelectors = [
      '[data-testid="offer-amount"]',
      '[class*="offer"]',
      '[class*="price"]',
      'h1:has-text("$")',
      'h2:has-text("$")',
      'span:has-text("$")',
      '[class*="amount"]',
    ];

    let offerText = null;

    // Poll for the offer amount
    const offerDeadline = Date.now() + 45000;
    while (Date.now() < offerDeadline && elapsed() < TOTAL_TIMEOUT) {
      if (await isBlocked(page)) {
        await screenshot(page, 'blocked-waiting-offer');
        return { error: 'blocked', wizardLog };
      }

      for (const sel of offerSelectors) {
        try {
          const el = await page.$(sel);
          if (el) {
            const text = await el.textContent();
            const dollarMatch = text.match(/\$[\d,]+/);
            if (dollarMatch) {
              offerText = dollarMatch[0];
              console.log(`  [carvana] Found offer: ${offerText}`);
              break;
            }
          }
        } catch {
          continue;
        }
      }

      if (offerText) break;

      // Also try scanning the full page for a dollar amount
      try {
        const bodyText = await page.textContent('body');
        const bigDollar = bodyText.match(/\$\s?[\d,]{3,}/g);
        if (bigDollar && bigDollar.length > 0) {
          // Take the largest dollar amount as the likely offer
          const amounts = bigDollar.map((s) => parseInt(s.replace(/[$,\s]/g, ''), 10));
          const maxAmount = Math.max(...amounts);
          if (maxAmount > 500) {
            offerText = `$${maxAmount.toLocaleString()}`;
            console.log(`  [carvana] Found offer from body scan: ${offerText}`);
            break;
          }
        }
      } catch {
        // ignore
      }

      await new Promise((r) => setTimeout(r, 3000));
    }

    await screenshot(page, '08-offer-result');

    // If no offer found in the DOM, check captured API responses
    if (!offerText && capturedResponses.length > 0) {
      log(`[carvana] Checking ${capturedResponses.length} captured API responses for offer data...`);
      for (const resp of capturedResponses) {
        try {
          const data = JSON.parse(resp.body);
          // Look for common offer field names in JSON responses
          const offerValue = data.offer || data.offerAmount || data.price ||
            data.value || data.appraisalValue || data.estimatedValue ||
            (data.data && (data.data.offer || data.data.price || data.data.value));
          if (offerValue && typeof offerValue === 'number' && offerValue > 500) {
            offerText = `$${offerValue.toLocaleString()}`;
            log(`[carvana] OFFER FROM API: ${offerText} (source: ${resp.url.substring(0, 80)})`);
            break;
          }
          // Also scan JSON string for dollar amounts
          const jsonStr = JSON.stringify(data);
          const dollarMatch = jsonStr.match(/\$[\d,]{3,}/);
          if (dollarMatch) {
            const amount = parseInt(dollarMatch[0].replace(/[$,]/g, ''), 10);
            if (amount > 500) {
              offerText = dollarMatch[0];
              log(`[carvana] OFFER FROM API JSON: ${offerText} (source: ${resp.url.substring(0, 80)})`);
              break;
            }
          }
        } catch { /* not valid JSON or no matching fields */ }
      }
    }

    if (!offerText) {
      const finalScreenshot = await screenshot(page, '09-no-offer');
      let pageState = {};
      try {
        pageState.url = page.url();
        pageState.title = await page.title().catch(() => 'unknown');
        pageState.bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 1000)).catch(() => '');
        console.log(`[carvana] NO OFFER FOUND — page state:`);
        console.log(`  url: ${pageState.url}`);
        console.log(`  title: ${pageState.title}`);
        console.log(`  body: ${pageState.bodySnippet.substring(0, 500)}`);
      } catch (_) {}
      return {
        error: 'Could not extract offer amount. The page may have changed or the flow was interrupted.',
        details: { vin, mileage, zip, pageState, capturedApiCount: capturedResponses.length, launchMethod },
        wizardLog,
        screenshot: finalScreenshot,
      };
    }

    return {
      offer: offerText,
      details: {
        vin,
        mileage,
        zip,
        source: 'carvana',
        timestamp: new Date().toISOString(),
        capturedApiCount: capturedResponses.length,
        launchMethod,
      },
      wizardLog,
    };
  } catch (err) {
    console.error(`[carvana] Error: ${err.message}`);
    return {
      error: err.message,
      details: { vin, mileage, zip },
      wizardLog,
    };
  } finally {
    await closeBrowser(browser);
    console.log(`[carvana] Flow completed in ${Math.round(elapsed() / 1000)}s`);
  }
}

async function getCarvanaOffer(params) {
  if (activeRun) {
    console.log('[carvana] Another run in progress — queuing (waiting up to 5 min)...');
    try { await Promise.race([activeRun, new Promise((_, rej) => setTimeout(() => rej(new Error('queue timeout')), 300_000))]); }
    catch (e) { console.log(`[carvana] Queue wait ended: ${e.message}`); }
  }
  activeRun = (async () => {
    try { return await _getCarvanaOfferImpl(params); }
    finally { activeRun = null; }
  })();
  return activeRun;
}

module.exports = { getCarvanaOffer };
