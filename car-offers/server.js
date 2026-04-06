const express = require('express');
const fs = require('fs');
const path = require('path');
const config = require('./lib/config');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: false }));

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
    <input type="text" id="proxyPort" name="proxyPort" placeholder="12345" inputmode="numeric" value="${escapeAttr(config.PROXY_PORT || '7000')}">

    <label for="proxyUser">Proxy Username</label>
    <input type="text" id="proxyUser" name="proxyUser" placeholder="username" value="${escapeAttr(config.PROXY_USER || 'spjax0kgms')}">

    <label for="proxyPass">Proxy Password</label>
    <input type="password" id="proxyPass" name="proxyPass" placeholder="${config.PROXY_PASS ? '••••••••' : 'password'}" value="">

    <label for="projectEmail">Project Email</label>
    <input type="email" id="projectEmail" name="projectEmail" placeholder="you@example.com (optional)" value="${escapeAttr(config.PROJECT_EMAIL)}">

    <button type="submit">Save Configuration</button>
  </form>
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
});
