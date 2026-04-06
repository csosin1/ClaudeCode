const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const config = require('./config');

// Apply stealth plugin to avoid bot detection
chromium.use(StealthPlugin());

const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

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
 * Launch a stealth Chromium browser with optional residential proxy.
 * Returns { browser, page }.
 */
async function launchBrowser(options = {}) {
  const args = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-software-rasterizer',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-default-apps',
    '--disable-sync',
    '--disable-translate',
    '--no-first-run',
    '--no-zygote',
    '--single-process',
    '--mute-audio',
  ];

  // Build proxy config
  // NOTE: Decodo session suffix (-session-xxx) causes auth failure.
  // Use plain username for now. Sticky sessions may need a different format.
  let proxyConfig = null;
  if (config.PROXY_HOST && config.PROXY_PASS) {
    const proxyPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');

    proxyConfig = {
      server: `http://${config.PROXY_HOST}:${proxyPort}`,
      username: config.PROXY_USER,
      password: config.PROXY_PASS,
    };
    console.log(`[browser] Using proxy: ${config.PROXY_HOST}:${proxyPort} user=${config.PROXY_USER}`);
  } else {
    console.log('[browser] No proxy configured — using direct connection');
  }

  const launchOptions = {
    headless: true,
    args,
  };
  if (proxyConfig) {
    launchOptions.proxy = proxyConfig;
  }

  // Try playwright-extra (stealth) first, fall back to regular playwright
  let browser;
  try {
    browser = await chromium.launch(launchOptions);
    console.log('[browser] Launched via playwright-extra (stealth)');
  } catch (stealthErr) {
    console.warn(`[browser] playwright-extra launch failed: ${stealthErr.message}`);
    console.log('[browser] Falling back to regular playwright...');
    try {
      const pw = require('playwright');
      browser = await pw.chromium.launch(launchOptions);
      console.log('[browser] Launched via regular playwright');
    } catch (fallbackErr) {
      console.error(`[browser] Regular playwright also failed: ${fallbackErr.message}`);
      throw new Error(`Browser launch failed. Stealth: ${stealthErr.message}. Fallback: ${fallbackErr.message}`);
    }
  }

  const context = await browser.newContext({
    userAgent: USER_AGENT,
    viewport: { width: 1920, height: 1080 },
    locale: 'en-US',
    timezoneId: 'America/New_York',
    ...options,
  });

  const page = await context.newPage();

  return { browser, page };
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
};
