const express = require('express');
const fs = require('fs');
const path = require('path');
const config = require('./lib/config');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: false }));

// --- Startup self-test state ---
const selfTest = {
  proxyResult: null,
  proxyTestedAt: null,
  startedAt: new Date().toISOString(),
  lastCarvanaRun: null,
};

/**
 * Run a proxy connectivity test in the background.
 * Stores result in selfTest for the /api/status endpoint.
 */
async function runProxyTest() {
  try { config.reloadConfig(); } catch (_) {}
  if (!config.PROXY_HOST || !config.PROXY_PASS) {
    selfTest.proxyResult = { ok: false, error: 'Proxy not configured (no password)' };
    selfTest.proxyTestedAt = new Date().toISOString();
    return;
  }

  const proxyPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');
  const sessionId = Math.random().toString(36).substring(7);
  const proxyUser = config.PROXY_USER ? `${config.PROXY_USER}-session-${sessionId}` : '';

  let browser = null;
  try {
    const pw = require('playwright');
    browser = await pw.chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--no-zygote', '--single-process', '--disable-gpu', '--disable-dev-shm-usage'],
      proxy: {
        server: `http://${config.PROXY_HOST}:${proxyPort}`,
        username: proxyUser,
        password: config.PROXY_PASS,
      },
    });

    const page = await browser.newPage();
    await page.goto('https://ip.decodo.com/json', { timeout: 30000 });
    const body = await page.textContent('body');
    await browser.close();
    browser = null;

    try {
      const ipData = JSON.parse(body);
      selfTest.proxyResult = { ok: true, ip: ipData.ip, country: ipData.country_code, port: proxyPort };
    } catch {
      selfTest.proxyResult = { ok: true, ip: body.trim().substring(0, 100), port: proxyPort };
    }
  } catch (err) {
    if (browser) try { await browser.close(); } catch (_) {}
    selfTest.proxyResult = { ok: false, error: err.message, port: proxyPort };
  }
  selfTest.proxyTestedAt = new Date().toISOString();
  console.log(`[self-test] Proxy test result:`, JSON.stringify(selfTest.proxyResult));
}

/**
 * Run network-level diagnostics (TCP, DNS, HTTP CONNECT) and store in selfTest.
 */
async function runNetworkDiag() {
  try { config.reloadConfig(); } catch (_) {}
  const net = require('net');
  const dns = require('dns');
  const proxyPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');
  const host = config.PROXY_HOST || 'gate.decodo.com';
  const diag = {};

  // DNS
  diag.dns = await new Promise((resolve) => {
    dns.resolve4(host, (err, addresses) => {
      if (err) return resolve({ ok: false, error: err.message });
      resolve({ ok: true, addresses });
    });
  });

  // TCP to proxy
  diag.tcp_proxy = await new Promise((resolve) => {
    const sock = net.createConnection({ host, port: parseInt(proxyPort), timeout: 10000 }, () => {
      sock.destroy();
      resolve({ ok: true, host, port: proxyPort });
    });
    sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, error: err.message }); });
    sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'timeout' }); });
  });

  // HTTP CONNECT with auth
  if (diag.tcp_proxy.ok && config.PROXY_PASS) {
    diag.http_connect = await new Promise((resolve) => {
      const sock = net.createConnection({ host, port: parseInt(proxyPort), timeout: 15000 }, () => {
        const sessionId = Math.random().toString(36).substring(7);
        const proxyUser = config.PROXY_USER ? `${config.PROXY_USER}-session-${sessionId}` : config.PROXY_USER;
        const auth = Buffer.from(`${proxyUser}:${config.PROXY_PASS}`).toString('base64');
        sock.write(`CONNECT ip.decodo.com:443 HTTP/1.1\r\nHost: ip.decodo.com:443\r\nProxy-Authorization: Basic ${auth}\r\n\r\n`);
        let data = '';
        sock.on('data', (chunk) => {
          data += chunk.toString();
          if (data.includes('\r\n\r\n')) {
            sock.destroy();
            const statusLine = data.split('\r\n')[0];
            resolve({ ok: statusLine.includes('200'), response: statusLine });
          }
        });
        sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'HTTP CONNECT timeout' }); });
      });
      sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, error: err.message }); });
      sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'TCP timeout' }); });
    });

    // Also try without session suffix (plain username)
    if (!diag.http_connect.ok) {
      diag.http_connect_plain = await new Promise((resolve) => {
        const sock = net.createConnection({ host, port: parseInt(proxyPort), timeout: 15000 }, () => {
          const auth = Buffer.from(`${config.PROXY_USER}:${config.PROXY_PASS}`).toString('base64');
          sock.write(`CONNECT ip.decodo.com:443 HTTP/1.1\r\nHost: ip.decodo.com:443\r\nProxy-Authorization: Basic ${auth}\r\n\r\n`);
          let data = '';
          sock.on('data', (chunk) => {
            data += chunk.toString();
            if (data.includes('\r\n\r\n')) {
              sock.destroy();
              const statusLine = data.split('\r\n')[0];
              resolve({ ok: statusLine.includes('200'), response: statusLine });
            }
          });
          sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'timeout' }); });
        });
        sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, error: err.message }); });
        sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'timeout' }); });
      });
    }
  }

  selfTest.networkDiag = diag;
  selfTest.networkDiagAt = new Date().toISOString();
  console.log('[startup] Network diag:', JSON.stringify(diag));
}

/**
 * Try alternative proxy ports (10001-10007) if the default fails.
 */
async function tryAlternativeProxyConfigs() {
  const ports = ['10001', '10002', '10003', '10004', '10005'];
  const currentPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');

  for (const port of ports) {
    if (port === currentPort && selfTest.proxyResult && !selfTest.proxyResult.ok) continue; // skip already-failed port

    console.log(`[startup] Trying proxy on port ${port}...`);
    let browser = null;
    try {
      const pw = require('playwright');
      browser = await pw.chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--no-zygote', '--single-process', '--disable-gpu', '--disable-dev-shm-usage'],
        proxy: {
          server: `http://${config.PROXY_HOST}:${port}`,
          username: config.PROXY_USER,
          password: config.PROXY_PASS,
        },
      });
      const page = await browser.newPage();
      await page.goto('https://ip.decodo.com/json', { timeout: 20000 });
      const body = await page.textContent('body');
      await browser.close();
      browser = null;

      const ipData = JSON.parse(body);
      selfTest.proxyResult = { ok: true, ip: ipData.ip, country: ipData.country_code, port, note: `worked on port ${port} (no session suffix)` };
      selfTest.proxyTestedAt = new Date().toISOString();
      selfTest.workingPort = port;
      console.log(`[startup] Proxy WORKS on port ${port}! IP: ${ipData.ip}`);
      return; // Found a working config
    } catch (err) {
      if (browser) try { await browser.close(); } catch (_) {}
      console.log(`[startup] Port ${port} failed: ${err.message}`);
    }
  }

  console.log('[startup] All proxy ports failed.');
}

// --- Setup page: configure .env from the browser ---
app.get('/setup', (_req, res) => {
  // Reload config from disk in case .env was written after server started
  try { config.reloadConfig(); } catch (_) {}
  const msg = _req.query.msg || '';
  res.send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Setup — Car Offer Tool</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 16px;
    }
    h1 {
      font-size: 1.5rem;
      text-align: center;
      margin: 12px 0 8px;
      color: #38bdf8;
    }
    .subtitle {
      text-align: center;
      color: #94a3b8;
      font-size: 0.85rem;
      margin-bottom: 20px;
    }
    .card {
      background: #1e293b;
      border-radius: 12px;
      padding: 20px;
      max-width: 480px;
      margin: 0 auto;
    }
    label {
      display: block;
      font-size: 0.85rem;
      color: #94a3b8;
      margin-bottom: 4px;
      margin-top: 16px;
    }
    label:first-of-type { margin-top: 0; }
    input {
      width: 100%;
      padding: 12px;
      border: 1px solid #334155;
      border-radius: 8px;
      background: #0f172a;
      color: #f1f5f9;
      font-size: 1rem;
      outline: none;
    }
    input:focus { border-color: #38bdf8; }
    button {
      width: 100%;
      margin-top: 20px;
      padding: 14px;
      border: none;
      border-radius: 8px;
      background: #0ea5e9;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover { background: #0284c7; }
    .alert {
      max-width: 480px;
      margin: 0 auto 16px;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 0.9rem;
      text-align: center;
    }
    .alert-warn { background: #422006; color: #fbbf24; }
    .alert-ok   { background: #052e16; color: #4ade80; }
  </style>
</head>
<body>
  <h1>Server Setup</h1>
  <p class="subtitle">Configure proxy &amp; email for Carvana lookups</p>
  ${msg === 'saved' ? '<div class="alert alert-ok">Configuration saved! <a href="/car-offers/" style="color:#4ade80;font-weight:600;">Go to Car Offer Tool &rarr;</a></div>' : ''}
  ${msg === 'required' ? '<div class="alert alert-warn">Please configure your proxy password first.</div>' : ''}
  <form class="card" method="POST" action="/car-offers/api/setup">
    <label for="proxyHost">Proxy Host</label>
    <input type="text" id="proxyHost" name="proxyHost" placeholder="proxy.example.com" value="${escapeAttr(config.PROXY_HOST || 'gate.decodo.com')}">

    <label for="proxyPort">Proxy Port</label>
    <input type="text" id="proxyPort" name="proxyPort" placeholder="12345" inputmode="numeric" value="${escapeAttr(config.PROXY_PORT || '10001')}">

    <label for="proxyUser">Proxy Username</label>
    <input type="text" id="proxyUser" name="proxyUser" placeholder="username" value="${escapeAttr(config.PROXY_USER || 'spjax0kgms')}">

    <label for="proxyPass">Proxy Password</label>
    <input type="password" id="proxyPass" name="proxyPass" placeholder="${config.PROXY_PASS ? '••••••••' : 'password'}" value="">

    <label for="projectEmail">Project Email</label>
    <input type="email" id="projectEmail" name="projectEmail" placeholder="you@example.com (optional)" value="${escapeAttr(config.PROJECT_EMAIL)}">

    <button type="submit">Save Configuration</button>
  </form>

  <div class="card" style="margin-top:20px;">
    <button id="testBtn" type="button" onclick="testProxy()" style="background:#059669;">Test Proxy Connection</button>
    <div id="testResult" style="margin-top:12px;font-size:0.9rem;text-align:center;"></div>
  </div>

  <script>
    async function testProxy() {
      const btn = document.getElementById('testBtn');
      const result = document.getElementById('testResult');
      btn.disabled = true;
      btn.textContent = 'Testing...';
      result.innerHTML = '<span style="color:#94a3b8;">Launching browser through proxy... (10-20s)</span>';
      try {
        const resp = await fetch('/car-offers/api/test-proxy');
        const data = await resp.json();
        if (data.ok) {
          result.innerHTML = '<span style="color:#4ade80;">Proxy working! IP: ' + (data.ip || 'unknown') + ' (' + (data.country || '?') + ')</span>';
        } else {
          result.innerHTML = '<span style="color:#f87171;">Proxy failed: ' + (data.error || 'unknown error') + '</span>';
        }
      } catch (e) {
        result.innerHTML = '<span style="color:#f87171;">Request failed: ' + e.message + '</span>';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Test Proxy Connection';
      }
    }
  </script>
</body>
</html>`);
});

app.post('/api/setup', (req, res) => {
  const sanitize = (v) => String(v || '').replace(/[\r\n]/g, '').trim();

  const proxyHost = sanitize(req.body.proxyHost);
  const proxyPort = sanitize(req.body.proxyPort);
  const proxyUser = sanitize(req.body.proxyUser);
  // If password field is blank, keep the existing value
  const proxyPass = req.body.proxyPass ? sanitize(req.body.proxyPass) : config.PROXY_PASS;
  const projectEmail = sanitize(req.body.projectEmail);

  const envContent = [
    `PROXY_HOST=${proxyHost}`,
    `PROXY_PORT=${proxyPort}`,
    `PROXY_USER=${proxyUser}`,
    `PROXY_PASS=${proxyPass}`,
    `PROJECT_EMAIL=${projectEmail}`,
    `PORT=${config.PORT}`,
  ].join('\n') + '\n';

  const envPath = path.join(__dirname, '.env');
  fs.writeFileSync(envPath, envContent, 'utf8');
  config.reloadConfig();

  // If the request is JSON (API call), return JSON; otherwise redirect
  if (req.headers['content-type'] === 'application/json') {
    return res.json({ ok: true, message: 'Configuration saved.' });
  }
  res.redirect('/car-offers/setup?msg=saved');
});

/** Escape a string for use inside an HTML attribute value (double-quoted). */
function escapeAttr(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// --- Serve the HTML UI at GET / ---
app.get('/', (_req, res) => {
  // Redirect to setup if not configured
  if (!config.isConfigured()) {
    return res.redirect('/car-offers/setup?msg=required');
  }

  res.send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Car Offer Tool</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 16px;
    }
    h1 {
      font-size: 1.5rem;
      text-align: center;
      margin: 12px 0 24px;
      color: #38bdf8;
    }
    .card {
      background: #1e293b;
      border-radius: 12px;
      padding: 20px;
      max-width: 480px;
      margin: 0 auto;
    }
    label {
      display: block;
      font-size: 0.85rem;
      color: #94a3b8;
      margin-bottom: 4px;
      margin-top: 16px;
    }
    label:first-of-type { margin-top: 0; }
    input {
      width: 100%;
      padding: 12px;
      border: 1px solid #334155;
      border-radius: 8px;
      background: #0f172a;
      color: #f1f5f9;
      font-size: 1rem;
      outline: none;
    }
    input:focus { border-color: #38bdf8; }
    button {
      width: 100%;
      margin-top: 20px;
      padding: 14px;
      border: none;
      border-radius: 8px;
      background: #0ea5e9;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover { background: #0284c7; }
    button:disabled {
      background: #334155;
      cursor: not-allowed;
    }
    .result {
      margin-top: 20px;
      max-width: 480px;
      margin-left: auto;
      margin-right: auto;
    }
    .result-card {
      background: #1e293b;
      border-radius: 12px;
      padding: 20px;
      margin-top: 12px;
    }
    .offer-amount {
      font-size: 2rem;
      font-weight: 700;
      color: #4ade80;
      text-align: center;
      margin: 8px 0;
    }
    .error-msg {
      color: #f87171;
      text-align: center;
      padding: 12px;
    }
    .spinner {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 24px;
    }
    .spinner-ring {
      width: 40px;
      height: 40px;
      border: 4px solid #334155;
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .spinner-text {
      margin-top: 12px;
      color: #94a3b8;
      font-size: 0.9rem;
    }
    .detail-row {
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      font-size: 0.9rem;
      border-bottom: 1px solid #334155;
    }
    .detail-row:last-child { border-bottom: none; }
    .detail-label { color: #94a3b8; }
    .detail-value { color: #f1f5f9; font-weight: 500; }
  </style>
</head>
<body>
  <h1>Car Offer Tool</h1>
  <div class="card">
    <label for="vin">VIN</label>
    <input type="text" id="vin" placeholder="e.g. 1HGBH41JXMN109186" maxlength="17" autocapitalize="characters">

    <label for="mileage">Mileage</label>
    <input type="number" id="mileage" placeholder="e.g. 45000" inputmode="numeric">

    <label for="zip">Zip Code</label>
    <input type="text" id="zip" placeholder="e.g. 06880" maxlength="5" value="06880" inputmode="numeric">

    <button id="btn" onclick="getOffer()">Get Carvana Offer</button>
  </div>

  <div class="result" id="result"></div>

  <script>
    async function getOffer() {
      const vin = document.getElementById('vin').value.trim();
      const mileage = document.getElementById('mileage').value.trim();
      const zip = document.getElementById('zip').value.trim();
      const btn = document.getElementById('btn');
      const resultDiv = document.getElementById('result');

      if (!vin || !mileage || !zip) {
        resultDiv.innerHTML = '<div class="result-card"><p class="error-msg">Please fill in all fields.</p></div>';
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Working...';
      resultDiv.innerHTML = '<div class="result-card"><div class="spinner"><div class="spinner-ring"></div><div class="spinner-text">Getting offer from Carvana...<br>This can take up to 2 minutes.</div></div></div>';

      try {
        const resp = await fetch('/car-offers/api/carvana', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vin, mileage, zip }),
        });
        const data = await resp.json();

        if (data.error) {
          resultDiv.innerHTML = '<div class="result-card"><p class="error-msg">Error: ' + escapeHtml(data.error) + '</p></div>';
        } else {
          let html = '<div class="result-card">';
          html += '<div class="offer-amount">' + escapeHtml(data.offer) + '</div>';
          if (data.details) {
            html += '<div style="margin-top:12px">';
            const d = data.details;
            if (d.year) html += detailRow('Vehicle', d.year + ' ' + (d.make || '') + ' ' + (d.model || ''));
            html += detailRow('VIN', d.vin || vin);
            html += detailRow('Mileage', Number(d.mileage || mileage).toLocaleString());
            html += detailRow('Zip', d.zip || zip);
            html += detailRow('Source', d.source || 'carvana');
            html += detailRow('Time', new Date(d.timestamp || Date.now()).toLocaleString());
            html += '</div>';
          }
          html += '</div>';
          resultDiv.innerHTML = html;
        }
      } catch (err) {
        resultDiv.innerHTML = '<div class="result-card"><p class="error-msg">Request failed: ' + escapeHtml(err.message) + '</p></div>';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Get Carvana Offer';
      }
    }

    function escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    function detailRow(label, value) {
      return '<div class="detail-row"><span class="detail-label">' + escapeHtml(label) + '</span><span class="detail-value">' + escapeHtml(String(value)) + '</span></div>';
    }
  </script>
</body>
</html>`);
});

// --- Debug endpoint (returns server state for QA) ---
app.get('/api/debug', (_req, res) => {
  try { config.reloadConfig(); } catch (_) {}
  const info = {
    timestamp: new Date().toISOString(),
    proxy_host: config.PROXY_HOST,
    proxy_port: config.PROXY_PORT,
    proxy_user: config.PROXY_USER,
    proxy_pass_set: !!config.PROXY_PASS,
    proxy_pass_length: (config.PROXY_PASS || '').length,
    project_email: config.PROJECT_EMAIL || '(not set)',
    node_version: process.version,
    uptime_seconds: Math.floor(process.uptime()),
  };
  res.json(info);
});

// --- Proxy test endpoint (uses regular playwright, not stealth — more stable) ---
app.get('/api/test-proxy', async (_req, res) => {
  try { config.reloadConfig(); } catch (_) {}

  if (!config.PROXY_HOST || !config.PROXY_PASS) {
    return res.json({ ok: false, error: 'Proxy not configured. Save your password first.' });
  }

  const proxyPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');
  const sessionId = Math.random().toString(36).substring(7);
  const proxyUser = config.PROXY_USER ? `${config.PROXY_USER}-session-${sessionId}` : '';

  const proxyInfo = {
    host: config.PROXY_HOST,
    port: proxyPort,
    user: proxyUser,
    pass_length: (config.PROXY_PASS || '').length,
  };

  let browser = null;
  try {
    const pw = require('playwright');
    browser = await pw.chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--no-zygote', '--single-process', '--disable-gpu', '--disable-dev-shm-usage'],
      proxy: {
        server: `http://${config.PROXY_HOST}:${proxyPort}`,
        username: proxyUser,
        password: config.PROXY_PASS,
      },
    });

    const page = await browser.newPage();
    await page.goto('https://ip.decodo.com/json', { timeout: 30000 });
    const body = await page.textContent('body');
    await browser.close();
    browser = null;

    try {
      const ipData = JSON.parse(body);
      return res.json({ ok: true, ip: ipData.ip, country: ipData.country_code, proxy: proxyInfo });
    } catch {
      return res.json({ ok: true, ip: body.trim().substring(0, 100), proxy: proxyInfo });
    }
  } catch (err) {
    if (browser) try { await browser.close(); } catch (_) {}
    console.error('[test-proxy] Error:', err.message);
    return res.json({ ok: false, error: err.message, proxy: proxyInfo });
  }
});

// --- Dashboard: auto-refreshing status page with one-tap actions ---
app.get('/dashboard', (_req, res) => {
  res.send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Car Offers — Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 16px; }
    h1 { font-size: 1.4rem; text-align: center; margin: 8px 0 16px; color: #38bdf8; }
    .card { background: #1e293b; border-radius: 12px; padding: 16px; max-width: 480px; margin: 0 auto 12px; }
    .card h2 { font-size: 1rem; color: #94a3b8; margin-bottom: 8px; }
    .row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; border-bottom: 1px solid #334155; }
    .row:last-child { border-bottom: none; }
    .label { color: #94a3b8; }
    .val { color: #f1f5f9; font-weight: 500; }
    .ok { color: #4ade80; }
    .fail { color: #f87171; }
    .pending { color: #fbbf24; }
    button { width: 100%; margin-top: 12px; padding: 14px; border: none; border-radius: 8px; color: #fff; font-size: 1rem; font-weight: 600; cursor: pointer; }
    .btn-blue { background: #0ea5e9; }
    .btn-green { background: #059669; }
    .btn-orange { background: #d97706; }
    button:disabled { background: #334155; cursor: not-allowed; }
    #log { margin-top: 8px; font-size: 0.8rem; color: #94a3b8; text-align: center; min-height: 20px; }
    .offer-big { font-size: 2rem; font-weight: 700; color: #4ade80; text-align: center; margin: 8px 0; }
    .error-big { font-size: 1rem; color: #f87171; text-align: center; margin: 8px 0; word-break: break-word; }
  </style>
</head>
<body>
  <h1>Car Offers Dashboard</h1>

  <div class="card" id="proxyCard">
    <h2>Proxy Status</h2>
    <div id="proxyInfo"><span class="pending">Loading...</span></div>
    <button class="btn-green" id="retestBtn" onclick="retestProxy()">Retest Proxy</button>
  </div>

  <div class="card">
    <h2>Run Carvana Offer (Test VIN)</h2>
    <div class="row"><span class="label">VIN</span><span class="val">1HGCV2F9XNA008352</span></div>
    <div class="row"><span class="label">Vehicle</span><span class="val">2022 Honda Accord Touring</span></div>
    <div class="row"><span class="label">Mileage</span><span class="val">48,000</span></div>
    <div class="row"><span class="label">Zip</span><span class="val">06880</span></div>
    <button class="btn-blue" id="runBtn" onclick="runCarvana()">Get Carvana Offer</button>
    <div id="log"></div>
  </div>

  <div class="card" id="resultCard" style="display:none;">
    <h2>Last Carvana Result</h2>
    <div id="resultContent"></div>
  </div>

  <div class="card">
    <a href="/car-offers/setup" style="color:#38bdf8;text-decoration:none;font-size:0.9rem;">Setup Page &rarr;</a>
  </div>

  <script>
    async function loadStatus() {
      try {
        const resp = await fetch('/car-offers/api/status');
        const data = await resp.json();
        renderProxy(data.proxy);
        if (data.lastCarvanaRun) renderResult(data.lastCarvanaRun);
      } catch (e) {
        document.getElementById('proxyInfo').innerHTML = '<span class="fail">Failed to load: ' + e.message + '</span>';
      }
    }

    function renderProxy(p) {
      if (!p) return;
      let html = '';
      html += row('Host', p.host || '(not set)');
      html += row('Port', p.port || '(not set)');
      html += row('Password', p.pass_set ? '<span class="ok">Set (' + p.pass_length + ' chars)</span>' : '<span class="fail">NOT SET</span>');
      if (p.test_result) {
        if (p.test_result.ok) {
          html += row('Test', '<span class="ok">PASS — IP: ' + (p.test_result.ip || '?') + ' (' + (p.test_result.country || '?') + ')</span>');
        } else {
          html += row('Test', '<span class="fail">FAIL — ' + esc(p.test_result.error || 'unknown') + '</span>');
        }
        html += row('Tested', p.tested_at ? new Date(p.tested_at).toLocaleString() : 'never');
      } else {
        html += row('Test', '<span class="pending">Not tested yet</span>');
      }
      document.getElementById('proxyInfo').innerHTML = html;
    }

    function renderResult(r) {
      const card = document.getElementById('resultCard');
      const content = document.getElementById('resultContent');
      card.style.display = 'block';
      if (r.offer) {
        content.innerHTML = '<div class="offer-big">' + esc(r.offer) + '</div>' +
          row('VIN', r.vin || '') + row('Completed', r.completed_at ? new Date(r.completed_at).toLocaleString() : '');
      } else if (r.error) {
        content.innerHTML = '<div class="error-big">' + esc(r.error) + '</div>' +
          row('VIN', r.vin || '') + row('Completed', r.completed_at ? new Date(r.completed_at).toLocaleString() : '');
      }
    }

    function row(label, value) {
      return '<div class="row"><span class="label">' + esc(label) + '</span><span class="val">' + value + '</span></div>';
    }

    function esc(s) {
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }

    async function retestProxy() {
      const btn = document.getElementById('retestBtn');
      btn.disabled = true; btn.textContent = 'Testing...';
      try {
        await fetch('/car-offers/api/retest-proxy');
        // Poll status every 5s for up to 30s
        for (let i = 0; i < 6; i++) {
          await new Promise(r => setTimeout(r, 5000));
          await loadStatus();
        }
      } catch (e) {
        document.getElementById('proxyInfo').innerHTML += '<br><span class="fail">' + e.message + '</span>';
      }
      btn.disabled = false; btn.textContent = 'Retest Proxy';
    }

    async function runCarvana() {
      const btn = document.getElementById('runBtn');
      const log = document.getElementById('log');
      btn.disabled = true; btn.textContent = 'Running...';
      log.innerHTML = '<span class="pending">Launching browser, navigating Carvana... (1-3 min)</span>';
      try {
        const resp = await fetch('/car-offers/api/auto-run');
        const data = await resp.json();
        if (!data.ok) {
          log.innerHTML = '<span class="fail">' + esc(data.error) + '</span>';
          btn.disabled = false; btn.textContent = 'Get Carvana Offer';
          return;
        }
        log.innerHTML = '<span class="pending">Request sent. Polling for results...</span>';
        // Poll status every 10s for up to 4 min
        for (let i = 0; i < 24; i++) {
          await new Promise(r => setTimeout(r, 10000));
          const st = await (await fetch('/car-offers/api/status')).json();
          if (st.lastCarvanaRun && st.lastCarvanaRun.completed_at) {
            renderResult(st.lastCarvanaRun);
            log.innerHTML = '<span class="ok">Done!</span>';
            break;
          }
          log.innerHTML = '<span class="pending">Still running... (' + ((i + 1) * 10) + 's)</span>';
        }
      } catch (e) {
        log.innerHTML = '<span class="fail">Error: ' + esc(e.message) + '</span>';
      }
      btn.disabled = false; btn.textContent = 'Get Carvana Offer';
    }

    // Load on page open + refresh every 30s
    loadStatus();
    setInterval(loadStatus, 30000);
  </script>
</body>
</html>`);
});

// --- Status endpoint (shows proxy test + last run results) ---
app.get('/api/status', (_req, res) => {
  try { config.reloadConfig(); } catch (_) {}
  res.json({
    service: {
      startedAt: selfTest.startedAt,
      uptime_seconds: Math.floor(process.uptime()),
      node_version: process.version,
    },
    proxy: {
      configured: !!(config.PROXY_HOST && config.PROXY_PASS),
      host: config.PROXY_HOST,
      port: config.PROXY_PORT,
      user: config.PROXY_USER,
      pass_set: !!config.PROXY_PASS,
      pass_length: (config.PROXY_PASS || '').length,
      test_result: selfTest.proxyResult,
      tested_at: selfTest.proxyTestedAt,
    },
    networkDiag: selfTest.networkDiag || null,
    networkDiagAt: selfTest.networkDiagAt || null,
    workingPort: selfTest.workingPort || null,
    lastCarvanaRun: selfTest.lastCarvanaRun,
  });
});

// --- Auto-run: trigger the test VIN Carvana offer automatically ---
// GET /api/auto-run — runs the test VIN (2022 Honda Accord) through Carvana
// This lets us trigger a test without any manual form filling
app.get('/api/auto-run', async (_req, res) => {
  const testVin = _req.query.vin || '1HGCV2F9XNA008352';
  const testMileage = _req.query.mileage || '48000';
  const testZip = _req.query.zip || '06880';

  // Don't run if proxy isn't configured
  try { config.reloadConfig(); } catch (_) {}
  if (!config.PROXY_HOST || !config.PROXY_PASS) {
    return res.json({
      ok: false,
      error: 'Proxy not configured. Go to /car-offers/setup and enter the proxy password first.',
    });
  }

  let getCarvanaOffer;
  try {
    ({ getCarvanaOffer } = require('./lib/carvana'));
  } catch (loadErr) {
    return res.json({ ok: false, error: `Carvana module not available: ${loadErr.message}` });
  }

  console.log(`[auto-run] Starting Carvana offer for VIN=${testVin} mileage=${testMileage} zip=${testZip}`);
  res.json({
    ok: true,
    message: `Running Carvana offer for VIN ${testVin}. Check /car-offers/api/status for results (takes 1-3 min).`,
    started_at: new Date().toISOString(),
  });

  // Run in background (don't block the HTTP response)
  try {
    const result = await getCarvanaOffer({
      vin: testVin,
      mileage: testMileage,
      zip: testZip,
      email: config.PROJECT_EMAIL || 'caroffers.tool@gmail.com',
    });
    selfTest.lastCarvanaRun = {
      ...result,
      vin: testVin,
      mileage: testMileage,
      zip: testZip,
      completed_at: new Date().toISOString(),
    };
    console.log(`[auto-run] Carvana result:`, JSON.stringify(selfTest.lastCarvanaRun));
  } catch (err) {
    selfTest.lastCarvanaRun = {
      error: err.message,
      vin: testVin,
      completed_at: new Date().toISOString(),
    };
    console.error(`[auto-run] Carvana error:`, err.message);
  }
});

// --- Raw TCP connectivity test to proxy server ---
app.get('/api/diag-network', async (_req, res) => {
  try { config.reloadConfig(); } catch (_) {}
  const net = require('net');
  const proxyPort = (config.PROXY_PORT === '7000') ? '10001' : (config.PROXY_PORT || '10001');
  const host = config.PROXY_HOST || 'gate.decodo.com';
  const results = {};

  // Test 1: TCP connect to proxy
  results.tcp_proxy = await new Promise((resolve) => {
    const sock = net.createConnection({ host, port: parseInt(proxyPort), timeout: 10000 }, () => {
      sock.destroy();
      resolve({ ok: true, host, port: proxyPort });
    });
    sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, host, port: proxyPort, error: err.message }); });
    sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, host, port: proxyPort, error: 'TCP timeout (10s)' }); });
  });

  // Test 2: TCP connect to ip.decodo.com:443 (direct, no proxy)
  results.tcp_decodo_direct = await new Promise((resolve) => {
    const sock = net.createConnection({ host: 'ip.decodo.com', port: 443, timeout: 10000 }, () => {
      sock.destroy();
      resolve({ ok: true });
    });
    sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, error: err.message }); });
    sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'TCP timeout (10s)' }); });
  });

  // Test 3: DNS resolve proxy host
  const dns = require('dns');
  results.dns_proxy = await new Promise((resolve) => {
    dns.resolve4(host, (err, addresses) => {
      if (err) return resolve({ ok: false, error: err.message });
      resolve({ ok: true, addresses });
    });
  });

  // Test 4: Try HTTP CONNECT through proxy (raw)
  results.http_connect = await new Promise((resolve) => {
    const sock = net.createConnection({ host, port: parseInt(proxyPort), timeout: 15000 }, () => {
      const sessionId = Math.random().toString(36).substring(7);
      const proxyUser = config.PROXY_USER ? `${config.PROXY_USER}-session-${sessionId}` : config.PROXY_USER;
      const auth = Buffer.from(`${proxyUser}:${config.PROXY_PASS}`).toString('base64');
      sock.write(`CONNECT ip.decodo.com:443 HTTP/1.1\r\nHost: ip.decodo.com:443\r\nProxy-Authorization: Basic ${auth}\r\n\r\n`);

      let data = '';
      sock.on('data', (chunk) => {
        data += chunk.toString();
        if (data.includes('\r\n\r\n')) {
          sock.destroy();
          const statusLine = data.split('\r\n')[0];
          resolve({ ok: statusLine.includes('200'), response: statusLine });
        }
      });
      sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'HTTP CONNECT timeout (15s)' }); });
    });
    sock.on('error', (err) => { sock.destroy(); resolve({ ok: false, error: err.message }); });
    sock.on('timeout', () => { sock.destroy(); resolve({ ok: false, error: 'TCP timeout (15s)' }); });
  });

  res.json(results);
});

// --- Retest proxy endpoint ---
app.get('/api/retest-proxy', async (_req, res) => {
  res.json({ ok: true, message: 'Proxy retest started. Check /car-offers/api/status in 15-20s.' });
  await runProxyTest();
});

// --- Browser diagnostic: can Chromium launch at all? ---
app.get('/api/diag-browser', async (_req, res) => {
  let browser = null;
  const steps = [];
  try {
    steps.push('Loading playwright...');
    let pw;
    try {
      pw = require('playwright');
    } catch (e) {
      steps.push(`playwright require failed: ${e.message}`);
      return res.json({ ok: false, steps, error: e.message });
    }

    steps.push('Checking chromium executable...');
    const execPath = pw.chromium.executablePath();
    steps.push(`Executable: ${execPath}`);

    const fs = require('fs');
    const exists = fs.existsSync(execPath);
    steps.push(`Exists: ${exists}`);
    if (!exists) {
      return res.json({ ok: false, steps, error: 'Chromium binary not found. Run: npx playwright install chromium' });
    }

    steps.push('Launching headless Chromium (no proxy)...');
    browser = await pw.chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--no-zygote', '--single-process', '--disable-gpu', '--disable-dev-shm-usage'],
    });
    steps.push('Browser launched OK');

    const page = await browser.newPage();
    steps.push('Page created OK');

    await page.goto('data:text/html,<h1>test</h1>', { timeout: 10000 });
    const title = await page.textContent('h1');
    steps.push(`Page loaded: ${title}`);

    await browser.close();
    browser = null;
    steps.push('Browser closed OK');

    return res.json({ ok: true, steps });
  } catch (err) {
    if (browser) try { await browser.close(); } catch (_) {}
    steps.push(`Error: ${err.message}`);
    return res.json({ ok: false, steps, error: err.message });
  }
});

// --- API endpoint ---
app.post('/api/carvana', async (req, res) => {
  const { vin, mileage, zip } = req.body || {};

  if (!vin || !mileage || !zip) {
    return res.status(400).json({ error: 'Missing required fields: vin, mileage, zip' });
  }

  let getCarvanaOffer;
  try {
    ({ getCarvanaOffer } = require('./lib/carvana'));
  } catch (loadErr) {
    console.error('[server] Failed to load carvana module:', loadErr.message);
    return res.status(503).json({ error: 'Carvana module not available yet — dependencies may still be installing. Try again in a minute.' });
  }

  try {
    const result = await getCarvanaOffer({
      vin: String(vin).toUpperCase(),
      mileage: String(mileage),
      zip: String(zip),
      email: config.PROJECT_EMAIL,
    });
    res.json(result);
  } catch (err) {
    console.error('[server] Carvana error:', err);
    res.status(500).json({ error: err.message || 'Internal server error' });
  }
});

// --- Start server ---
const port = config.PORT;
app.listen(port, '0.0.0.0', () => {
  console.log(`Car Offer Tool running on http://0.0.0.0:${port}`);

  // Run full diagnostics 5 seconds after startup
  setTimeout(async () => {
    console.log('[startup] Running full network diagnostics...');
    await runNetworkDiag();
    console.log('[startup] Running proxy self-test...');
    await runProxyTest();

    // If proxy test failed, try alternative configs
    if (selfTest.proxyResult && !selfTest.proxyResult.ok) {
      console.log('[startup] Proxy failed — trying alternative ports...');
      await tryAlternativeProxyConfigs();
    }
  }, 5000);
});
