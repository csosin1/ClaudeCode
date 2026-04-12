const fs = require('fs');
const path = require('path');
const config = require('./config');

const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

// Persistent Chrome profile — makes the browser "look aged" (cookies,
// localStorage, history). This is patchright's single biggest recommendation
// for Cloudflare Turnstile success: ephemeral /tmp profiles get flagged.
const USER_DATA_DIR = path.join(__dirname, '..', '.chrome-profile');

// Sticky proxy session — keep the same residential IP across runs. Cloudflare
// treats "new IP + new fingerprint every request" as bot-like. 23h TTL so we
// refresh before Decodo's 24h max-session expires.
const SESSION_FILE = path.join(__dirname, '..', '.proxy-session');
const SESSION_TTL_MS = 23 * 60 * 60 * 1000;

function getOrCreateProxySession() {
  try {
    const raw = fs.readFileSync(SESSION_FILE, 'utf8');
    const data = JSON.parse(raw);
    if (data.sessionId && data.createdAt && Date.now() - data.createdAt < SESSION_TTL_MS) {
      return data.sessionId;
    }
  } catch { /* no session or expired */ }
  const sessionId = `stick${Math.random().toString(36).slice(2, 10)}`;
  try {
    fs.writeFileSync(SESSION_FILE, JSON.stringify({ sessionId, createdAt: Date.now() }));
  } catch { /* non-fatal */ }
  return sessionId;
}

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
    const pause = Math.floor(Math.random() * 100) + 50;
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
  } catch { /* non-critical */ }
}

/**
 * Start a background mouse-drift task. Humans don't hold the mouse perfectly
 * still — they drift a few pixels while reading/typing. Returns a stop fn.
 */
function startMouseDrift(page) {
  let stopped = false;
  let x = 600 + Math.random() * 400;
  let y = 400 + Math.random() * 200;
  (async () => {
    while (!stopped) {
      try {
        x += (Math.random() - 0.5) * 40;
        y += (Math.random() - 0.5) * 30;
        x = Math.max(100, Math.min(1800, x));
        y = Math.max(100, Math.min(1000, y));
        await page.mouse.move(x, y, { steps: 3 + Math.floor(Math.random() * 4) });
      } catch { /* page may be navigating */ }
      await new Promise((r) => setTimeout(r, 400 + Math.random() * 600));
    }
  })().catch(() => {});
  return () => { stopped = true; };
}

/**
 * Inject anti-detection scripts into the page context.
 */
async function injectStealth(context) {
  await context.addInitScript(() => {
    // 1. webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. Plugins
    Object.defineProperty(navigator, 'plugins', {
      get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
      ],
    });

    // 3. Languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

    // 4. Fake window.chrome
    if (!window.chrome) {
      window.chrome = {
        runtime: { connect: () => {}, sendMessage: () => {} },
        loadTimes: () => ({}),
        csi: () => ({}),
      };
    }

    // 5. permissions.query
    const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (originalQuery) {
      window.navigator.permissions.query = (parameters) => {
        if (parameters && parameters.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission });
        }
        return originalQuery.call(window.navigator.permissions, parameters);
      };
    }

    // 6. WebGL vendor/renderer
    try {
      const getParameter = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, parameter);
      };
    } catch { /* ignore */ }

    // 7. WebRTC leak block — critical. Without this, headed Chrome can leak
    //    the server's real IP via STUN requests, contradicting the proxy IP
    //    and instantly flagging us as a bot.
    try {
      const blockedRTC = function () { throw new Error('WebRTC disabled'); };
      window.RTCPeerConnection = blockedRTC;
      window.webkitRTCPeerConnection = blockedRTC;
      window.RTCDataChannel = blockedRTC;
      if (navigator.mediaDevices) {
        navigator.mediaDevices.enumerateDevices = () => Promise.resolve([]);
      }
    } catch { /* ignore */ }

    // 8. chrome.runtime.id removal
    if (window.chrome && window.chrome.runtime) {
      window.chrome.runtime.id = undefined;
    }

    // 9. Hardware concurrency — match a typical Win10 machine
    try {
      Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
      Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    } catch { /* ignore */ }
  });
}

/**
 * Launch a persistent-context stealth Chromium.
 * Persistent context is critical for Cloudflare Turnstile — a fresh /tmp
 * profile is a strong bot signal. We keep the profile directory around so
 * cookies, localStorage, and cache age naturally across runs.
 */
async function launchBrowser(_options = {}) {
  // Ensure profile dir exists
  try { fs.mkdirSync(USER_DATA_DIR, { recursive: true }); } catch { /* exists */ }

  const useHeaded = !!process.env.DISPLAY;

  const args = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--window-size=1920,1080',
    '--window-position=0,0',
    // WebRTC leak block at the browser level — complements the JS init script
    '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--force-webrtc-ip-handling-policy',
  ];
  if (!useHeaded) {
    args.push('--disable-gpu', '--disable-software-rasterizer', '--disable-extensions',
      '--disable-background-networking', '--no-first-run', '--mute-audio');
  } else {
    args.push('--start-maximized', '--enable-features=NetworkService,NetworkServiceInProcess');
  }

  // Sticky proxy config
  let proxyConfig = null;
  if (config.PROXY_HOST && config.PROXY_PASS) {
    const proxyPort = '7000';
    const sessionId = getOrCreateProxySession();
    const proxyUser = `user-${config.PROXY_USER}-country-us-zip-06880-session-${sessionId}-sessionduration-1440`;
    proxyConfig = {
      server: `http://${config.PROXY_HOST}:${proxyPort}`,
      username: proxyUser,
      password: config.PROXY_PASS,
    };
    console.log(`[browser] Using proxy: ${config.PROXY_HOST}:${proxyPort} stickySession=${sessionId}`);
  } else {
    console.log('[browser] No proxy configured — using direct connection');
  }

  console.log(`[browser] Headed=${useHeaded} (DISPLAY=${process.env.DISPLAY || 'unset'}) profile=${USER_DATA_DIR}`);

  const contextOptions = {
    headless: !useHeaded,
    args,
    viewport: { width: 1920, height: 1080 },
    userAgent: USER_AGENT,
    locale: 'en-US',
    timezoneId: 'America/New_York',
    extraHTTPHeaders: {
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
      'sec-ch-ua': '"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="24"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"',
    },
  };
  if (proxyConfig) contextOptions.proxy = proxyConfig;

  // Priority: patchright → playwright-extra → plain playwright.
  // launchPersistentContext returns a BrowserContext directly (no .newContext).
  let context;
  let launchMethod = 'unknown';
  try {
    const { chromium } = require('patchright');
    context = await chromium.launchPersistentContext(USER_DATA_DIR, contextOptions);
    launchMethod = 'patchright-persistent';
    console.log('[browser] Launched via patchright launchPersistentContext');
  } catch (patchErr) {
    console.warn(`[browser] Patchright persistent launch failed: ${patchErr.message}`);
    try {
      const { chromium } = require('playwright-extra');
      const StealthPlugin = require('puppeteer-extra-plugin-stealth');
      chromium.use(StealthPlugin());
      context = await chromium.launchPersistentContext(USER_DATA_DIR, contextOptions);
      launchMethod = 'playwright-extra-persistent';
      console.log('[browser] Launched via playwright-extra launchPersistentContext');
    } catch (stealthErr) {
      console.warn(`[browser] Stealth persistent launch failed: ${stealthErr.message}`);
      const pw = require('playwright');
      context = await pw.chromium.launchPersistentContext(USER_DATA_DIR, contextOptions);
      launchMethod = 'playwright-persistent';
      console.log('[browser] Launched via plain playwright launchPersistentContext');
    }
  }

  await injectStealth(context);

  // Persistent context ships with a default page; reuse it so the profile's
  // pre-existing session storage applies.
  const pages = context.pages();
  const page = pages.length > 0 ? pages[0] : await context.newPage();

  // We return the context as `browser` for backwards compatibility with the
  // caller, which only uses .close() — BrowserContext has the same method.
  return { browser: context, page, launchMethod };
}

/**
 * Safely close a browser/context instance.
 */
async function closeBrowser(browser) {
  try {
    if (browser) await browser.close();
  } catch { /* ignore close errors */ }
}

/**
 * Simulate human-like initial browsing behavior.
 */
async function simulateHumanBehavior(page) {
  try {
    for (let i = 0; i < 3; i++) {
      const x = 200 + Math.floor(Math.random() * 800);
      const y = 200 + Math.floor(Math.random() * 400);
      await page.mouse.move(x, y, { steps: Math.floor(Math.random() * 10) + 5 });
      await new Promise(r => setTimeout(r, Math.floor(Math.random() * 500) + 200));
    }
    await page.mouse.wheel(0, Math.floor(Math.random() * 200) + 50);
    await new Promise(r => setTimeout(r, Math.floor(Math.random() * 1000) + 500));
  } catch { /* non-critical */ }
}

module.exports = {
  launchBrowser,
  humanDelay,
  humanType,
  randomMouseMove,
  closeBrowser,
  simulateHumanBehavior,
  startMouseDrift,
};
