const { launchBrowser, humanDelay, humanType, randomMouseMove, closeBrowser, simulateHumanBehavior } = require('./browser');
const config = require('./config');
const path = require('path');

const CARVANA_URL = 'https://www.carvana.com/sell-my-car';
const TOTAL_TIMEOUT = 300_000; // 5 minutes total (IP hunt + proxy latency)

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
    'blocked',
    'access denied',
    'challenge-running',
    'cf-browser-verification',
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
async function getCarvanaOffer({ vin, mileage, zip, email }) {
  const offerEmail = email || config.PROJECT_EMAIL || 'caroffers.tool@gmail.com';
  if (!offerEmail) {
    return { error: 'No email configured. Set PROJECT_EMAIL in .env' };
  }

  let browser = null;
  const startTime = Date.now();
  const wizardLog = []; // Capture wizard diagnostics for return value

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

    // --- Launch initial browser (will be replaced during US IP hunt) ---
    let result;
    let page;
    try {
      result = await launchBrowser();
    } catch (launchErr) {
      console.error(`[carvana] Browser launch failed: ${launchErr.message}`);
      throw launchErr;
    }
    browser = result.browser;
    page = result.page;

    // --- Step 1: Warm up browser session with non-Carvana sites ---
    // Visiting a few benign sites first builds a more realistic browser fingerprint
    // and lets Cloudflare see normal navigation patterns before hitting the target
    log('[carvana] Step 1: Warming up browser session...');
    try {
      await page.goto('https://www.google.com', { timeout: 20000, waitUntil: 'domcontentloaded' });
      await humanDelay(2000, 4000);
      await simulateHumanBehavior(page);
      log('[carvana] Warmup: visited Google');
    } catch { log('[carvana] Warmup: Google failed (non-fatal)'); }
    await humanDelay(3000, 5000);

    // Verify US IP via ip.decodo.com (optional — curl already confirmed)
    try {
      await page.goto('https://ip.decodo.com/json', { timeout: 20000 });
      const ipInfo = await page.textContent('body');
      log(`[carvana] Proxy IP info: ${ipInfo.substring(0, 200)}`);
    } catch (proxyErr) {
      log(`[carvana] Proxy verification skipped: ${proxyErr.message}`);
    }
    await humanDelay(3000, 5000);

    // --- Navigate to Carvana with retry logic for Cloudflare challenges ---
    log('[carvana] Navigating to Carvana sell page...');

    let carvanaLoaded = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await page.goto(CARVANA_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
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

      // Cloudflare detected — try to handle the challenge
      log(`[carvana] Cloudflare challenge detected (attempt ${attempt})`);
      await screenshot(page, `blocked-attempt-${attempt}`);

      // Try to find and interact with Cloudflare Turnstile/challenge widget
      // Cloudflare uses an iframe for its challenge — we need to click inside it
      try {
        const cfFrames = page.frames().filter(f =>
          f.url().includes('challenges.cloudflare.com') ||
          f.url().includes('turnstile') ||
          f.url().includes('cf-chl')
        );
        log(`[carvana] Found ${cfFrames.length} Cloudflare challenge frames`);
        for (const frame of cfFrames) {
          try {
            // Look for the checkbox/verify button inside the challenge iframe
            const checkbox = await frame.$('input[type="checkbox"], .cb-i, #challenge-stage, .spacer');
            if (checkbox) {
              log('[carvana] Found Cloudflare checkbox — clicking...');
              await humanDelay(1000, 2000);
              await checkbox.click();
              await humanDelay(5000, 10000);
            }
            // Some challenges just have a "Verify" button
            const verifyBtn = await frame.$('button, input[type="submit"]');
            if (verifyBtn) {
              log('[carvana] Found Cloudflare verify button — clicking...');
              await humanDelay(1000, 2000);
              await verifyBtn.click();
              await humanDelay(5000, 10000);
            }
          } catch (frameErr) {
            log(`[carvana] Challenge frame interaction failed: ${frameErr.message}`);
          }
        }
      } catch (cfErr) {
        log(`[carvana] Cloudflare frame detection failed: ${cfErr.message}`);
      }

      // Wait for the challenge to resolve (JS execution + potential redirect)
      const waitSecs = [20, 30, 45][attempt] || 45;
      log(`[carvana] Waiting ${waitSecs}s for challenge resolution...`);

      // Try waitForURL — if Cloudflare resolves, the URL will change
      try {
        await page.waitForURL('**/sell-my-car**', { timeout: waitSecs * 1000 });
        log('[carvana] URL changed — challenge may have resolved');
      } catch {
        // URL didn't change — continue with human simulation
        for (let w = 0; w < Math.floor(waitSecs / 10); w++) {
          await humanDelay(8000, 12000);
          await simulateHumanBehavior(page);
        }
      }

      // Check if challenge resolved
      if (!(await isBlocked(page))) {
        carvanaLoaded = true;
        log('[carvana] Cloudflare challenge resolved!');
        break;
      }

      // Try refreshing the page for next attempt
      if (attempt < 2) {
        log('[carvana] Refreshing for next attempt...');
        await humanDelay(5000, 10000);
      }
    }

    if (!carvanaLoaded) {
      const ssPath = await screenshot(page, 'blocked-final');
      const pageTitle = await page.title().catch(() => 'unknown');
      const bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 500)).catch(() => '');
      const pageUrl = page.url();
      log(`[carvana] BLOCKED after all attempts — title: ${pageTitle}, url: ${pageUrl}`);
      return { error: 'blocked', details: { pageTitle, bodySnippet, screenshot: ssPath, url: pageUrl }, wizardLog };
    }

    // --- Step 2: Switch to VIN tab and enter VIN ---
    console.log('[carvana] Step 2: Looking for VIN entry...');
    checkTimeout();

    // Carvana shows license plate input by default. VIN is on a secondary tab.
    // Look for a VIN tab/button to click first.
    const vinTabSelectors = [
      'button:has-text("VIN")',
      'a:has-text("VIN")',
      '[role="tab"]:has-text("VIN")',
      'label:has-text("VIN")',
      'span:has-text("VIN")',
      '[data-testid*="vin-tab"]',
      '[data-testid*="vin"]',
    ];

    for (const sel of vinTabSelectors) {
      try {
        const tab = await page.waitForSelector(sel, { timeout: 3000 });
        if (tab && await tab.isVisible()) {
          console.log(`  [carvana] Found VIN tab: ${sel} — clicking...`);
          await randomMouseMove(page, sel).catch(() => {});
          await humanDelay(500, 1000);
          await tab.click();
          await humanDelay(1000, 2000);
          await screenshot(page, '02-vin-tab-clicked');
          break;
        }
      } catch {
        continue;
      }
    }

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
      return { error: 'Could not find VIN input field. Selectors may need updating.' };
    }

    await randomMouseMove(page, vinSelectors[0]).catch(() => {});
    await humanDelay(1000, 2000);
    await vinInput.click();
    // Type VIN character by character
    for (const char of vin) {
      await vinInput.type(char, { delay: 0 });
      await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 100) + 50));
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
    checkTimeout();

    if (await isBlocked(page)) {
      await screenshot(page, 'blocked-after-vin');
      return { error: 'blocked', wizardLog };
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

    // Generic "click through the wizard" loop — handles up to 15 pages
    let stuckCount = 0;
    for (let step = 0; step < 15; step++) {
      checkTimeout();
      const currentUrl = page.url();
      log(`[carvana] Wizard step ${step}: URL = ${currentUrl}`);
      await screenshot(page, `wizard-${step}`);

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
        console.log('[carvana] Blocked during wizard navigation');
        await screenshot(page, 'blocked-wizard');
        return { error: 'blocked', details: { vin, mileage, zip }, wizardLog };
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

      // Try to click a submit/next/continue button
      let clickedSubmit = false;
      for (const sel of submitSelectors) {
        try {
          const btn = await page.waitForSelector(sel, { timeout: 2000 });
          if (btn && await btn.isVisible()) {
            await randomMouseMove(page, sel).catch(() => {});
            await humanDelay(800, 1500);
            await btn.click();
            clickedSubmit = true;
            log(`  Clicked submit: ${sel}`);
            break;
          }
        } catch {
          continue;
        }
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

    if (!offerText) {
      const finalScreenshot = await screenshot(page, '09-no-offer');
      // Capture diagnostic info about what page we're actually on
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
        details: { vin, mileage, zip, pageState },
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

module.exports = { getCarvanaOffer };
