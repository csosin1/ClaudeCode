const fs = require('fs');
const path = require('path');
const config = require('./config');
const { pickProfile, pickProfileByIndex } = require('./fingerprint');
const { buildStealthInitScript } = require('./stealth-init');

// ---------------------------------------------------------------------------
// Per-consumer isolated state
// ---------------------------------------------------------------------------
// Every consumer in the panel gets their OWN persistent Chrome profile and
// their OWN sticky proxy session. Without isolation, one flagged session
// would contaminate everyone — a panel is only useful if each consumer looks
// like a distinct real person over time.
//
// Filesystem layout (all excluded from rsync / git):
//   .chrome-profiles/cons01/       <- patchright user-data-dir
//   .chrome-profiles/cons01.warmup <- marker file for shopper warmup age
//   .proxy-sessions/cons01.json    <- { sessionId, createdAt } for Decodo
//
// Legacy single-profile paths (.chrome-profile/, .proxy-session,
// .profile-warmup) are still honored when launchBrowser() is called without
// a consumerId so the existing /api/carvana / /api/carmax / /api/driveway
// endpoints don't break.

const LEGACY_USER_DATA_DIR = path.join(__dirname, '..', '.chrome-profile');
const LEGACY_SESSION_FILE  = path.join(__dirname, '..', '.proxy-session');
const LEGACY_WARMUP_FILE   = path.join(__dirname, '..', '.profile-warmup');

const CHROME_PROFILES_DIR  = path.join(__dirname, '..', '.chrome-profiles');
const PROXY_SESSIONS_DIR   = path.join(__dirname, '..', '.proxy-sessions');

const SESSION_TTL_MS = 23 * 60 * 60 * 1000;

/** Normalize a consumerId into a filesystem-safe slug (e.g. 1 -> "cons01"). */
function _consumerSlug(consumerId) {
  if (consumerId == null) return null;
  const raw = String(consumerId).trim();
  if (!raw) return null;
  // If the caller already passed a slug like "cons01", keep it.
  if (/^cons\d+$/i.test(raw)) return raw.toLowerCase();
  const n = Number(raw);
  if (Number.isFinite(n) && n >= 0) {
    return `cons${String(Math.floor(n)).padStart(2, '0')}`;
  }
  // Fallback: strip any non-alphanumeric and prefix.
  return `cons${raw.replace(/[^a-zA-Z0-9]/g, '').slice(0, 16).toLowerCase()}`;
}

/** Resolve per-consumer filesystem paths. Legacy fallback when slug is null. */
function _pathsForConsumer(slug) {
  if (!slug) {
    return {
      userDataDir: LEGACY_USER_DATA_DIR,
      sessionFile: LEGACY_SESSION_FILE,
      warmupFile:  LEGACY_WARMUP_FILE,
      slug: null,
    };
  }
  return {
    userDataDir: path.join(CHROME_PROFILES_DIR, slug),
    sessionFile: path.join(PROXY_SESSIONS_DIR, `${slug}.json`),
    warmupFile:  path.join(CHROME_PROFILES_DIR, `${slug}.warmup`),
    slug,
  };
}

/**
 * Get or create the sticky proxy session id for a consumer (or for the
 * legacy single-profile path when sessionFile points at .proxy-session).
 *
 * For a consumer the sessionId uses a deterministic base seed so the same
 * residential IP is preserved across browser launches within the 23h TTL —
 * and when the TTL rolls, the NEXT session still embeds the slug so the
 * consumer remains distinct from their siblings.
 */
function getOrCreateProxySession(sessionFile, slug) {
  try {
    const raw = fs.readFileSync(sessionFile, 'utf8');
    const data = JSON.parse(raw);
    if (data.sessionId && data.createdAt && Date.now() - data.createdAt < SESSION_TTL_MS) {
      return data.sessionId;
    }
  } catch { /* no session or expired */ }
  const suffix = Math.random().toString(36).slice(2, 8);
  const sessionId = slug ? `${slug}-stick-${suffix}` : `stick${Math.random().toString(36).slice(2, 10)}`;
  try {
    fs.mkdirSync(path.dirname(sessionFile), { recursive: true });
    fs.writeFileSync(sessionFile, JSON.stringify({ sessionId, createdAt: Date.now() }));
  } catch { /* non-fatal */ }
  return sessionId;
}

/**
 * Log-normal-ish human delay. Skewed right so rare long pauses look natural.
 * Mean tuned to ~((min+max)/2) with a long tail approaching max*1.6.
 */
function humanDelay(min = 2000, max = 5000) {
  const u = Math.max(0.001, Math.min(0.999, Math.random()));
  const base = -Math.log(1 - u) * ((min + max) / 4);
  const ms = Math.max(min, Math.min(max * 1.6, Math.round(base + min)));
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Short delay helper (per-character, between clicks, etc). */
function microDelay(min = 50, max = 200) {
  const ms = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Human-style typing with a WPM distribution.
 * Most chars: 150-350ms. Every ~8 chars, a longer 500-950ms "reading" pause.
 * Prevents constant-rhythm robot typing that CAPTCHA systems key on.
 */
async function humanType(page, selector, text) {
  const el = typeof selector === 'string'
    ? await page.waitForSelector(selector, { timeout: 15000 })
    : selector;
  try { await el.click(); } catch { /* already focused */ }
  await microDelay(100, 300);
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    await el.type(char, { delay: 0 });
    const isPause = Math.random() < 0.12;
    const d = isPause
      ? 500 + Math.random() * 450
      : 120 + Math.random() * 230;
    await new Promise((r) => setTimeout(r, d));
  }
}

/** Cubic-bezier point at t between p0..p3 (control points). */
function bezierPoint(t, p0, p1, p2, p3) {
  const u = 1 - t;
  const tt = t * t, uu = u * u, uuu = uu * u, ttt = tt * t;
  return {
    x: uuu * p0.x + 3 * uu * t * p1.x + 3 * u * tt * p2.x + ttt * p3.x,
    y: uuu * p0.y + 3 * uu * t * p1.y + 3 * u * tt * p2.y + ttt * p3.y,
  };
}

/**
 * Move the mouse along a cubic bezier with jitter. Real humans don't move
 * in straight lines — linear mouse.move calls are a well-known tell.
 */
async function bezierMouseMove(page, toX, toY, opts = {}) {
  const steps = opts.steps || 18 + Math.floor(Math.random() * 16);
  const from = page.__lastMousePos || { x: 600 + Math.random() * 300, y: 400 + Math.random() * 200 };
  const dx = toX - from.x, dy = toY - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const spread = Math.min(220, dist * 0.35 + 30);
  const midX = from.x + dx * 0.4 + (Math.random() - 0.5) * spread;
  const midY = from.y + dy * 0.4 + (Math.random() - 0.5) * spread;
  const midX2 = from.x + dx * 0.75 + (Math.random() - 0.5) * spread * 0.6;
  const midY2 = from.y + dy * 0.75 + (Math.random() - 0.5) * spread * 0.6;
  const p0 = from, p1 = { x: midX, y: midY }, p2 = { x: midX2, y: midY2 }, p3 = { x: toX, y: toY };
  for (let i = 1; i <= steps; i++) {
    // Ease-in-out shaping so the cursor slows at both ends.
    const rawT = i / steps;
    const t = (rawT * rawT) / (rawT * rawT + (1 - rawT) * (1 - rawT));
    const pt = bezierPoint(t, p0, p1, p2, p3);
    const jx = pt.x + (Math.random() - 0.5) * 1.5;
    const jy = pt.y + (Math.random() - 0.5) * 1.5;
    try { await page.mouse.move(jx, jy); } catch { /* page may navigate */ }
    await new Promise((r) => setTimeout(r, 6 + Math.floor(Math.random() * 14)));
  }
  page.__lastMousePos = { x: toX, y: toY };
}

/** Bezier-move mouse to a random point inside the element's bbox. */
async function randomMouseMove(page, selector) {
  try {
    const el = typeof selector === 'string'
      ? await page.waitForSelector(selector, { timeout: 10000 })
      : selector;
    const box = await el.boundingBox();
    if (box) {
      const x = box.x + box.width * (0.25 + Math.random() * 0.5);
      const y = box.y + box.height * (0.25 + Math.random() * 0.5);
      await bezierMouseMove(page, x, y);
    }
  } catch { /* non-critical */ }
}

/** Background mouse drift while reading — stops on returned fn. */
function startMouseDrift(page) {
  let stopped = false;
  let x = (page.__lastMousePos && page.__lastMousePos.x) || 600 + Math.random() * 400;
  let y = (page.__lastMousePos && page.__lastMousePos.y) || 400 + Math.random() * 200;
  (async () => {
    while (!stopped) {
      try {
        x += (Math.random() - 0.5) * 40;
        y += (Math.random() - 0.5) * 30;
        x = Math.max(100, Math.min(1800, x));
        y = Math.max(100, Math.min(1000, y));
        await page.mouse.move(x, y);
        page.__lastMousePos = { x, y };
      } catch { /* page may be navigating */ }
      await new Promise((r) => setTimeout(r, 400 + Math.random() * 600));
    }
  })().catch(() => {});
  return () => { stopped = true; };
}

/**
 * Inject the full anti-detection script into every frame (incl. iframes).
 * Playwright's addInitScript applies to all frames in the context, including
 * cross-origin iframes (e.g. Turnstile widget).
 */
async function injectStealth(context, profile) {
  const script = buildStealthInitScript(profile);
  await context.addInitScript({ content: script });
}

/**
 * Mark the consumer's profile as warmed. With no argument, writes the legacy
 * single-profile marker (preserves old behavior for existing routes).
 */
function markProfileWarmed(consumerId) {
  const { warmupFile } = _pathsForConsumer(_consumerSlug(consumerId));
  try {
    fs.mkdirSync(path.dirname(warmupFile), { recursive: true });
    fs.writeFileSync(warmupFile, JSON.stringify({ warmedAt: Date.now() }));
  } catch { /* non-fatal */ }
}

/** Has the consumer's profile been warmed within ttlHours? */
function profileIsWarm(ttlHoursOrConsumerId, maybeTtlHours) {
  // Backward-compat: old signature was profileIsWarm(ttlHours).
  // New signature: profileIsWarm(consumerId, ttlHours).
  let consumerId = null;
  let ttlHours = 24;
  if (typeof ttlHoursOrConsumerId === 'number' && maybeTtlHours === undefined) {
    ttlHours = ttlHoursOrConsumerId;
  } else {
    consumerId = ttlHoursOrConsumerId;
    if (typeof maybeTtlHours === 'number') ttlHours = maybeTtlHours;
  }
  const { warmupFile } = _pathsForConsumer(_consumerSlug(consumerId));
  try {
    const raw = fs.readFileSync(warmupFile, 'utf8');
    const data = JSON.parse(raw);
    return data.warmedAt && Date.now() - data.warmedAt < ttlHours * 60 * 60 * 1000;
  } catch { return false; }
}

/**
 * Launch a persistent-context stealth Chromium.
 *
 * @param {Object} [_options]
 * @param {boolean} [_options.skipStealth] - Diagnostic override: skip init script.
 * @param {number|string} [_options.consumerId] - Panel consumer id. When set,
 *   uses per-consumer isolated profile dir + proxy session + warmup marker,
 *   and overrides fingerprint via the consumer's fingerprint_profile_id.
 * @param {number} [_options.fingerprintProfileId] - Direct fingerprint index
 *   from fingerprint.PROFILES. Used by panel consumers so their visual
 *   machine identity is fixed across the life of the panel.
 * @param {string} [_options.proxyZip] - Override the residential proxy zip
 *   hint. Defaults to 06880 (Westport CT); panel consumers pass their own
 *   home_zip so their residential IP reflects where they actually live.
 */
async function launchBrowser(_options = {}) {
  const slug = _consumerSlug(_options.consumerId);
  const paths = _pathsForConsumer(slug);
  const USER_DATA_DIR = paths.userDataDir;
  const SESSION_FILE = paths.sessionFile;

  try { fs.mkdirSync(USER_DATA_DIR, { recursive: true }); } catch { /* exists */ }

  // Clear stale SingletonLock from a previous crashed Chromium. Persistent
  // profiles leave these behind on SIGKILL / process crash and refuse to
  // launch until removed. Safe as long as no other Chromium is actually
  // using THIS consumer's profile right now (we check pgrep).
  try {
    const { execSync } = require('child_process');
    const running = execSync('pgrep -f "user-data-dir=' + USER_DATA_DIR + '" || true').toString().trim();
    if (!running) {
      for (const name of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
        try { fs.unlinkSync(path.join(USER_DATA_DIR, name)); } catch { /* not present */ }
      }
    }
  } catch { /* non-fatal */ }

  const useHeaded = !!process.env.DISPLAY;
  const sessionId = config.PROXY_HOST && config.PROXY_PASS
    ? getOrCreateProxySession(SESSION_FILE, slug)
    : 'no-proxy';
  // Consumer has a fixed fingerprint_profile_id; otherwise derive from session.
  const profile = _options.fingerprintProfileId != null
    ? pickProfileByIndex(_options.fingerprintProfileId, sessionId)
    : pickProfile(sessionId);
  const proxyZip = String(_options.proxyZip || '06880').replace(/[^0-9]/g, '').slice(0, 5) || '06880';

  const args = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    `--window-size=${profile.screen.width},${profile.screen.height}`,
    '--window-position=0,0',
    `--lang=${profile.locale}`,
    // WebRTC leak block at the browser level — complements JS init script
    '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--force-webrtc-ip-handling-policy',
    '--disable-features=IsolateOrigins,site-per-process',
  ];
  if (!useHeaded) {
    args.push('--disable-gpu', '--disable-software-rasterizer', '--disable-extensions',
      '--disable-background-networking', '--no-first-run', '--mute-audio');
  } else {
    args.push('--start-maximized', '--enable-features=NetworkService,NetworkServiceInProcess');
  }

  let proxyConfig = null;
  if (config.PROXY_HOST && config.PROXY_PASS) {
    const proxyPort = '7000';
    const proxyUser = `user-${config.PROXY_USER}-country-us-zip-${proxyZip}-session-${sessionId}-sessionduration-1440`;
    proxyConfig = {
      server: `http://${config.PROXY_HOST}:${proxyPort}`,
      username: proxyUser,
      password: config.PROXY_PASS,
    };
    console.log(`[browser] Using proxy: ${config.PROXY_HOST}:${proxyPort} stickySession=${sessionId} zip=${proxyZip} consumer=${slug || 'legacy'}`);
  } else {
    console.log('[browser] No proxy configured — using direct connection');
  }

  console.log(`[browser] Headed=${useHeaded} (DISPLAY=${process.env.DISPLAY || 'unset'}) profile=${USER_DATA_DIR}`);
  console.log(`[browser] Fingerprint: ${profile.screen.width}x${profile.screen.height}@${profile.dpr}x cores=${profile.hardwareConcurrency} ram=${profile.deviceMemory}GB gpu="${profile.gpu.unmaskedRenderer}"`);

  const contextOptions = {
    headless: !useHeaded,
    args,
    viewport: { width: profile.screen.width, height: profile.screen.height },
    screen: { width: profile.screen.width, height: profile.screen.height },
    deviceScaleFactor: profile.dpr,
    userAgent: profile.userAgent,
    locale: profile.locale,
    timezoneId: profile.timezone,
    colorScheme: 'light',
    extraHTTPHeaders: {
      'Accept-Language': profile.acceptLanguage,
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
      'sec-ch-ua': profile.secChUa,
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': profile.secChUaPlatform,
      'sec-ch-ua-platform-version': profile.secChUaPlatformVersion,
      'sec-ch-ua-full-version-list': profile.secChUaFullVersionList,
      'Upgrade-Insecure-Requests': '1',
    },
  };
  if (proxyConfig) contextOptions.proxy = proxyConfig;

  // Priority: patchright → playwright-extra → plain playwright.
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

  if (!_options.skipStealth) {
    await injectStealth(context, profile);
  }

  const pages = context.pages();
  const page = pages.length > 0 ? pages[0] : await context.newPage();

  return { browser: context, page, launchMethod, profile, sessionId, consumerSlug: slug };
}

/** Safely close a browser/context instance. */
async function closeBrowser(browser) {
  try {
    if (browser) await browser.close();
  } catch { /* ignore close errors */ }
}

/** Simulate human-like initial browsing behavior. */
async function simulateHumanBehavior(page) {
  try {
    for (let i = 0; i < 3; i++) {
      const x = 200 + Math.floor(Math.random() * 800);
      const y = 200 + Math.floor(Math.random() * 400);
      await bezierMouseMove(page, x, y, { steps: 12 + Math.floor(Math.random() * 10) });
      await new Promise(r => setTimeout(r, Math.floor(Math.random() * 500) + 200));
    }
    await page.mouse.wheel(0, Math.floor(Math.random() * 200) + 50);
    await new Promise(r => setTimeout(r, Math.floor(Math.random() * 1000) + 500));
  } catch { /* non-critical */ }
}

/**
 * Simulate a brief tab blur/focus (alt-tab). Real users leave tabs in
 * background sometimes — totally-focused lifetime is itself a signal.
 */
async function simulateBlurFocus(page) {
  try {
    await page.evaluate(() => {
      window.dispatchEvent(new Event('blur'));
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await new Promise((r) => setTimeout(r, 2000 + Math.random() * 3000));
    await page.evaluate(() => {
      window.dispatchEvent(new Event('focus'));
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
  } catch { /* non-critical */ }
}

module.exports = {
  launchBrowser,
  humanDelay,
  microDelay,
  humanType,
  randomMouseMove,
  bezierMouseMove,
  closeBrowser,
  simulateHumanBehavior,
  simulateBlurFocus,
  startMouseDrift,
  markProfileWarmed,
  profileIsWarm,
  USER_DATA_DIR: LEGACY_USER_DATA_DIR,
  CHROME_PROFILES_DIR,
  PROXY_SESSIONS_DIR,
};
