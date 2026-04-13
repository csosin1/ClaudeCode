/**
 * Shopper warmup — "act like a real used-car shopper" before the sell flow.
 *
 * Cloudflare Turnstile's interactive score is built from pre-submission
 * behavior. A session that lands directly on /sell-my-car, fills a form,
 * and submits looks nothing like an actual seller — real sellers usually
 * browse inventory, poke around, THEN go sell. This module replays that.
 *
 * Two entry points:
 *   - fullWarmup(page, log): 10-15 min browse. Called once per N hours
 *     against a fresh profile (or after a forced reset). Builds real
 *     cookies / localStorage that aren't replayable by a headless bot.
 *   - miniBrowse(page, log): ~2-3 min browse right before the sell flow.
 *     Establishes recency — Carvana sees "I was just on this site".
 *
 * Both use randomized action order so accumulated behavior doesn't look
 * identical across runs.
 */

const {
  humanDelay, microDelay, bezierMouseMove,
  simulateHumanBehavior, simulateBlurFocus, startMouseDrift,
} = require('./browser');

/** Slow scroll — emits multiple wheel events like a real scroll gesture. */
async function slowScroll(page, totalPx, opts = {}) {
  const steps = opts.steps || 8 + Math.floor(Math.random() * 6);
  const direction = totalPx >= 0 ? 1 : -1;
  const stepPx = Math.abs(totalPx) / steps;
  for (let i = 0; i < steps; i++) {
    try {
      await page.mouse.wheel(0, direction * (stepPx + (Math.random() - 0.5) * stepPx * 0.3));
    } catch { /* page may navigate */ }
    await microDelay(80, 260);
  }
}

/** Try several selectors; return the first visible ElementHandle, or null. */
async function firstVisible(page, selectors) {
  for (const sel of selectors) {
    try {
      const el = await page.$(sel);
      if (el && await el.isVisible()) return { el, sel };
    } catch { continue; }
  }
  return null;
}

/** Hover over an element via bezier move, without clicking. */
async function hoverElement(page, el) {
  try {
    const box = await el.boundingBox();
    if (!box) return;
    const x = box.x + box.width * (0.3 + Math.random() * 0.4);
    const y = box.y + box.height * (0.3 + Math.random() * 0.4);
    await bezierMouseMove(page, x, y);
  } catch { /* non-critical */ }
}

/** Action: land on the homepage and scroll around like a window-shopper. */
async function actionHomepage(page, log) {
  log('[warmup] Homepage browse');
  try {
    await page.goto('https://www.carvana.com/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  } catch (e) {
    log(`[warmup] Homepage nav failed: ${e.message}`);
    return;
  }
  try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch { /* ok */ }
  await humanDelay(3000, 7000);

  // Scroll down slowly, pause, scroll up a bit (humans re-read), scroll back
  await slowScroll(page, 600 + Math.random() * 400);
  await humanDelay(2000, 5000);
  await slowScroll(page, -200 - Math.random() * 100); // re-read
  await humanDelay(1500, 3500);
  await slowScroll(page, 500 + Math.random() * 400);
  await humanDelay(2000, 4000);
  await simulateHumanBehavior(page);
}

/** Action: browse the shop-used-cars listing page, hover cards, scroll. */
async function actionBrowseListings(page, log) {
  log('[warmup] Browse used-cars listings');
  try {
    await page.goto('https://www.carvana.com/cars', { waitUntil: 'domcontentloaded', timeout: 45000 });
  } catch (e) {
    log(`[warmup] Listings nav failed: ${e.message}`);
    return;
  }
  try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch { /* ok */ }
  await humanDelay(3000, 6000);

  // Hover a few result cards
  const cards = await page.$$('[data-testid*="vehicle-card"], a[href*="/vehicle/"], [class*="vehicle-card"], [class*="result-tile"]').catch(() => []);
  const hoverCount = Math.min(cards.length, 2 + Math.floor(Math.random() * 3));
  for (let i = 0; i < hoverCount; i++) {
    const card = cards[Math.floor(Math.random() * cards.length)];
    if (!card) continue;
    await hoverElement(page, card);
    await humanDelay(800, 2500);
  }
  await slowScroll(page, 800 + Math.random() * 600);
  await humanDelay(2000, 4500);
  await slowScroll(page, 400 + Math.random() * 400);
  await humanDelay(1500, 3500);
}

/** Action: click into one vehicle detail, scroll photos/description. */
async function actionVehicleDetail(page, log) {
  log('[warmup] Click into a vehicle detail page');
  // Find any vehicle card link
  const cardLink = await firstVisible(page, [
    'a[href*="/vehicle/"]',
    '[data-testid*="vehicle-card"] a',
  ]);
  if (!cardLink) {
    log('[warmup] No vehicle card found — skipping detail');
    return;
  }
  try {
    const box = await cardLink.el.boundingBox();
    if (box) {
      await bezierMouseMove(page, box.x + box.width * 0.5, box.y + box.height * 0.5);
      await humanDelay(400, 900);
      await cardLink.el.click();
    }
  } catch (e) {
    log(`[warmup] Vehicle click failed: ${e.message}`);
    return;
  }
  try { await page.waitForLoadState('domcontentloaded', { timeout: 20000 }); } catch { /* ok */ }
  await humanDelay(4000, 8000);

  // Scroll through photos/description/specs
  await slowScroll(page, 500 + Math.random() * 400);
  await humanDelay(3000, 6000);
  await slowScroll(page, 600 + Math.random() * 400);
  await humanDelay(4000, 9000);
  await slowScroll(page, -300 - Math.random() * 200); // re-read
  await humanDelay(2000, 4000);

  // Occasional alt-tab blur/focus
  if (Math.random() < 0.5) {
    log('[warmup] Simulating alt-tab blur/focus');
    await simulateBlurFocus(page);
  }

  await humanDelay(3000, 7000);

  // Navigate back
  try {
    await page.goBack({ waitUntil: 'domcontentloaded', timeout: 20000 });
  } catch { /* ok */ }
  await humanDelay(2500, 5000);
}

/** Action: run a quick search-filter interaction (brand name). */
async function actionSearchFilter(page, log) {
  log('[warmup] Try search/filter interaction');
  // Just do another listings page with a different URL pattern
  const makes = ['honda', 'toyota', 'ford', 'chevrolet'];
  const pick = makes[Math.floor(Math.random() * makes.length)];
  try {
    await page.goto(`https://www.carvana.com/cars/${pick}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  } catch (e) {
    log(`[warmup] Filter nav failed: ${e.message}`);
    return;
  }
  await humanDelay(3000, 6000);
  await slowScroll(page, 700 + Math.random() * 500);
  await humanDelay(2000, 4500);
}

/** Shuffle an array in place (Fisher-Yates). */
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

/**
 * Full warmup — 10-15 minutes of browsing. Randomized action order.
 * Call only when the profile is fresh or expired.
 */
async function fullWarmup(page, log) {
  const stopDrift = startMouseDrift(page);
  try {
    log('[warmup] FULL warmup starting (10-15 min browse)');
    // Homepage is always first — establishes session cookies
    await actionHomepage(page, log);

    const secondary = shuffle([
      () => actionBrowseListings(page, log),
      () => actionVehicleDetail(page, log),
      () => actionSearchFilter(page, log),
      () => actionBrowseListings(page, log), // double-up to stretch duration
    ]);
    for (const a of secondary) {
      await a();
      await humanDelay(4000, 9000);
    }
    log('[warmup] FULL warmup complete');
  } finally {
    stopDrift();
  }
}

/**
 * Mini warmup — 2-3 minutes. Homepage → one listing → one detail. Used
 * before the sell flow on every run so the behavioral score has something
 * to grade rather than a cold jump to /sell-my-car.
 */
async function miniBrowse(page, log) {
  const stopDrift = startMouseDrift(page);
  try {
    log('[warmup] MINI browse (homepage → listings → detail)');
    await actionHomepage(page, log);
    const actions = shuffle([
      () => actionBrowseListings(page, log),
      () => actionVehicleDetail(page, log),
    ]);
    // Only one of the two to keep it quick.
    await actions[0]();
    log('[warmup] MINI browse complete');
  } finally {
    stopDrift();
  }
}

module.exports = { fullWarmup, miniBrowse };
