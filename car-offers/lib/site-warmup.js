/**
 * Generic per-site mini-browse warmup.
 *
 * The original shopper-warmup.js hardcodes carvana.com URLs. For multi-site
 * comparison we need to warm cookies on carmax.com and driveway.com too.
 * This module is a small, site-agnostic wrapper that does homepage -> one
 * listings page -> back, with the same human-feel scroll / hover / blur
 * tricks as shopper-warmup.js — just taking the base URL as an arg.
 *
 * Intentionally short (60-120s). The FULL warmup still lives in
 * shopper-warmup.js and only runs against carvana.com because that's the
 * profile-level warmup marker (browser.js's profile-warm check). For each
 * subsequent site in a comparison run we only need a light cookie warm so
 * the "Referer: <site>.com" and site-specific cookies exist before the
 * sell flow fires.
 */

const {
  humanDelay, microDelay, bezierMouseMove,
  simulateHumanBehavior, startMouseDrift,
} = require('./browser');

async function slowScroll(page, totalPx, opts = {}) {
  const steps = opts.steps || 6 + Math.floor(Math.random() * 4);
  const direction = totalPx >= 0 ? 1 : -1;
  const stepPx = Math.abs(totalPx) / steps;
  for (let i = 0; i < steps; i++) {
    try {
      await page.mouse.wheel(0, direction * (stepPx + (Math.random() - 0.5) * stepPx * 0.3));
    } catch { /* nav */ }
    await microDelay(80, 260);
  }
}

/**
 * Warm a site's cookies by visiting homepage and one inventory page.
 *
 * @param {import('playwright').Page} page
 * @param {Object} site
 * @param {string} site.homepage  e.g. 'https://www.carmax.com/'
 * @param {string} [site.inventory]  e.g. 'https://www.carmax.com/cars'
 * @param {Function} log - log(msg) function from caller
 */
async function siteWarmup(page, site, log) {
  const stopDrift = startMouseDrift(page);
  try {
    log(`[site-warmup] visiting ${site.homepage}`);
    try {
      await page.goto(site.homepage, { waitUntil: 'domcontentloaded', timeout: 45000 });
    } catch (e) {
      log(`[site-warmup] homepage nav failed: ${e.message}`);
      return;
    }
    try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch { /* ok */ }
    await humanDelay(3000, 6000);
    await slowScroll(page, 500 + Math.random() * 400);
    await humanDelay(2000, 4000);
    await slowScroll(page, -200);
    await humanDelay(1500, 3000);
    await simulateHumanBehavior(page);

    if (site.inventory) {
      log(`[site-warmup] visiting ${site.inventory}`);
      try {
        await page.goto(site.inventory, { waitUntil: 'domcontentloaded', timeout: 45000 });
      } catch (e) {
        log(`[site-warmup] inventory nav failed: ${e.message}`);
        return;
      }
      try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch { /* ok */ }
      await humanDelay(3000, 6000);
      await slowScroll(page, 700 + Math.random() * 500);
      await humanDelay(2500, 5000);
    }
    log('[site-warmup] done');
  } finally {
    stopDrift();
  }
}

module.exports = { siteWarmup };
