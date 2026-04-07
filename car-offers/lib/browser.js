const config = require('./config');

const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

/**
 * Random delay between min and max milliseconds.
 */
function humanDelay(min = 2000, max = 5000) {
  const ms = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Type text character-by-character with random delays to mimic human typing.
 */
async function humanType(page, selector, text) {
  const el = await page.waitForSelector(selector, { timeout: 15000 });
  await el.click();
  for (const char of text) {
    await el.type(char, { delay: 0 });
    const pause = Math.floor(Math.random() * 100) + 50; // 50-150ms
    await new Promise((r) => setTimeout(r, pause));
  }
}

/**
 * Move mouse to a random point near an element before interacting.
 */
async function randomMouseMove(page, selector) {
  try {
    const el = await page.waitForSelector(selector, { timeout: 10000 });
    const box = await el.boundingBox();
    if (box) {
      const x = box.x + box.width * Math.random();
      const y = box.y + box.height * Math.random();
      await page.mouse.move(x, y, { steps: Math.floor(Math.random() * 5) + 3 });
    }
  } catch {
    // Non-critical — continue
  }
}

/**
 * Inject anti-detection scripts into the page context.
 * This patches navigator properties that PerimeterX/Cloudflare check.
 */
async function injectStealth(context) {
  await context.addInitScript(() => {
    // 1. Hide webdriver flag (biggest detection signal)
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. Override navigator.plugins (headless has empty array)
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        return [
          { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
          { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
          { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
      },
    });

    // 3. Override navigator.languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

    // 4. Fake window.chrome object (missing in headless)
    if (!window.chrome) {
      window.chrome = {
        runtime: { connect: () => {}, sendMessage: () => {} },
        loadTimes: () => ({}),
        csi: () => ({}),
      };
    }

    // 5. Override permissions query (headless returns 'denied' for notifications)
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => {
      if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
      }
      return originalQuery(parameters);
    };

    // 6. Fix WebGL vendor/renderer (SwiftShader is a headless giveaway)
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
      if (parameter === 37445) return 'Intel Inc.'; // UNMASKED_VENDOR_WEBGL
      if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
      return getParameter.call(this, parameter);
    };

    // 7. Prevent iframe contentWindow detection
    const originalAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function () {
      return originalAttachShadow.apply(this, arguments);
    };

    // 8. Fix chrome.runtime to not throw errors
    if (window.chrome && window.chrome.runtime) {
      window.chrome.runtime.id = undefined;
    }
  });
}

/**
 * Simulate human-like initial browsing behavior.
 */
async function simulateHumanBehavior(page) {
  try {
    // Random mouse movements
    for (let i = 0; i < 3; i++) {
      const x = 200 + Math.floor(Math.random() * 800);
      const y = 200 + Math.floor(Math.random() * 400);
      await page.mouse.move(x, y, { steps: Math.floor(Math.random() * 10) + 5 });
      await new Promise(r => setTimeout(r, Math.floor(Math.random() * 500) + 200));
    }
    // Small scroll
    await page.mouse.wheel(0, Math.floor(Math.random() * 200) + 50);
    await new Promise(r => setTimeout(r, Math.floor(Math.random() * 1000) + 500));
  } catch {
    // Non-critical
  }
}

/**
 * Launch a stealth Chromium browser with residential proxy.
 * Returns { browser, page }.
 *
 * Strategy: Try playwright-extra stealth first (patches many detections
 * at the CDP level). Fall back to regular playwright + manual injection.
 */
async function launchBrowser(options = {}) {
  // Use headed mode if DISPLAY is available (Xvfb virtual display)
  const useHeaded = !!process.env.DISPLAY;

  // Minimal args for headed mode — fewer flags = less detection surface
  // In headless mode, add more flags for stability on servers
  const args = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--window-size=1920,1080',
    '--window-position=0,0',
  ];

  if (!useHeaded) {
    // Only add these in headless mode where we need extra stability
    args.push(
      '--disable-gpu',
      '--disable-software-rasterizer',
      '--disable-extensions',
      '--disable-background-networking',
      '--no-first-run',
      '--mute-audio',
    );
  } else {
    // Headed mode: look like a real user's Chrome
    args.push(
      '--start-maximized',
      '--enable-features=NetworkService,NetworkServiceInProcess',
    );
  }

  // Build proxy config
  // Decodo geo-targeting: use port 7000 with user- prefix and country/zip params
  // Add session stickiness to keep the same IP for the entire browser session
  // This prevents Cloudflare from seeing IP changes mid-flow
  let proxyConfig = null;
  if (config.PROXY_HOST && config.PROXY_PASS) {
    const proxyPort = '7000';
    const sessionId = `carvana${Date.now()}`;
    const proxyUser = `user-${config.PROXY_USER}-country-us-zip-06880-session-${sessionId}-sessionduration-30`;
    proxyConfig = {
      server: `http://${config.PROXY_HOST}:${proxyPort}`,
      username: proxyUser,
      password: config.PROXY_PASS,
    };
    console.log(`[browser] Using proxy: ${config.PROXY_HOST}:${proxyPort} session=${sessionId}`);
  } else {
    console.log('[browser] No proxy configured — using direct connection');
  }

  if (useHeaded) {
    console.log(`[browser] Using HEADED mode (DISPLAY=${process.env.DISPLAY})`);
  } else {
    console.log('[browser] Using headless mode (no DISPLAY set)');
  }

  const launchOptions = { headless: !useHeaded, args };
  if (proxyConfig) {
    launchOptions.proxy = proxyConfig;
  }

  // Priority order:
  // 1. Patchright — patches CDP Runtime.enable leak (Cloudflare's #1 detection)
  // 2. playwright-extra + stealth plugin — patches many browser fingerprints
  // 3. Regular playwright — baseline fallback
  let browser;
  let usedStealth = false;
  let launchMethod = 'unknown';
  try {
    const { chromium } = require('patchright');
    browser = await chromium.launch(launchOptions);
    launchMethod = 'patchright';
    usedStealth = true;
    console.log('[browser] Launched via patchright (CDP leak patched — best stealth)');
  } catch (patchErr) {
    console.warn(`[browser] Patchright launch failed: ${patchErr.message}`);
    try {
      const { chromium } = require('playwright-extra');
      const StealthPlugin = require('puppeteer-extra-plugin-stealth');
      chromium.use(StealthPlugin());
      browser = await chromium.launch(launchOptions);
      usedStealth = true;
      launchMethod = 'playwright-extra';
      console.log('[browser] Launched via playwright-extra (stealth plugin)');
    } catch (stealthErr) {
      console.warn(`[browser] Stealth launch failed: ${stealthErr.message}`);
      console.log('[browser] Falling back to regular playwright + manual anti-detection...');
      const pw = require('playwright');
      browser = await pw.chromium.launch(launchOptions);
      launchMethod = 'playwright';
      console.log('[browser] Launched via regular playwright');
    }
  }

  const context = await browser.newContext({
    userAgent: USER_AGENT,
    viewport: { width: 1920, height: 1080 },
    locale: 'en-US',
    timezoneId: 'America/New_York',
    // Extra headers to look more human
    extraHTTPHeaders: {
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
      'sec-ch-ua': '"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="24"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"',
    },
    ...options,
  });

  // Always inject manual anti-detection (complements patchright/stealth plugin)
  await injectStealth(context);
  console.log(`[browser] Launch method: ${launchMethod} | Manual anti-detection: injected`);

  const page = await context.newPage();
  return { browser, page, launchMethod };
}

/**
 * Safely close a browser instance.
 */
async function closeBrowser(browser) {
  try {
    if (browser) await browser.close();
  } catch {
    // Ignore close errors
  }
}

module.exports = {
  launchBrowser,
  humanDelay,
  humanType,
  randomMouseMove,
  closeBrowser,
  simulateHumanBehavior,
};
