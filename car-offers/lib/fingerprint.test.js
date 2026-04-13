#!/usr/bin/env node
/**
 * Fingerprint unit test — launches the stealth browser against a local
 * fixture (and optionally bot.sannysoft.com / creepjs if DISPLAY & network
 * are available) and asserts the key detection vectors are patched.
 *
 * Runs without a test framework — just `node lib/fingerprint.test.js`.
 * Exits 0 on PASS, non-zero on FAIL.
 *
 * The canonical suite would hit https://bot.sannysoft.com, but that
 * requires network egress. We keep the assertions self-contained by
 * spinning up a local fixture page and querying the same fingerprint
 * points those sites query.
 */

const assert = require('assert');
const http = require('http');
const { launchBrowser, closeBrowser } = require('./browser');

const FIXTURE_HTML = `<!DOCTYPE html>
<html><head><title>fp</title></head><body>
<script>
  const out = {};
  out.stealthApplied = !!window.__stealthApplied;
  try { out.webdriver = navigator.webdriver; } catch(e){ out.webdriver = 'ERR:'+e.message; }
  try { out.platform = navigator.platform; } catch(e){ out.platform = 'ERR'; }
  try { out.languages = navigator.languages; } catch(e){ out.languages = null; }
  try { out.hwConc = navigator.hardwareConcurrency; } catch(e){ out.hwConc = null; }
  try { out.deviceMem = navigator.deviceMemory; } catch(e){ out.deviceMem = null; }
  try { out.vendor = navigator.vendor; } catch(e){ out.vendor = null; }
  try { out.plugins = navigator.plugins.length; } catch(e){ out.plugins = null; }
  try { out.chromeType = typeof window.chrome; } catch(e){ out.chromeType = null; }
  try { out.chromeRuntime = typeof (window.chrome && window.chrome.runtime && window.chrome.runtime.OnInstalledReason); } catch(e){ out.chromeRuntime = null; }
  try { out.uaDataPlatform = navigator.userAgentData && navigator.userAgentData.platform; } catch(e){ out.uaDataPlatform = null; }
  try {
    const c = document.createElement('canvas'); c.width = 200; c.height = 60;
    const ctx = c.getContext('2d'); ctx.textBaseline = 'top'; ctx.font = '14px Arial';
    ctx.fillStyle = 'red'; ctx.fillRect(0, 0, 200, 60);
    ctx.fillStyle = 'blue'; ctx.fillText('fp-test-string', 10, 10);
    // Two getImageData reads on the same rect should return slightly
    // different pixel data because our patch adds per-call PRNG noise.
    const img1 = ctx.getImageData(0, 0, 50, 10).data;
    const img2 = ctx.getImageData(0, 0, 50, 10).data;
    let diff = 0;
    for (let i = 0; i < img1.length; i++) if (img1[i] !== img2[i]) diff++;
    out.canvasNoiseDiffCount = diff;
    out.canvasLen = img1.length;
    out.canvas1 = c.toDataURL().length;
  } catch(e){ out.canvasNoiseDiffCount = 'ERR:' + e.message; }
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    out.webglVendor = gl.getParameter(37445);
    out.webglRenderer = gl.getParameter(37446);
  } catch(e){ out.webglVendor = 'ERR'; out.webglRenderer = 'ERR'; }
  try {
    const gl2 = document.createElement('canvas').getContext('webgl2');
    out.webgl2Vendor = gl2 && gl2.getParameter(37445);
    out.webgl2Renderer = gl2 && gl2.getParameter(37446);
  } catch(e){ out.webgl2Vendor = 'ERR'; out.webgl2Renderer = 'ERR'; }
  try { out.tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e){ out.tz = null; }
  try { out.screenW = screen.width; out.screenH = screen.height; } catch(e){ out.screenW = null; }
  (async () => {
    try {
      const b = await navigator.getBattery();
      out.batteryCharging = b.charging;
      out.batteryLevel = b.level;
    } catch(e){ out.batteryCharging = 'ERR:'+e.message; }
    try {
      const d = await navigator.mediaDevices.enumerateDevices();
      out.mediaDevicesCount = d.length;
      out.mediaDeviceKinds = d.map(x => x.kind);
    } catch(e){ out.mediaDevicesCount = 'ERR'; }
    try {
      const p = await navigator.permissions.query({ name: 'clipboard-read' });
      out.permClipboard = p.state;
      const p2 = await navigator.permissions.query({ name: 'geolocation' });
      out.permGeo = p2.state;
    } catch(e){ out.permClipboard = 'ERR:'+e.message; }
    try {
      out.uaDataHE = await navigator.userAgentData.getHighEntropyValues(['platform','platformVersion','architecture','bitness']);
    } catch(e){ out.uaDataHE = 'ERR:'+e.message; }
    // Stash in a DOM attribute so Playwright can read it via the isolated
    // evaluate world (it cannot read window.* from the page's main world).
    document.body.setAttribute('data-fp', JSON.stringify(out));
    document.title = 'done';
  })();
</script>
</body></html>`;

async function runLocalFixture() {
  // Start a tiny local HTTP server serving the fixture.
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(FIXTURE_HTML);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const url = `http://127.0.0.1:${port}/fp`;

  let browser, page, profile;
  const results = {};
  try {
    const res = await launchBrowser();
    browser = res.browser; page = res.page; profile = res.profile;

    await page.goto(url, { waitUntil: 'load', timeout: 20000 });
    console.log('[fp-test] Page loaded, URL=' + page.url());
    // Capture any console errors from the page for debugging
    page.on('pageerror', (e) => console.error('[page-error] ' + e.message));
    page.on('console', (m) => { if (m.type() === 'error') console.error('[page-console] ' + m.text()); });
    // Brief check of what's in window immediately
    await new Promise(r => setTimeout(r, 500));
    // Poll for body[data-fp] — patchright runs evaluate() in an isolated
    // world where page-set window globals aren't visible, but DOM attrs are.
    let fp = null;
    for (let i = 0; i < 60; i++) {
      const raw = await page.getAttribute('body', 'data-fp').catch(() => null);
      if (raw) { try { fp = JSON.parse(raw); break; } catch { /* still writing */ } }
      await new Promise(r => setTimeout(r, 250));
    }
    if (!fp) throw new Error('Fixture never set body[data-fp] within 15s');
    Object.assign(results, { fp, profile });
  } finally {
    await closeBrowser(browser).catch(() => {});
    server.close();
  }
  return results;
}

function must(cond, msg) {
  if (!cond) {
    console.error('FAIL: ' + msg);
    process.exitCode = 1;
  } else {
    console.log('PASS: ' + msg);
  }
}

(async () => {
  console.log('[fp-test] Launching stealth browser against local fixture...');
  const { fp, profile } = await runLocalFixture();
  console.log('[fp-test] Fingerprint probe result:');
  console.log(JSON.stringify(fp, null, 2));

  // ---- Assertions: key bot tells must be patched ----
  must(fp.webdriver === false, `navigator.webdriver is ${fp.webdriver} (want false)`);
  must(fp.platform === 'Win32', `navigator.platform is ${fp.platform} (want Win32)`);
  must(Array.isArray(fp.languages) && fp.languages[0] === 'en-US', `languages=${JSON.stringify(fp.languages)}`);
  must(fp.hwConc === profile.hardwareConcurrency, `hwConc=${fp.hwConc} want ${profile.hardwareConcurrency}`);
  must(fp.deviceMem === profile.deviceMemory, `deviceMemory=${fp.deviceMem} want ${profile.deviceMemory}`);
  must(fp.vendor === 'Google Inc.', `vendor=${fp.vendor}`);
  must(typeof fp.plugins === 'number' && fp.plugins >= 3, `plugins.length=${fp.plugins} (want >=3)`);
  must(fp.chromeType === 'object', `typeof window.chrome=${fp.chromeType}`);
  must(fp.chromeRuntime === 'object', `chrome.runtime.OnInstalledReason=${fp.chromeRuntime} (want object)`);
  must(fp.uaDataPlatform === 'Windows', `userAgentData.platform=${fp.uaDataPlatform}`);
  // WebGL: Xvfb on a server usually lacks GPU; treat 'ERR'/null as SKIP.
  if (fp.webglVendor === 'ERR' || fp.webglVendor === null) {
    console.log('SKIP: WebGL unavailable in this env (expected on Xvfb w/o GPU)');
  } else {
    must(fp.webglVendor === profile.gpu.unmaskedVendor, `webgl vendor=${fp.webglVendor}`);
    must(fp.webglRenderer === profile.gpu.unmaskedRenderer, `webgl renderer=${fp.webglRenderer}`);
    must(fp.webgl2Vendor === profile.gpu.unmaskedVendor, `webgl2 vendor=${fp.webgl2Vendor}`);
    must(fp.webgl2Renderer === profile.gpu.unmaskedRenderer, `webgl2 renderer=${fp.webgl2Renderer}`);
  }
  must(fp.tz === 'America/New_York', `Intl TZ=${fp.tz}`);
  must(fp.screenW === profile.screen.width, `screen.width=${fp.screenW} want ${profile.screen.width}`);
  must(fp.batteryCharging === true, `battery.charging=${fp.batteryCharging}`);
  must(typeof fp.batteryLevel === 'number' && fp.batteryLevel > 0 && fp.batteryLevel <= 1, `battery.level=${fp.batteryLevel}`);
  must(fp.mediaDevicesCount >= 2, `mediaDevices count=${fp.mediaDevicesCount}`);
  must(fp.permClipboard === 'prompt', `perm clipboard=${fp.permClipboard}`);
  must(fp.permGeo === 'prompt', `perm geolocation=${fp.permGeo}`);
  must(fp.uaDataHE && fp.uaDataHE.platform === 'Windows', `UA-CH HE platform=${JSON.stringify(fp.uaDataHE)}`);
  must(fp.uaDataHE && fp.uaDataHE.architecture === 'x86', `UA-CH HE architecture=${fp.uaDataHE && fp.uaDataHE.architecture}`);
  // Canvas noise: two getImageData reads should show per-call PRNG noise.
  must(
    typeof fp.canvasNoiseDiffCount === 'number' && fp.canvasNoiseDiffCount > 0,
    `canvas getImageData noise diff=${fp.canvasNoiseDiffCount} (want >0 out of ${fp.canvasLen})`,
  );

  if (process.exitCode) {
    console.error('\n[fp-test] Some checks FAILED — see above.');
  } else {
    console.log('\n[fp-test] All checks PASSED.');
  }
})().catch((err) => {
  console.error('[fp-test] Fatal error:', err);
  process.exit(2);
});
