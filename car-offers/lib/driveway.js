/**
 * Driveway "Sell Your Car" wizard automation.
 *
 * Starting URL: https://www.driveway.com/sell-your-car
 *   (The shorter /sell 404s as of 2026-04-13; /sell-your-car is canonical.)
 *
 * Wizard shape (per Driveway's own FAQ — selectors verified at build time
 * may still drift):
 *   1. VIN or license-plate input
 *   2. Mileage
 *   3. Condition + "important features"
 *   4. Contact info -> instant offer
 *
 * Driveway historically has NOT gated the offer behind SMS/account, but
 * will push a "create account to accept" step AFTER the offer is shown.
 * We stop at the offer display; detectAccountWall() still runs at every
 * step so if the page changes and demands a phone code, we bail cleanly
 * with status='account_required'.
 *
 * Selectors are best-effort — sites in the auto-buyer space change
 * their wizard markup every quarter or two. The adaptive approach (lists
 * of fallback selectors + text-based button clicks) survives most
 * revisions. Flagged `// TODO(selector)` where we've had to guess.
 */

const {
  launchBrowser, humanDelay, closeBrowser,
  simulateHumanBehavior, markProfileWarmed, profileIsWarm,
} = require('./browser');
const { miniBrowse } = require('./shopper-warmup');
const { siteWarmup } = require('./site-warmup');
const {
  screenshot, debugDump, isBlocked, waitForBlockResolve, humanInput, scanForOffer,
  firstVisible, findInputByLabelOrSelectors, clickFirstByText, detectAccountWall,
} = require('./wizard-common');
const { siteConditionLabel, EXTRA_ANSWERS } = require('./offer-input');
const config = require('./config');

const DRIVEWAY_URL = 'https://www.driveway.com/sell-your-car';
const DRIVEWAY_HOMEPAGE = 'https://www.driveway.com/';
const DRIVEWAY_INVENTORY = 'https://www.driveway.com/shop';
const TOTAL_TIMEOUT = 900_000;
const WARMUP_TTL_HOURS = 24;

let activeRun = null;

async function _getDrivewayOfferImpl({ vin, mileage, zip, condition, email, consumerId, fingerprintProfileId, proxyZip, debug }) {
  const offerEmail = email || config.PROJECT_EMAIL || 'caroffers.tool@gmail.com';
  const conditionLabel = siteConditionLabel('driveway', condition);
  const wizardLog = [];
  const startTime = Date.now();
  let browser = null;
  let launchMethod = 'unknown';

  function log(msg) {
    console.log(msg);
    wizardLog.push(`${Math.round((Date.now() - startTime) / 1000)}s: ${msg}`);
  }
  function elapsed() { return Date.now() - startTime; }
  function checkTimeout() {
    if (elapsed() > TOTAL_TIMEOUT) throw new Error('Total timeout exceeded');
  }

  try {
    log(`[driveway] Starting VIN=${vin} mi=${mileage} zip=${zip} cond=${condition}->${conditionLabel}`);

    const result = await launchBrowser({ consumerId, fingerprintProfileId, proxyZip: proxyZip || zip });
    browser = result.browser;
    const page = result.page;
    launchMethod = result.launchMethod || 'unknown';
    log(`[driveway] Browser: ${launchMethod} | headed: ${!!process.env.DISPLAY}`);

    // --- Warmup ---
    const isWarm = profileIsWarm(consumerId, WARMUP_TTL_HOURS);
    log(`[driveway] Profile warm state: ${isWarm ? 'fresh' : 'cold'}`);
    if (!isWarm) {
      try { await miniBrowse(page, log); markProfileWarmed(consumerId); } catch (e) { log(`[driveway] carvana warm fail: ${e.message}`); }
    }
    try {
      await siteWarmup(page, { homepage: DRIVEWAY_HOMEPAGE, inventory: DRIVEWAY_INVENTORY }, log);
    } catch (e) { log(`[driveway] site warm fail (non-fatal): ${e.message}`); }
    await humanDelay(2000, 5000);

    // --- Navigate to sell page ---
    log(`[driveway] Navigating to ${DRIVEWAY_URL}`);
    let loaded = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await page.goto(DRIVEWAY_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
      } catch (e) {
        log(`[driveway] nav attempt ${attempt} failed: ${e.message}`);
        if (attempt === 2) {
          await screenshot(page, 'driveway', 'nav-fail');
          return { status: 'error', error: `navigation failed: ${e.message}`, wizardLog, launchMethod };
        }
        await humanDelay(8000, 12000);
        continue;
      }
      await humanDelay(5000, 8000);
      try { await simulateHumanBehavior(page); } catch { /* ok */ }
      try { await page.waitForLoadState('networkidle', { timeout: 30000 }); } catch { /* ok */ }
      await screenshot(page, 'driveway', `01-landing-${attempt}`);

      if (!(await isBlocked(page))) { loaded = true; break; }
      log(`[driveway] block detected attempt ${attempt}`);
      if (await waitForBlockResolve(page, log, [30, 45, 60][attempt] || 60)) {
        loaded = true; break;
      }
      if (attempt < 2) await humanDelay(10000, 15000);
    }
    if (!loaded) {
      await screenshot(page, 'driveway', 'blocked-final');
      return {
        status: 'blocked',
        error: 'blocked at landing',
        details: { at: 'landing', url: page.url(), launchMethod },
        wizardLog,
      };
    }

    // --- Step 1: VIN ---
    checkTimeout();
    log('[driveway] Step 1: Clicking VIN tab + finding VIN input');
    if (debug) await debugDump(page, 'driveway', 'step1-landing');
    // Driveway shows "License Plate / VIN" tabs; click VIN tab. The text-only
    // "VIN" matches both <button>VIN</button> and the active "VIN" tab.
    await clickFirstByText(page, ['VIN'], 2000);
    await humanDelay(400, 900);

    // Driveway's VIN input has NO "VIN" in placeholder/name — placeholder is
    // a sample VIN (e.g. "1GCCW80H7CR161832"). The label "VIN" is a sibling.
    // Use findInputByLabelOrSelectors to walk from the label.
    const vinInputSelectors = [
      'input[name="vin"]',
      'input[name="vehicleVin"]',
      'input[placeholder*="VIN" i]',
      'input[data-testid*="vin"]',
      'input[aria-label*="VIN" i]',
      '#vin',
      // Driveway-specific: looks like a 17-char text input on the only form
      'form input[type="text"][maxlength="17"]',
      'form input[maxlength="17"]',
    ];
    const vinFound = await findInputByLabelOrSelectors(page, vinInputSelectors, ['VIN'], 8000);
    if (!vinFound) {
      // Last resort: any single visible text input on the form box. The VIN
      // box only contains one input.
      try {
        const candidates = await page.$$('input[type="text"]:visible, input:not([type]):visible');
        for (const cand of candidates) {
          const isVis = await cand.isVisible().catch(() => false);
          if (!isVis) continue;
          const ml = await cand.getAttribute('maxlength').catch(() => null);
          if (ml === '17' || ml === null) {
            log(`[driveway] VIN input fallback (visible text input maxlength=${ml})`);
            await humanInput(page, cand, vin);
            await humanDelay(800, 1600);
            // proceed straight to submit
            const subFb = await clickFirstByText(page,
              ['Get an Offer', 'Get My Offer', 'Get Your Offer', 'Get Offer', 'Continue', 'Next'], 3000);
            if (!subFb.clicked) { try { await page.keyboard.press('Enter'); } catch {} }
            await humanDelay(4000, 7000);
            await screenshot(page, 'driveway', '03-after-vin-fb');
            if (debug) await debugDump(page, 'driveway', 'step3-after-vin');
            // Jump past the normal-path block by setting a flag
            return await _drivewayPostVinLoop({ page, log, vin, mileage, zip, condition,
              conditionLabel, offerEmail, launchMethod, wizardLog, checkTimeout, debug });
          }
        }
      } catch { /* fall through */ }
      await screenshot(page, 'driveway', 'no-vin-input');
      if (debug) await debugDump(page, 'driveway', 'no-vin-input');
      log('[driveway] FAIL: no VIN input found at landing — page may require login or has changed');
      return {
        status: 'error',
        error: 'VIN input not found — Driveway markup may have changed',
        details: { url: page.url(), launchMethod },
        wizardLog,
      };
    }
    log(`[driveway] VIN input: ${vinFound.sel}`);
    await humanInput(page, vinFound.el, vin);
    await humanDelay(800, 1600);
    await screenshot(page, 'driveway', '02-vin-entered');
    if (debug) await debugDump(page, 'driveway', 'step2-vin-entered');

    const vinSubmit = await clickFirstByText(page,
      ['Get an Offer', 'Get My Offer', 'Get Your Offer', 'Get Offer', 'Continue', 'Next'], 3000);
    if (!vinSubmit.clicked) {
      try { await page.keyboard.press('Enter'); } catch { /* ok */ }
      log('[driveway] VIN submitted via Enter');
    } else {
      log(`[driveway] VIN submitted via "${vinSubmit.label}"`);
    }
    await humanDelay(4000, 7000);
    await screenshot(page, 'driveway', '03-after-vin');
    if (debug) await debugDump(page, 'driveway', 'step3-after-vin');
    return await _drivewayPostVinLoop({ page, log, vin, mileage, zip, condition,
      conditionLabel, offerEmail, launchMethod, wizardLog, checkTimeout, debug });
  } catch (err) {
    log(`[driveway] ERROR: ${err.message}`);
    return {
      status: 'error',
      error: err.message,
      details: { vin, mileage, zip, condition, launchMethod },
      wizardLog,
    };
  } finally {
    await closeBrowser(browser);
    console.log(`[driveway] flow completed in ${Math.round(elapsed() / 1000)}s`);
  }
}

/**
 * Post-VIN-submit wizard loop, factored out so both the normal path and the
 * VIN-input fallback path share it. Returns the final wizard result object.
 */
async function _drivewayPostVinLoop({ page, log, vin, mileage, zip, condition, conditionLabel,
  offerEmail, launchMethod, wizardLog, checkTimeout, debug }) {

  if (await isBlocked(page)) {
    log('[driveway] block after VIN submit');
    if (!(await waitForBlockResolve(page, log, 90))) {
      return { status: 'blocked', error: 'blocked after VIN submit', wizardLog, launchMethod };
    }
  }

  // --- Adaptive wizard loop ---
  let filledMileage = false;
  let filledZip = false;
  let selectedCondition = false;
  let filledEmail = false;
  let stuckCount = 0;

  for (let step = 0; step < 20; step++) {
    checkTimeout();
    const url = page.url();
    log(`[driveway] wizard step ${step}: ${url}`);
    await screenshot(page, 'driveway', `wizard-${step}`);
    if (debug) await debugDump(page, 'driveway', `wizard-${step}`);

    const wall = await detectAccountWall(page);
    if (wall) {
      log(`[driveway] account wall: ${wall}`);
      await screenshot(page, 'driveway', 'account-wall');
      return {
        status: 'account_required',
        error: `Driveway requires account / verification (${wall})`,
        details: { at: wall, url, launchMethod },
        wizardLog,
      };
    }

    const offerAmt = await scanForOffer(page);
    if (offerAmt && offerAmt > 500) {
      log(`[driveway] OFFER FOUND step ${step}: $${offerAmt}`);
      await screenshot(page, 'driveway', 'offer-found');
      let expires = null;
      try {
        const bodyText = await page.textContent('body');
        const expMatch = bodyText.match(/(?:expires?|valid(?:\s+through|\s+until)?|good\s+through|offer\s+good\s+until)[:\s]+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4})/i);
        if (expMatch) expires = expMatch[1];
      } catch { /* ok */ }
      return {
        status: 'ok',
        offer_usd: offerAmt,
        offer: `$${offerAmt.toLocaleString()}`,
        offer_expires: expires,
        details: { vin, mileage, zip, condition, source: 'driveway', url, launchMethod },
        wizardLog,
      };
    }

    if (await isBlocked(page)) {
      log('[driveway] block mid-wizard');
      if (!(await waitForBlockResolve(page, log, 45))) {
        return { status: 'blocked', error: `blocked mid-wizard step ${step}`, wizardLog, launchMethod };
      }
    }

    let interacted = false;

    if (!filledMileage) {
      const m = await findInputByLabelOrSelectors(page, [
        'input[name="mileage"]', 'input[name="odometer"]',
        'input[placeholder*="ileage" i]', 'input[placeholder*="iles" i]',
        'input[data-testid*="mileage" i]', 'input[aria-label*="ileage" i]',
        'input[type="number"]', 'input[inputmode="numeric"]',
      ], ['Mileage', 'Odometer', 'Miles'], 2000);
      if (m) {
        log(`[driveway] mileage: ${mileage} (sel=${m.sel})`);
        await humanInput(page, m.el, String(mileage));
        filledMileage = true;
        interacted = true;
        await humanDelay(800, 1500);
      }
    }

    if (!filledZip) {
      const z = await findInputByLabelOrSelectors(page, [
        'input[name="zip"]', 'input[name="zipCode"]', 'input[name="postalCode"]',
        'input[placeholder*="ip code" i]', 'input[placeholder*="ostal" i]',
        'input[maxlength="5"][inputmode="numeric"]',
        'input[data-testid*="zip" i]',
      ], ['Zip', 'ZIP', 'Postal'], 2000);
      if (z) {
        log(`[driveway] zip: ${zip} (sel=${z.sel})`);
        await humanInput(page, z.el, String(zip));
        filledZip = true;
        interacted = true;
        await humanDelay(800, 1500);
      }
    }

    if (!filledEmail) {
      const e = await findInputByLabelOrSelectors(page, [
        'input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail" i]',
      ], ['Email'], 2000);
      if (e) {
        log(`[driveway] email: ${offerEmail}`);
        await humanInput(page, e.el, offerEmail);
        filledEmail = true;
        interacted = true;
        await humanDelay(800, 1500);
      }
    }

    if (!selectedCondition || !interacted) {
      const cond = await clickFirstByText(page, [conditionLabel], 1500);
      if (cond.clicked) {
        log(`[driveway] condition: ${conditionLabel}`);
        selectedCondition = true;
        interacted = true;
        await humanDelay(600, 1200);
      }
    }

    if (!interacted) {
      const extra = await clickFirstByText(page, [
        EXTRA_ANSWERS.accidentHistory, EXTRA_ANSWERS.titleStatus,
        EXTRA_ANSWERS.loanStatus, EXTRA_ANSWERS.ownership,
        EXTRA_ANSWERS.modifications,
        'No accidents', 'No damage', 'Clean title',
        'I own it outright', 'Paid off', 'No loan',
        'No modifications', 'Factory stock', 'No', 'None',
      ], 1500);
      if (extra.clicked) {
        log(`[driveway] extra: "${extra.label}"`);
        interacted = true;
        await humanDelay(600, 1200);
      }
    }

    if (!interacted) {
      const confirm = await clickFirstByText(page, [
        'This is my car', 'Looks right', 'Yes, this is', 'Correct', 'Confirm',
      ], 1500);
      if (confirm.clicked) {
        log(`[driveway] vehicle confirm: "${confirm.label}"`);
        interacted = true;
        await humanDelay(600, 1200);
      }
    }

    const next = await clickFirstByText(page, [
      'Get Your Offer', 'Get My Offer', 'See My Offer', 'View Offer', 'Get an Offer',
      'Continue', 'Next', 'Submit',
    ], 2000);
    if (next.clicked) {
      log(`[driveway] clicked: ${next.label}`);
      interacted = true;
    }

    await humanDelay(3000, 6000);
    const newUrl = page.url();
    if (newUrl === url && !interacted) {
      stuckCount++;
      log(`[driveway] stuck=${stuckCount}`);
      if (stuckCount >= 3) break;
    } else if (newUrl !== url) {
      log(`[driveway] nav: ${newUrl}`);
      stuckCount = 0;
    }
  }

  const finalOffer = await scanForOffer(page);
  if (finalOffer && finalOffer > 500) {
    return {
      status: 'ok',
      offer_usd: finalOffer,
      offer: `$${finalOffer.toLocaleString()}`,
      details: { vin, mileage, zip, condition, source: 'driveway', url: page.url(), launchMethod },
      wizardLog,
    };
  }

  await screenshot(page, 'driveway', 'no-offer-final');
  if (debug) await debugDump(page, 'driveway', 'no-offer-final');
  const title = await page.title().catch(() => 'unknown');
  const bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 1000)).catch(() => '');
  log(`[driveway] FAIL: wizard finished, no offer dollar amount. title="${title}" url=${page.url()}`);
  return {
    status: 'error',
    error: 'No offer extracted — wizard finished without dollar amount',
    details: { vin, mileage, zip, condition, url: page.url(), title, bodySnippet, launchMethod },
    wizardLog,
  };
}

async function getDrivewayOffer(params) {
  if (activeRun) {
    console.log('[driveway] Another run active — queuing');
    try { await Promise.race([activeRun, new Promise((_, rej) => setTimeout(() => rej(new Error('queue timeout')), 300_000))]); }
    catch (e) { console.log(`[driveway] queue wait: ${e.message}`); }
  }
  activeRun = (async () => {
    try { return await _getDrivewayOfferImpl(params); }
    finally { activeRun = null; }
  })();
  return activeRun;
}

module.exports = { getDrivewayOffer };
