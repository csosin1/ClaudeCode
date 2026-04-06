const { launchBrowser, humanDelay, humanType, randomMouseMove, closeBrowser } = require('./browser');
const config = require('./config');
const path = require('path');

const CARVANA_URL = 'https://www.carvana.com/sell-my-car';
const TOTAL_TIMEOUT = 180_000; // 3 minutes total (proxy adds latency)

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
  const html = await page.content();
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

  function elapsed() {
    return Date.now() - startTime;
  }

  function checkTimeout() {
    if (elapsed() > TOTAL_TIMEOUT) {
      throw new Error('Total timeout exceeded (120s)');
    }
  }

  try {
    console.log(`[carvana] Starting offer flow for VIN=${vin} mileage=${mileage} zip=${zip}`);
    console.log(`[carvana] Proxy: host=${config.PROXY_HOST} port=${config.PROXY_PORT} user=${config.PROXY_USER} pass=${config.PROXY_PASS ? config.PROXY_PASS.length + 'chars' : 'NONE'}`);

    // --- Launch browser ---
    let result;
    try {
      result = await launchBrowser();
    } catch (launchErr) {
      console.error(`[carvana] Browser launch failed: ${launchErr.message}`);
      throw launchErr;
    }
    browser = result.browser;
    const page = result.page;

    // --- Step 1: Navigate to sell-my-car ---
    console.log('[carvana] Step 1: Navigating to Carvana sell page...');
    // Verify proxy is working by checking our IP
    try {
      console.log('[carvana] Verifying proxy connection...');
      await page.goto('http://httpbin.org/ip', { timeout: 20000 });
      const ipInfo = await page.textContent('body');
      console.log(`[carvana] Proxy IP info: ${ipInfo}`);
    } catch (proxyErr) {
      console.error(`[carvana] Proxy verification failed: ${proxyErr.message}`);
      throw new Error(`Proxy connection failed: ${proxyErr.message}. Check proxy credentials.`);
    }

    try {
      await page.goto(CARVANA_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    } catch (navErr) {
      console.error(`[carvana] Navigation failed: ${navErr.message}`);
      await screenshot(page, '00-nav-failure').catch(() => {});
      throw navErr;
    }
    await humanDelay(3000, 6000);
    await screenshot(page, '01-landing');

    if (await isBlocked(page)) {
      const ssPath = await screenshot(page, 'blocked');
      const pageTitle = await page.title().catch(() => 'unknown');
      const bodySnippet = await page.textContent('body').then(t => t.substring(0, 300)).catch(() => 'could not read body');
      console.log(`[carvana] BLOCKED — title: ${pageTitle}, body: ${bodySnippet}`);
      return { error: 'blocked', details: { pageTitle, bodySnippet, screenshot: ssPath, url: page.url() } };
    }

    // --- Step 2: Enter VIN ---
    console.log('[carvana] Step 2: Entering VIN...');
    checkTimeout();

    // Try multiple selectors — the exact one will need tuning on the live site
    const vinSelectors = [
      'input[placeholder*="VIN"]',
      'input[placeholder*="vin"]',
      'input[name="vin"]',
      'input[data-testid="vin-input"]',
      'input[aria-label*="VIN"]',
      '#vin-input',
      'input[type="text"]',
    ];

    let vinInput = null;
    for (const sel of vinSelectors) {
      try {
        vinInput = await page.waitForSelector(sel, { timeout: 5000 });
        if (vinInput) {
          console.log(`  [carvana] Found VIN input with selector: ${sel}`);
          break;
        }
      } catch {
        continue;
      }
    }

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
    const submitSelectors = [
      'button[type="submit"]',
      'button:has-text("Get Offer")',
      'button:has-text("Next")',
      'button:has-text("Continue")',
      'button:has-text("Get My Offer")',
      'button:has-text("Get Started")',
    ];

    let submitted = false;
    for (const sel of submitSelectors) {
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
      return { error: 'blocked' };
    }

    // --- Step 3: Vehicle confirmation — extract make/model/year ---
    console.log('[carvana] Step 3: Checking vehicle confirmation...');
    let vehicleDetails = {};
    try {
      // Look for vehicle info text on the page
      const bodyText = await page.textContent('body');
      // Try to extract year/make/model from page text
      const carMatch = bodyText.match(/(\d{4})\s+([\w-]+)\s+([\w-]+)/);
      if (carMatch) {
        vehicleDetails = {
          year: carMatch[1],
          make: carMatch[2],
          model: carMatch[3],
        };
        console.log(`  [carvana] Vehicle: ${carMatch[1]} ${carMatch[2]} ${carMatch[3]}`);
      }
    } catch {
      // Non-critical
    }

    // --- Step 4: Enter mileage ---
    console.log('[carvana] Step 4: Entering mileage...');
    checkTimeout();

    const mileageSelectors = [
      'input[placeholder*="ileage"]',
      'input[placeholder*="miles"]',
      'input[name="mileage"]',
      'input[data-testid="mileage-input"]',
      'input[aria-label*="ileage"]',
      'input[type="number"]',
    ];

    let mileageInput = null;
    for (const sel of mileageSelectors) {
      try {
        mileageInput = await page.waitForSelector(sel, { timeout: 5000 });
        if (mileageInput) {
          console.log(`  [carvana] Found mileage input with: ${sel}`);
          break;
        }
      } catch {
        continue;
      }
    }

    if (!mileageInput) {
      try {
        const byPlaceholder = page.getByPlaceholder(/mile/i);
        await byPlaceholder.waitFor({ timeout: 5000 });
        mileageInput = await byPlaceholder.elementHandle();
      } catch {
        // Continue — mileage may appear on a later step
      }
    }

    if (mileageInput) {
      await mileageInput.click();
      for (const char of String(mileage)) {
        await mileageInput.type(char, { delay: 0 });
        await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 100) + 50));
      }
      await humanDelay(1000, 2000);

      // Submit mileage
      for (const sel of submitSelectors) {
        try {
          const btn = await page.waitForSelector(sel, { timeout: 3000 });
          if (btn) {
            await btn.click();
            break;
          }
        } catch {
          continue;
        }
      }
      await humanDelay(3000, 5000);
      await screenshot(page, '04-mileage');
    } else {
      console.log('  [carvana] No mileage input found — may be on a different step');
    }

    checkTimeout();

    // --- Step 5: Condition questions ---
    console.log('[carvana] Step 5: Answering condition questions...');

    // Look for condition-related buttons/options and select "Good" or positive options
    const conditionKeywords = ['good', 'excellent', 'no', 'none', 'clean'];
    for (const keyword of conditionKeywords) {
      try {
        const btns = await page.$$(`button:has-text("${keyword}"), label:has-text("${keyword}"), [role="radio"]:has-text("${keyword}")`);
        for (const btn of btns) {
          if (await btn.isVisible()) {
            await humanDelay(1000, 2000);
            await btn.click();
            console.log(`  [carvana] Selected condition option: ${keyword}`);
          }
        }
      } catch {
        continue;
      }
    }

    // Click through any "Next" / "Continue" buttons for condition pages
    for (let i = 0; i < 5; i++) {
      checkTimeout();
      let clicked = false;
      for (const sel of submitSelectors) {
        try {
          const btn = await page.waitForSelector(sel, { timeout: 3000 });
          if (btn && (await btn.isVisible())) {
            await humanDelay(1500, 3000);
            await btn.click();
            clicked = true;
            break;
          }
        } catch {
          continue;
        }
      }
      if (!clicked) break;
      await humanDelay(2000, 4000);

      // Check for more condition questions
      const hasCondition = await page.$('button:has-text("Good"), button:has-text("Excellent"), button:has-text("None")');
      if (hasCondition) {
        try {
          await hasCondition.click();
        } catch {
          // ignore
        }
      } else {
        break;
      }
    }

    await screenshot(page, '05-condition');
    checkTimeout();

    // --- Step 6: Enter zip code ---
    console.log('[carvana] Step 6: Entering zip code...');

    const zipSelectors = [
      'input[placeholder*="ip"]',
      'input[placeholder*="zip"]',
      'input[name="zip"]',
      'input[name="zipCode"]',
      'input[data-testid="zip-input"]',
      'input[aria-label*="ip"]',
      'input[maxlength="5"]',
    ];

    let zipInput = null;
    for (const sel of zipSelectors) {
      try {
        zipInput = await page.waitForSelector(sel, { timeout: 5000 });
        if (zipInput) {
          console.log(`  [carvana] Found zip input with: ${sel}`);
          break;
        }
      } catch {
        continue;
      }
    }

    if (zipInput) {
      await zipInput.click();
      await zipInput.fill(''); // Clear any existing value
      for (const char of String(zip)) {
        await zipInput.type(char, { delay: 0 });
        await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 100) + 50));
      }
      await humanDelay(1000, 2000);

      for (const sel of submitSelectors) {
        try {
          const btn = await page.waitForSelector(sel, { timeout: 3000 });
          if (btn) {
            await btn.click();
            break;
          }
        } catch {
          continue;
        }
      }
      await humanDelay(3000, 5000);
      await screenshot(page, '06-zip');
    }

    checkTimeout();

    // --- Step 7: Enter email ---
    console.log('[carvana] Step 7: Entering email...');

    const emailSelectors = [
      'input[type="email"]',
      'input[placeholder*="mail"]',
      'input[name="email"]',
      'input[data-testid="email-input"]',
      'input[aria-label*="mail"]',
    ];

    let emailInput = null;
    for (const sel of emailSelectors) {
      try {
        emailInput = await page.waitForSelector(sel, { timeout: 5000 });
        if (emailInput) {
          console.log(`  [carvana] Found email input with: ${sel}`);
          break;
        }
      } catch {
        continue;
      }
    }

    if (emailInput) {
      await emailInput.click();
      for (const char of offerEmail) {
        await emailInput.type(char, { delay: 0 });
        await new Promise((r) => setTimeout(r, Math.floor(Math.random() * 80) + 40));
      }
      await humanDelay(1000, 2000);

      for (const sel of submitSelectors) {
        try {
          const btn = await page.waitForSelector(sel, { timeout: 3000 });
          if (btn) {
            await btn.click();
            break;
          }
        } catch {
          continue;
        }
      }
      await humanDelay(3000, 5000);
      await screenshot(page, '07-email');
    }

    checkTimeout();

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
        return { error: 'blocked' };
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
      return {
        error: 'Could not extract offer amount. The page may have changed or the flow was interrupted.',
        details: vehicleDetails,
        screenshot: finalScreenshot,
      };
    }

    return {
      offer: offerText,
      details: {
        ...vehicleDetails,
        vin,
        mileage,
        zip,
        source: 'carvana',
        timestamp: new Date().toISOString(),
      },
    };
  } catch (err) {
    console.error(`[carvana] Error: ${err.message}`);
    return {
      error: err.message,
      details: { vin, mileage, zip },
    };
  } finally {
    await closeBrowser(browser);
    console.log(`[carvana] Flow completed in ${Math.round(elapsed() / 1000)}s`);
  }
}

module.exports = { getCarvanaOffer };
