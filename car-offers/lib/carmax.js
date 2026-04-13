/**
 * CarMax "Sell My Car" wizard automation.
 *
 * Starting URL: https://www.carmax.com/sell-my-car
 * Wizard shape (as of 2026-04-13):
 *   1. Landing page: prominent "Get your offer" with VIN / license-plate tabs.
 *   2. VIN submit -> year/make/model confirmation screen
 *   3. Mileage input
 *   4. Zip input (may be inferred from location; sometimes asked first)
 *   5. Condition questions (cosmetic / mechanical / accident / title)
 *   6. Contact info (email / phone) -> offer OR account-wall
 *
 * IMPORTANT: CarMax has historically pushed hard on account creation —
 * if the page demands a phone number + SMS code to "see your offer",
 * we STOP and return { status: 'account_required' } rather than try to
 * bypass. Solving SMS belongs to a product decision, not this scraper.
 *
 * Selectors here are best-effort against the live site. CarMax changes
 * their markup seasonally; the adaptive wizard loop (try a wide list of
 * selectors + fallback to text-based clicks) survives most revisions.
 * Flagged as `// TODO(selector)` where we've had to guess.
 */

const {
  launchBrowser, humanDelay, closeBrowser,
  simulateHumanBehavior, markProfileWarmed, profileIsWarm,
} = require('./browser');
const { miniBrowse } = require('./shopper-warmup');
const { siteWarmup } = require('./site-warmup');
const {
  screenshot, debugDump, isBlocked, waitForBlockResolve, humanInput, scanForOffer,
  firstVisible, findInputByLabelOrSelectors, expandSectionByText, pickDropdownOption,
  clickFirstByText, detectAccountWall,
} = require('./wizard-common');
const { siteConditionLabel, EXTRA_ANSWERS } = require('./offer-input');
const config = require('./config');

const CARMAX_URL = 'https://www.carmax.com/sell-my-car';
const CARMAX_HOMEPAGE = 'https://www.carmax.com/';
const CARMAX_INVENTORY = 'https://www.carmax.com/cars';
const TOTAL_TIMEOUT = 900_000;
const WARMUP_TTL_HOURS = 24;

// Serialize — persistent profile is a Chromium singleton.
let activeRun = null;

async function _getCarmaxOfferImpl({ vin, mileage, zip, condition, email, consumerId, fingerprintProfileId, proxyZip, debug }) {
  const offerEmail = email || config.PROJECT_EMAIL || 'caroffers.tool@gmail.com';
  const conditionLabel = siteConditionLabel('carmax', condition);
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
    log(`[carmax] Starting offer flow VIN=${vin} mi=${mileage} zip=${zip} cond=${condition}->${conditionLabel}`);

    // --- Launch ---
    const result = await launchBrowser({ consumerId, fingerprintProfileId, proxyZip: proxyZip || zip });
    browser = result.browser;
    const page = result.page;
    launchMethod = result.launchMethod || 'unknown';
    log(`[carmax] Browser: ${launchMethod} | headed: ${!!process.env.DISPLAY}`);

    // --- Warmup ---
    // We always run a light warm on carmax.com itself so its cookies exist.
    // If the Chrome profile is warm (from shopper-warmup's full browse on
    // carvana.com), that's still valuable — signals a returning machine —
    // but we need carmax-domain-specific cookies too.
    const isWarm = profileIsWarm(consumerId, WARMUP_TTL_HOURS);
    log(`[carmax] Profile warm state: ${isWarm ? 'fresh' : 'cold'}`);
    if (!isWarm) {
      // One-time deep warm on carvana.com (builds generic "returning consumer"
      // signal) then light warm on carmax. miniBrowse is carvana-flavored.
      try { await miniBrowse(page, log); markProfileWarmed(consumerId); } catch (e) { log(`[carmax] carvana warm fail: ${e.message}`); }
    }
    try {
      await siteWarmup(page, { homepage: CARMAX_HOMEPAGE, inventory: CARMAX_INVENTORY }, log);
    } catch (e) { log(`[carmax] site warm fail (non-fatal): ${e.message}`); }
    await humanDelay(2000, 5000);

    // --- Navigate to sell page ---
    log(`[carmax] Navigating to ${CARMAX_URL}`);
    let loaded = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await page.goto(CARMAX_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
      } catch (e) {
        log(`[carmax] nav attempt ${attempt} failed: ${e.message}`);
        if (attempt === 2) {
          await screenshot(page, 'carmax', 'nav-fail');
          return { status: 'error', error: `navigation failed: ${e.message}`, wizardLog, launchMethod };
        }
        await humanDelay(8000, 12000);
        continue;
      }
      await humanDelay(5000, 8000);
      try { await simulateHumanBehavior(page); } catch { /* ok */ }
      try { await page.waitForLoadState('networkidle', { timeout: 30000 }); } catch { /* ok */ }
      await screenshot(page, 'carmax', `01-landing-${attempt}`);

      if (!(await isBlocked(page))) { loaded = true; break; }
      log(`[carmax] block detected on attempt ${attempt} — waiting for resolve...`);
      if (await waitForBlockResolve(page, log, [30, 45, 60][attempt] || 60)) {
        loaded = true; break;
      }
      if (attempt < 2) await humanDelay(10000, 15000);
    }
    if (!loaded) {
      await screenshot(page, 'carmax', 'blocked-final');
      const title = await page.title().catch(() => 'unknown');
      return {
        status: 'blocked',
        error: 'blocked at landing',
        details: { at: 'landing', title, url: page.url(), launchMethod },
        wizardLog,
      };
    }

    // --- Step 1: Enter VIN ---
    checkTimeout();
    log('[carmax] Step 1: Looking for VIN input (may be on a tab)');
    // Click VIN tab if there's a license-plate/VIN toggle
    await clickFirstByText(page, ['VIN', 'Enter VIN', 'By VIN'], 2500);
    await humanDelay(600, 1200);

    // TODO(selector): CarMax's VIN input selectors observed across revisions.
    const vinInputSelectors = [
      'input[name="vin"]',
      'input[placeholder*="VIN"]',
      'input[placeholder*="vin"]',
      'input[data-testid*="vin"]',
      'input[aria-label*="VIN"]',
      '#vin',
      'input[name="vehicleVin"]',
    ];
    const vinFound = await firstVisible(page, vinInputSelectors, 8000);
    if (!vinFound) {
      await screenshot(page, 'carmax', 'no-vin-input');
      return {
        status: 'error', error: 'VIN input not found — CarMax markup may have changed',
        details: { url: page.url(), launchMethod }, wizardLog,
      };
    }
    log(`[carmax] VIN input: ${vinFound.sel}`);
    await humanInput(page, vinFound.el, vin);
    await humanDelay(800, 1600);
    await screenshot(page, 'carmax', '02-vin-entered');

    // Submit VIN
    const vinSubmitClick = await clickFirstByText(page,
      ['Get Your Offer', 'Get My Offer', 'Get Offer', 'Continue', 'Next', 'Submit'], 3000);
    if (!vinSubmitClick.clicked) {
      try { await page.keyboard.press('Enter'); log('[carmax] VIN submitted via Enter'); }
      catch (e) { log(`[carmax] VIN submit fail: ${e.message}`); }
    } else {
      log(`[carmax] VIN submitted via "${vinSubmitClick.label}"`);
    }
    await humanDelay(4000, 7000);
    await screenshot(page, 'carmax', '03-after-vin');

    // Block after submit?
    if (await isBlocked(page)) {
      log('[carmax] block after VIN submit — waiting up to 90s');
      if (!(await waitForBlockResolve(page, log, 90))) {
        return { status: 'blocked', error: 'blocked after VIN submit', wizardLog, launchMethod };
      }
    }

    // --- Adaptive wizard loop: mileage / zip / condition / contact ---
    // CarMax's vehicle-confirmation page has the GET MY OFFER button DISABLED
    // until you expand "Mileage and condition" and fill it in. Track expansion
    // attempts so we don't loop forever clicking a disabled CTA.
    let filledMileage = false;
    let filledZip = false;
    let selectedCondition = false;
    let filledEmail = false;
    let expandedMileageSection = false;
    let stuckCount = 0;
    let lastUrl = page.url();

    for (let step = 0; step < 25; step++) {
      checkTimeout();
      const url = page.url();
      log(`[carmax] wizard step ${step}: ${url}`);
      await screenshot(page, 'carmax', `wizard-${step}`);
      if (debug) await debugDump(page, 'carmax', `wizard-${step}`);

      // Account / SMS wall?
      const wall = await detectAccountWall(page);
      if (wall) {
        log(`[carmax] account wall detected: ${wall}`);
        await screenshot(page, 'carmax', 'account-wall');
        return {
          status: 'account_required',
          error: `CarMax requires account / verification (${wall})`,
          details: { at: wall, url, launchMethod },
          wizardLog,
        };
      }

      // Offer present?
      const offerAmt = await scanForOffer(page);
      if (offerAmt && offerAmt > 500) {
        log(`[carmax] OFFER FOUND on step ${step}: $${offerAmt}`);
        await screenshot(page, 'carmax', 'offer-found');
        // Try to find an expiration date nearby
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
          details: { vin, mileage, zip, condition, source: 'carmax', url, launchMethod },
          wizardLog,
        };
      }

      if (await isBlocked(page)) {
        log('[carmax] block mid-wizard');
        if (!(await waitForBlockResolve(page, log, 45))) {
          return { status: 'blocked', error: `blocked mid-wizard step ${step}`, wizardLog, launchMethod };
        }
      }

      let interacted = false;

      // Expand collapsed "Mileage and condition" section first — on the
      // vehicle-confirmation page CarMax HIDES the mileage input behind an
      // accordion and the GET MY OFFER button stays disabled until it's
      // expanded + filled. This was the root cause of the consumer-1 timeout
      // (clicked Get My Offer 4× without ever filling mileage).
      if (!filledMileage && !expandedMileageSection) {
        const exp = await expandSectionByText(page, [
          'Mileage and condition', 'Mileage & condition', 'Mileage', 'Condition',
        ], 1500);
        if (exp.clicked) {
          log(`[carmax] expanded section: "${exp.heading}"`);
          expandedMileageSection = true;
          interacted = true;
          await humanDelay(700, 1300);
        }
      }

      // Mileage
      if (!filledMileage) {
        const m = await findInputByLabelOrSelectors(page, [
          'input[name="mileage"]', 'input[name="odometer"]',
          'input[placeholder*="ileage" i]', 'input[placeholder*="iles" i]',
          'input[data-testid*="mileage" i]', 'input[aria-label*="ileage" i]',
          'input[type="number"]', 'input[inputmode="numeric"]',
        ], ['Mileage', 'Odometer', 'Miles', 'Current mileage'], 2000);
        if (m) {
          log(`[carmax] mileage: ${mileage} (sel=${m.sel})`);
          await humanInput(page, m.el, String(mileage));
          filledMileage = true;
          interacted = true;
          await humanDelay(800, 1500);
        }
      }

      // Zip
      if (!filledZip) {
        const z = await findInputByLabelOrSelectors(page, [
          'input[name="zip"]', 'input[name="zipCode"]', 'input[name="postalCode"]',
          'input[placeholder*="ip code" i]', 'input[placeholder*="ostal" i]',
          'input[maxlength="5"][inputmode="numeric"]',
          'input[data-testid*="zip" i]',
        ], ['Zip', 'ZIP', 'Postal'], 2000);
        if (z) {
          log(`[carmax] zip: ${zip} (sel=${z.sel})`);
          await humanInput(page, z.el, String(zip));
          filledZip = true;
          interacted = true;
          await humanDelay(800, 1500);
        }
      }

      // Email (usually late in flow, before offer)
      if (!filledEmail) {
        const e = await findInputByLabelOrSelectors(page, [
          'input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail" i]',
        ], ['Email'], 2000);
        if (e) {
          log(`[carmax] email: ${offerEmail}`);
          await humanInput(page, e.el, offerEmail);
          filledEmail = true;
          interacted = true;
          await humanDelay(800, 1500);
        }
      }

      // Condition selector — CarMax asks mechanical + cosmetic separately.
      // Pick the canonical label each time.
      if (!selectedCondition || interacted === false) {
        const conditionClick = await clickFirstByText(page, [conditionLabel], 1500);
        if (conditionClick.clicked) {
          log(`[carmax] condition clicked: ${conditionLabel}`);
          selectedCondition = true;
          interacted = true;
          await humanDelay(600, 1200);
        }
      }

      // Accident / title / ownership questions + the multi-question
      // condition page (rust, interior, tires, keys). CarMax stacks 10-15
      // radio groups on one page using the kmx-radio-label pattern. Click
      // EVERY un-checked radio whose visible text matches the safest answer
      // for that question — "No" for damage/issue questions, "2" for keys.
      // Use page.evaluate so we read all radios + their group state in one
      // round-trip (much faster than per-radio iteration). Run on every
      // iteration once mileage is filled — radio groups can appear after
      // earlier groups are answered (CarMax progressively reveals them).
      if (filledMileage) {
        try {
          const result = await page.evaluate(() => {
            // Find every radio input and its label text by walking the DOM
            // (kmx-radio-label is associated via for=id; many sites also use
            // <label><input>...text</label> wrapping pattern).
            const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
            const groups = new Map();  // group name -> array of {label, input}
            const out = { clicked: [], groupCount: 0 };

            for (const inp of radios) {
              if (!inp.name) continue;
              if (!groups.has(inp.name)) groups.set(inp.name, []);
              // Find associated label text
              let labelText = '';
              const id = inp.id;
              if (id) {
                const lab = document.querySelector(`label[for="${id}"]`);
                if (lab) labelText = (lab.textContent || '').trim();
              }
              if (!labelText && inp.parentElement) {
                labelText = (inp.parentElement.textContent || '').trim();
              }
              groups.get(inp.name).push({ input: inp, label: labelText });
            }
            out.groupCount = groups.size;

            // For each group, pick the safest answer in priority order.
            // Order matters: NO catches damage/issue questions; KEYS catches
            // "How many keys"; OWNERSHIP / TITLE for the post-condition page.
            const SAFE_NO = /^(no|none|no, never)$/i;
            const SAFE_KEYS = /^(2|two|2 keys|two keys|both keys)$/i;
            const SAFE_OWNERSHIP = /^(i own it|own outright|paid off|no loan|1 owner|original owner|i'm the original owner|i am the original owner)$/i;
            const SAFE_TITLE = /^(clean|clean title|in my name)$/i;
            const SAFE_USAGE = /^(personal|family|commute|none of these|none of the above)$/i;

            for (const [name, opts] of groups) {
              // Already answered? Skip.
              if (opts.some(o => o.input.checked)) continue;
              // Pick the "No" if present, else the "2" if it's a keys group, etc.
              let pick = opts.find(o => SAFE_NO.test(o.label));
              if (!pick) pick = opts.find(o => SAFE_KEYS.test(o.label));
              if (!pick) pick = opts.find(o => SAFE_OWNERSHIP.test(o.label));
              if (!pick) pick = opts.find(o => SAFE_TITLE.test(o.label));
              if (!pick) pick = opts.find(o => SAFE_USAGE.test(o.label));
              if (pick) {
                // Click via the input element so the React handler fires.
                // Some forms wrap the input in a span/label; clicking the
                // input directly bypasses CSS pointer-events:none on the
                // visible label. If click() doesn't dispatch a change event
                // on the React component, manually fire one.
                pick.input.click();
                pick.input.dispatchEvent(new Event('change', { bubbles: true }));
                out.clicked.push({ name, label: pick.label });
              } else {
                // Diagnostic: log what was unanswered
                out.unanswered = out.unanswered || [];
                out.unanswered.push({ name, options: opts.slice(0, 6).map(o => o.label) });
              }
            }
            return out;
          });
          if (result.clicked.length > 0) {
            log(`[carmax] auto-answered ${result.clicked.length}/${result.groupCount} radio groups: ${result.clicked.map(c => c.label).join(', ')}`);
            interacted = true;
            await humanDelay(800, 1400);
          } else if (result.groupCount > 0) {
            // No new groups answered. If unanswered remain, log them so we
            // know what label vocab to add to the SAFE_ regexes.
            const u = result.unanswered || [];
            if (u.length > 0) {
              log(`[carmax] ${u.length} unanswered groups (no safe answer): ${u.map(g => `${g.name}=[${g.options.join('|')}]`).slice(0, 6).join('; ')}`);
            } else {
              log(`[carmax] no unanswered radio groups (total=${result.groupCount})`);
            }
          }
        } catch (radioErr) {
          log(`[carmax] radio auto-answer error: ${radioErr.message}`);
        }
      }

      if (!interacted) {
        const extraAnswers = [
          EXTRA_ANSWERS.accidentHistory,     // "None"
          EXTRA_ANSWERS.titleStatus,         // "Clean"
          EXTRA_ANSWERS.loanStatus,          // "Own outright"
          EXTRA_ANSWERS.ownership,           // "I own it"
          EXTRA_ANSWERS.modifications,       // "None"
          // common button text variants CarMax uses
          'No accidents', 'No damage', 'Clean title',
          'I own it outright', 'Paid off', 'No loan',
          'No modifications', 'Factory stock',
          '1 owner', 'Original owner', 'No, never',
        ];
        const extra = await clickFirstByText(page, extraAnswers, 1500);
        if (extra.clicked) {
          log(`[carmax] answered extra: "${extra.label}"`);
          interacted = true;
          await humanDelay(600, 1200);
        }
      }

      // Confirm vehicle cards (year/make/model selection)
      if (!interacted) {
        const confirmClick = await clickFirstByText(page,
          ['This is my car', 'Looks right', 'Yes, this is', 'Correct', 'Confirm', 'Continue'], 1500);
        if (confirmClick.clicked) {
          log(`[carmax] vehicle confirm: "${confirmClick.label}"`);
          interacted = true;
          await humanDelay(600, 1200);
        }
      }

      // Next / Continue / Get offer — but only if NOT disabled. CarMax's
      // disabled "GET MY OFFER" button still matches has-text but clicking it
      // has no effect; the wizard would loop forever. Probe the disabled
      // attribute first.
      const ctaTexts = ['Get Your Offer', 'Get My Offer', 'See My Offer', 'View Offer',
         'Continue', 'Next', 'Submit', 'Confirm'];
      let clickedNext = false;
      for (const ctaText of ctaTexts) {
        try {
          const btn = await page.$(`button:has-text("${ctaText}"):not([disabled]):not([aria-disabled="true"])`);
          if (btn && await btn.isVisible()) {
            await humanDelay(700, 1300);
            await btn.click();
            log(`[carmax] clicked CTA: ${ctaText}`);
            clickedNext = true;
            interacted = true;
            break;
          }
        } catch { /* next */ }
      }
      // If no enabled CTA found, log it (helps diagnose accordion-blocked
      // forms) but don't error — maybe a page change is in flight.
      if (!clickedNext) {
        const disabledBtns = await page.$$eval('button[disabled], button[aria-disabled="true"]', els =>
          els.slice(0, 5).map(e => e.textContent.trim().slice(0, 40))
        ).catch(() => []);
        if (disabledBtns.length > 0) {
          log(`[carmax] no enabled CTA found. Disabled buttons present: ${JSON.stringify(disabledBtns)}`);
        }
      }

      await humanDelay(3000, 6000);

      const newUrl = page.url();
      if (newUrl === url && !interacted) {
        stuckCount++;
        log(`[carmax] no progress (stuck=${stuckCount})`);
        if (stuckCount >= 3) {
          log('[carmax] stuck 3× — breaking');
          break;
        }
      } else if (newUrl !== url) {
        log(`[carmax] nav: ${newUrl}`);
        stuckCount = 0;
      }
    }

    // Final check for offer
    const finalOffer = await scanForOffer(page);
    if (finalOffer && finalOffer > 500) {
      log(`[carmax] final-check offer: $${finalOffer}`);
      return {
        status: 'ok',
        offer_usd: finalOffer,
        offer: `$${finalOffer.toLocaleString()}`,
        details: { vin, mileage, zip, condition, source: 'carmax', url: page.url(), launchMethod },
        wizardLog,
      };
    }

    await screenshot(page, 'carmax', 'no-offer-final');
    const title = await page.title().catch(() => 'unknown');
    const bodySnippet = await page.textContent('body').then(t => (t || '').substring(0, 1000)).catch(() => '');
    return {
      status: 'error',
      error: 'No offer extracted — wizard finished without a dollar amount',
      details: { vin, mileage, zip, condition, url: page.url(), title, bodySnippet, launchMethod },
      wizardLog,
    };
  } catch (err) {
    log(`[carmax] ERROR: ${err.message}`);
    return {
      status: 'error',
      error: err.message,
      details: { vin, mileage, zip, condition, launchMethod },
      wizardLog,
    };
  } finally {
    await closeBrowser(browser);
    console.log(`[carmax] flow completed in ${Math.round(elapsed() / 1000)}s`);
  }
}

async function getCarmaxOffer(params) {
  if (activeRun) {
    console.log('[carmax] Another run active — queuing (up to 5 min)');
    try { await Promise.race([activeRun, new Promise((_, rej) => setTimeout(() => rej(new Error('queue timeout')), 300_000))]); }
    catch (e) { console.log(`[carmax] queue wait: ${e.message}`); }
  }
  activeRun = (async () => {
    try { return await _getCarmaxOfferImpl(params); }
    finally { activeRun = null; }
  })();
  return activeRun;
}

module.exports = { getCarmaxOffer };
