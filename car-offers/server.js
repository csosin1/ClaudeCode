const express = require('express');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execSync } = require('child_process');
const config = require('./lib/config');
const { normalizeOfferRequest } = require('./lib/offer-input');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: false }));

// --- Wizard debug captures (screenshots + HTML dumps written by debugDump()) ---
// Served at /debug/<site>/step-NN-<slug>.{png,html}. Behind nginx the public
// URL becomes /car-offers/preview/debug/... which the gallery below links to.
const DEBUG_DUMP_DIR = path.join(__dirname, 'public-debug');
try { fs.mkdirSync(DEBUG_DUMP_DIR, { recursive: true }); } catch { /* ok */ }
app.use('/debug', express.static(DEBUG_DUMP_DIR, {
  // HTML dumps are not trusted content — don't let the browser infer a weird type
  setHeaders(res, filePath) {
    if (filePath.endsWith('.html')) {
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
    }
  },
}));

// --- SQLite offers DB (shared by /api/carvana, /api/carmax, /api/driveway, /api/quote-all) ---
// Lazy-initialized so the server can boot even if better-sqlite3 is briefly
// missing (deploy race); subsequent requests just try again.
let _offersDb = null;
function getOffersDb() {
  if (_offersDb) return _offersDb;
  try {
    const { openDb } = require('./lib/offers-db');
    _offersDb = openDb();
    return _offersDb;
  } catch (e) {
    console.error('[offers-db] Failed to open:', e.message);
    return null;
  }
}

/**
 * Persist one site's result to the offers DB. Never throws — logs on failure.
 * Site handler result shape is normalized before insertion.
 */
function persistOffer({ site, runId, normalized, result, startedAt, durationMs, proxyIp }) {
  const db = getOffersDb();
  if (!db) return;
  const { insertOffer } = require('./lib/offers-db');
  // Defense in depth: always emit a non-null wizard_log so DB rows always
  // carry a diagnostic trail. If the handler returned no log, synthesize one
  // and append the error message — the bug we're guarding against here is
  // the 2026-04-13 consumer-1 carvana run that returned wizard_log=NULL.
  let logEntries = Array.isArray(result.wizardLog) ? result.wizardLog.slice() : [];
  if (logEntries.length === 0) {
    logEntries.push(`[server] ${site} handler returned no wizard_log`);
  }
  if (result.error) {
    logEntries.push(`[server] error: ${result.error}`);
  }
  try {
    insertOffer(db, {
      run_id: runId,
      vin: normalized.vin,
      mileage: Number(normalized.mileage),
      zip: normalized.zip,
      condition: normalized.condition,
      site,
      status: result.status || (result.offer_usd ? 'ok' : (result.error ? 'error' : 'ok')),
      offer_usd: result.offer_usd == null ? null : Number(result.offer_usd),
      offer_expires: result.offer_expires || null,
      proxy_ip: proxyIp || null,
      ran_at: new Date(startedAt || Date.now()).toISOString(),
      duration_ms: durationMs || null,
      wizard_log: logEntries,
    });
  } catch (e) {
    console.error(`[persist-offer] ${site} insert failed:`, e.message);
  }
}

/**
 * Extract a USD integer from a Carvana-style offer string ('$21,500') or a
 * direct number. Returns null if no match.
 */
function extractUsdInt(raw) {
  if (raw == null) return null;
  if (typeof raw === 'number' && Number.isFinite(raw)) return Math.round(raw);
  const m = String(raw).match(/\$?\s?([\d,]+)/);
  if (!m) return null;
  const n = parseInt(m[1].replace(/,/g, ''), 10);
  return Number.isFinite(n) ? n : null;
}

// --- Startup self-test state ---
const selfTest = {
  proxyResult: null,
  proxyTestedAt: null,
  startedAt: new Date().toISOString(),
  lastCarvanaRun: null,
};

/** Save diagnostic results to a static file so QA/external tools can read them */
function saveResults() {
  try {
    const resultsPath = path.join(__dirname, 'startup-results.json');
    fs.writeFileSync(resultsPath, JSON.stringify(selfTest, null, 2));
    console.log('[diag] Results saved to startup-results.json');
  } catch (e) {
    console.error('[diag] Failed to save results:', e.message);
  }
}

/**
 * Run a curl-based proxy test (no Playwright, no browser — just raw HTTP).
 * Tests: DNS, TCP, curl through proxy to httpbin.org and ip.decodo.com.
 */
async function runFullDiagnostic() {
  try { config.reloadConfig(); } catch (_) {}
  const host = config.PROXY_HOST || 'gate.decodo.com';
  const port = '7000'; // Decodo standard residential port (supports geo params)
  const user = config.PROXY_USER || '';
  const pass = config.PROXY_PASS || '';
  // Decodo requires user- prefix when using advanced params (country, zip, session)
  const geoUser = `user-${user}-country-us-zip-06880`;
  const diag = { timestamp: new Date().toISOString(), tests: {} };

  // Helper: run a shell command with timeout, return {ok, output/error}
  function run(label, cmd, timeoutMs = 15000) {
    try {
      const output = execSync(cmd, { timeout: timeoutMs, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
      diag.tests[label] = { ok: true, output: output.trim().substring(0, 500) };
      console.log(`[diag] ${label}: OK — ${output.trim().substring(0, 200)}`);
    } catch (err) {
      diag.tests[label] = { ok: false, error: (err.stderr || err.message || '').substring(0, 500), exitCode: err.status };
      console.log(`[diag] ${label}: FAIL — ${(err.stderr || err.message || '').substring(0, 200)}`);
    }
  }

  // Test 1: DNS resolution
  run('dns_resolve', `dig +short ${host} 2>&1 || nslookup ${host} 2>&1 | head -5`);

  // Test 2: TCP connectivity to proxy port
  run('tcp_proxy', `timeout 5 bash -c 'echo > /dev/tcp/${host}/${port}' 2>&1 && echo "TCP OK" || echo "TCP FAIL"`, 10000);

  // Test 3: curl through proxy WITH geo-targeting (US zip 06880) — port 7000
  const geoProxyUrl = `http://${geoUser}:${pass}@${host}:${port}`;
  run('curl_httpbin_geo', `curl -s --max-time 20 --proxy "${geoProxyUrl}" http://httpbin.org/ip 2>&1`);

  // Test 4: curl to ip.decodo.com through geo-targeted proxy
  run('curl_decodo_geo', `curl -s --max-time 20 --proxy "${geoProxyUrl}" https://ip.decodo.com/json 2>&1`);

  // Test 5: curl to httpbin directly (no proxy — baseline)
  run('curl_httpbin_direct', `curl -s --max-time 10 http://httpbin.org/ip 2>&1`);

  // Test 6: curl to Carvana through geo-targeted proxy (check if Cloudflare passes)
  run('curl_carvana_geo', `curl -s --max-time 20 -o /dev/null -w "%{http_code}" --proxy "${geoProxyUrl}" https://www.carvana.com/sell-my-car 2>&1`);

  // Test 7: plain proxy on port 10001 (no geo, for comparison)
  const plainProxyUrl = `http://${user}:${pass}@${host}:10001`;
  run('curl_httpbin_plain', `curl -s --max-time 15 --proxy "${plainProxyUrl}" http://httpbin.org/ip 2>&1`);

  selfTest.networkDiag = diag;
  selfTest.networkDiagAt = diag.timestamp;

  // Determine overall proxy status from geo-targeted curl tests
  // Primary: httpbin (returns clean IP JSON). Fallback: ip.decodo.com (also confirms geo).
  const httpbinResult = diag.tests.curl_httpbin_geo;
  const decodoResult = diag.tests.curl_decodo_geo;

  if (httpbinResult && httpbinResult.ok && httpbinResult.output.includes('origin') && !httpbinResult.output.includes('Access denied')) {
    try {
      const parsed = JSON.parse(httpbinResult.output);
      selfTest.proxyResult = { ok: true, ip: parsed.origin, method: 'curl-httpbin', port };
    } catch {
      selfTest.proxyResult = { ok: true, raw: httpbinResult.output, method: 'curl-httpbin', port };
    }
  } else if (decodoResult && decodoResult.ok && decodoResult.output.includes('isp') && !decodoResult.output.includes('Access denied')) {
    // ip.decodo.com worked — extract city/state info as confirmation
    try {
      // Output may be truncated, try to parse what we can
      const cityMatch = decodoResult.output.match(/"name":\s*"([^"]+)"/);
      const stateMatch = decodoResult.output.match(/"code":\s*"([^"]+)"/);
      const zipMatch = decodoResult.output.match(/"zip_code":\s*"([^"]+)"/);
      const city = cityMatch ? cityMatch[1] : 'unknown';
      const state = stateMatch ? stateMatch[1] : '?';
      const zipCode = zipMatch ? zipMatch[1] : '?';
      selfTest.proxyResult = { ok: true, location: `${city}, ${state} ${zipCode}`, method: 'curl-decodo', port };
      console.log(`[diag] Geo proxy confirmed via ip.decodo.com: ${city}, ${state} ${zipCode}`);
    } catch {
      selfTest.proxyResult = { ok: true, raw: decodoResult.output.substring(0, 200), method: 'curl-decodo', port };
    }
  } else if (diag.workingPort) {
    selfTest.proxyResult = { ok: true, method: 'curl', port: diag.workingPort, note: 'worked on alt port' };
    selfTest.workingPort = diag.workingPort;
  } else {
    selfTest.proxyResult = { ok: false, error: 'All curl proxy tests failed', method: 'curl', port };
  }
  selfTest.proxyTestedAt = new Date().toISOString();

  saveResults();
  return diag;
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
    h2.section {
      font-size: 1rem;
      color: #38bdf8;
      margin: 28px 0 4px;
      padding-top: 16px;
      border-top: 1px solid #334155;
    }
    .section-sub {
      font-size: 0.8rem;
      color: #94a3b8;
      margin-bottom: 4px;
    }
    .help {
      font-size: 0.75rem;
      color: #64748b;
      margin-top: 4px;
      line-height: 1.3;
    }
    .check {
      display: inline-block;
      color: #4ade80;
      font-weight: 700;
      margin-left: 6px;
    }
    .row {
      display: block;
      margin-bottom: 6px;
    }
    .row input {
      display: block;
      width: 100%;
      margin-bottom: 8px;
      box-sizing: border-box;
    }
    .save-one {
      display: block;
      width: 100%;
      padding: 10px 14px;
      font-size: 0.95rem;
      font-weight: 600;
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .save-one:disabled { opacity: 0.6; cursor: wait; }
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

    <label for="proxyPass">Proxy Password <span class="check" data-for="proxyPass"></span></label>
    <input type="password" id="proxyPass" name="proxyPass" placeholder="${config.PROXY_PASS ? '••••••••' : 'password'}" value="">

    <label for="projectEmail">Project Email <span class="check" data-for="projectEmail"></span></label>
    <input type="email" id="projectEmail" name="projectEmail" placeholder="you@example.com (optional)" value="${escapeAttr(config.PROJECT_EMAIL)}">

    <h2 class="section">Paid human-loop (Prolific + MTurk)</h2>
    <p class="section-sub">Orchestrator uses these to post paid micro-tasks when automation stalls.</p>

    <p class="section-sub">Paste whatever you have ready, tap <em>Save</em> next to that field. Other fields are left untouched — you can come back later for the rest.</p>

    <label for="prolificToken">Prolific API token <span class="check" data-for="prolificToken"></span></label>
    <div class="row"><input type="password" id="prolificToken" name="prolificToken" placeholder="${config.PROLIFIC_TOKEN ? '••••••••' : 'Paste Prolific API token'}" value="" autocomplete="off"><button type="button" class="save-one" data-field="prolificToken">Save</button></div>
    <p class="help">Create at app.prolific.com → Settings → API Tokens.</p>

    <label for="prolificBalanceUsd">Prolific prepaid balance (USD) <span class="check" data-for="prolificBalanceUsd"></span></label>
    <div class="row"><input type="number" id="prolificBalanceUsd" name="prolificBalanceUsd" placeholder="200" inputmode="numeric" min="0" step="1" value="${escapeAttr(config.PROLIFIC_BALANCE_USD || '')}"><button type="button" class="save-one" data-field="prolificBalanceUsd">Save</button></div>
    <p class="help">Whole dollars currently funded on your Prolific workspace.</p>

    <label for="mturkAccessKeyId">MTurk access key id <span class="check" data-for="mturkAccessKeyId"></span></label>
    <div class="row"><input type="text" id="mturkAccessKeyId" name="mturkAccessKeyId" placeholder="AKIA..." autocapitalize="characters" autocomplete="off" value="${escapeAttr(config.MTURK_ACCESS_KEY_ID)}"><button type="button" class="save-one" data-field="mturkAccessKeyId">Save</button></div>
    <p class="help">AWS IAM access key id for your MTurk requester account (starts with AKIA).</p>

    <label for="mturkSecretAccessKey">MTurk secret access key <span class="check" data-for="mturkSecretAccessKey"></span></label>
    <div class="row"><input type="password" id="mturkSecretAccessKey" name="mturkSecretAccessKey" placeholder="${config.MTURK_SECRET_ACCESS_KEY ? '••••••••' : 'Paste AWS secret key'}" value="" autocomplete="off"><button type="button" class="save-one" data-field="mturkSecretAccessKey">Save</button></div>
    <p class="help">Paired secret for the access key above; never shown back to you.</p>

    <label for="mturkBalanceUsd">MTurk prepaid balance (USD) <span class="check" data-for="mturkBalanceUsd"></span></label>
    <div class="row"><input type="number" id="mturkBalanceUsd" name="mturkBalanceUsd" placeholder="100" inputmode="numeric" min="0" step="1" value="${escapeAttr(config.MTURK_BALANCE_USD || '')}"><button type="button" class="save-one" data-field="mturkBalanceUsd">Save</button></div>
    <p class="help">Whole dollars currently prepaid on your MTurk requester account.</p>

    <label for="humanloopDailyCapUsd">Daily spending cap (USD) <span class="check" data-for="humanloopDailyCapUsd"></span></label>
    <div class="row"><input type="number" id="humanloopDailyCapUsd" name="humanloopDailyCapUsd" placeholder="50" inputmode="numeric" min="1" step="1" value="${escapeAttr(config.HUMANLOOP_DAILY_CAP_USD || 50)}"><button type="button" class="save-one" data-field="humanloopDailyCapUsd">Save</button></div>
    <p class="help">Hard daily cap across Prolific + MTurk. Orchestrator pauses paid tasks after this.</p>

    <button type="submit">Save everything at once</button>
  </form>

  <div class="card" style="margin-top:20px;">
    <button id="testBtn" type="button" onclick="testProxy()" style="background:#059669;">Test Proxy Connection</button>
    <div id="testResult" style="margin-top:12px;font-size:0.9rem;text-align:center;"></div>
  </div>

  <script>
    // Per-field Save buttons — paste one credential at a time, no need to
    // fill everything. Blank fields on the server keep the current value.
    document.querySelectorAll('.save-one').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const field = btn.getAttribute('data-field');
        const input = document.getElementById(field);
        if (!input || !input.value) {
          btn.textContent = 'Empty';
          setTimeout(function () { btn.textContent = 'Save'; }, 1400);
          return;
        }
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = 'Saving…';
        try {
          const body = {}; body[field] = input.value;
          const r = await fetch('/car-offers/api/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          if (r.ok) {
            btn.textContent = 'Saved ✓';
            btn.style.background = '#059669';
            if (input.type === 'password') input.value = '';
            const check = document.querySelector('.check[data-for="' + field + '"]');
            if (check) check.textContent = '\u2713 set';
          } else {
            let err = 'Error';
            try { const j = await r.json(); err = j.error || err; } catch (_) {}
            btn.textContent = err.slice(0, 20);
            btn.style.background = '#dc2626';
          }
        } catch (e) {
          btn.textContent = 'Network err';
          btn.style.background = '#dc2626';
        } finally {
          setTimeout(function () {
            btn.disabled = false;
            btn.textContent = original;
            btn.style.background = '';
          }, 2000);
        }
      });
    });

    // On load, fetch /api/setup/status and paint a green check next to
    // every field that's already configured. Never shows the actual value.
    (async function paintStatus() {
      try {
        const r = await fetch('/car-offers/api/setup/status', { cache: 'no-store' });
        if (!r.ok) return;
        const s = await r.json();
        const map = {
          proxyPass: s.proxy === true,
          projectEmail: s.email === true,
          prolificToken: s.prolific === true,
          prolificBalanceUsd: typeof s.prolific_balance === 'number' && s.prolific_balance > 0,
          mturkAccessKeyId: s.mturk === true,
          mturkSecretAccessKey: s.mturk === true,
          mturkBalanceUsd: typeof s.mturk_balance === 'number' && s.mturk_balance > 0,
          humanloopDailyCapUsd: typeof s.daily_cap === 'number' && s.daily_cap > 0,
        };
        document.querySelectorAll('.check').forEach(function (el) {
          var key = el.getAttribute('data-for');
          if (map[key]) el.textContent = '\u2713 set';
        });
      } catch (_) { /* silent: status is advisory only */ }
    })();

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
  const isJson = (req.headers['content-type'] || '').includes('application/json');
  const fail = (msg, field) => {
    if (isJson) return res.status(400).json({ ok: false, error: msg, field: field || null });
    return res.redirect('/car-offers/setup?msg=required');
  };

  // All fields: blank submission keeps the current value. This makes the form
  // safe for per-field "save one at a time" UX — typing just the Prolific token
  // and hitting Save will not clobber proxy/email.
  const keep = (raw, current) => (raw && sanitize(raw)) ? sanitize(raw) : (current || '');
  const proxyHost = keep(req.body.proxyHost, config.PROXY_HOST);
  const proxyPort = keep(req.body.proxyPort, config.PROXY_PORT);
  const proxyUser = keep(req.body.proxyUser, config.PROXY_USER);
  const proxyPass = keep(req.body.proxyPass, config.PROXY_PASS);
  const projectEmail = keep(req.body.projectEmail, config.PROJECT_EMAIL);

  // --- Paid human-loop fields (all optional: blank means "keep current"). ---
  const prolificToken = req.body.prolificToken
    ? sanitize(req.body.prolificToken)
    : config.PROLIFIC_TOKEN;
  const mturkAccessKeyId = req.body.mturkAccessKeyId
    ? sanitize(req.body.mturkAccessKeyId)
    : config.MTURK_ACCESS_KEY_ID;
  const mturkSecretAccessKey = req.body.mturkSecretAccessKey
    ? sanitize(req.body.mturkSecretAccessKey)
    : config.MTURK_SECRET_ACCESS_KEY;

  // Positive-int parser: blank means "don't update"; anything else must parse
  // to a non-negative integer. Returns { ok, value, error } so we can 400 early.
  function parseIntField(raw, label, currentVal, { min = 0 } = {}) {
    const s = sanitize(raw);
    if (!s) return { ok: true, value: currentVal };
    if (!/^\d+$/.test(s)) return { ok: false, error: `${label} must be a positive integer` };
    const n = parseInt(s, 10);
    if (n < min) return { ok: false, error: `${label} must be >= ${min}` };
    return { ok: true, value: n };
  }

  const prolificBal = parseIntField(req.body.prolificBalanceUsd, 'Prolific balance', config.PROLIFIC_BALANCE_USD);
  if (!prolificBal.ok) return fail(prolificBal.error, 'prolificBalanceUsd');
  const mturkBal = parseIntField(req.body.mturkBalanceUsd, 'MTurk balance', config.MTURK_BALANCE_USD);
  if (!mturkBal.ok) return fail(mturkBal.error, 'mturkBalanceUsd');
  const dailyCap = parseIntField(req.body.humanloopDailyCapUsd, 'Daily cap', config.HUMANLOOP_DAILY_CAP_USD, { min: 1 });
  if (!dailyCap.ok) return fail(dailyCap.error, 'humanloopDailyCapUsd');

  // MTurk access key id: only validate when a NEW non-empty value is submitted.
  // Blank means "don't change"; anything present must match the AWS IAM pattern.
  if (req.body.mturkAccessKeyId && sanitize(req.body.mturkAccessKeyId)) {
    if (!/^AKIA[0-9A-Z]{16}$/.test(mturkAccessKeyId)) {
      return fail('MTURK_ACCESS_KEY_ID must match /^AKIA[0-9A-Z]{16}$/', 'mturkAccessKeyId');
    }
  }

  // Write env files. The service runs from /opt/car-offers (live) or
  // /opt/car-offers-preview (preview); when invoked on one instance we also
  // mirror into the sibling instance's .env so "configure once" works for the
  // non-technical user. Missing sibling is fine — skip silently.
  const envContent = [
    `PROXY_HOST=${proxyHost}`,
    `PROXY_PORT=${proxyPort}`,
    `PROXY_USER=${proxyUser}`,
    `PROXY_PASS=${proxyPass}`,
    `PROJECT_EMAIL=${projectEmail}`,
    `PORT=${config.PORT}`,
    `PROLIFIC_TOKEN=${prolificToken}`,
    `PROLIFIC_BALANCE_USD=${prolificBal.value}`,
    `MTURK_ACCESS_KEY_ID=${mturkAccessKeyId}`,
    `MTURK_SECRET_ACCESS_KEY=${mturkSecretAccessKey}`,
    `MTURK_BALANCE_USD=${mturkBal.value}`,
    `HUMANLOOP_DAILY_CAP_USD=${dailyCap.value}`,
  ].join('\n') + '\n';

  // Dry-run mode: validate everything, don't persist, return {ok,saved:0,dry_run:true}.
  // Used by tests so they can exercise validation without clobbering real creds.
  const dryRun = req.query.dry_run === '1' || req.body.dry_run === true || req.body.dry_run === '1';

  const envPath = path.join(__dirname, '.env');
  let saved = 0;
  if (!dryRun) {
    try {
      fs.writeFileSync(envPath, envContent, 'utf8');
      saved += 1;
    } catch (e) {
      console.error('[setup] failed to write primary .env:', e.message);
      return isJson
        ? res.status(500).json({ ok: false, error: 'failed to write .env' })
        : res.redirect('/car-offers/setup?msg=required');
    }

    // Mirror to the sibling deployment (live <-> preview) if it exists.
    try {
      const siblingPaths = [
        '/opt/car-offers/.env',
        '/opt/car-offers-preview/.env',
      ].filter((p) => p !== envPath);
      for (const sp of siblingPaths) {
        const dir = path.dirname(sp);
        if (fs.existsSync(dir)) {
          fs.writeFileSync(sp, envContent, 'utf8');
          saved += 1;
        }
      }
    } catch (e) {
      // Non-fatal: the primary was already written.
      console.error('[setup] failed to mirror .env to sibling:', e.message);
    }

    config.reloadConfig();
  }

  if (isJson) {
    return res.json({ ok: true, saved, dry_run: dryRun });
  }
  if (dryRun) return res.redirect('/car-offers/setup?msg=saved');
  res.redirect('/car-offers/setup?msg=saved');

  // Re-run diagnostics in background after config change (skip on dry-run)
  if (!dryRun) {
    setTimeout(async () => {
      console.log('[setup] Config changed — re-running diagnostics...');
      await runFullDiagnostic();
      if (selfTest.proxyResult && selfTest.proxyResult.ok) {
        console.log('[setup] Curl proxy works! Testing Playwright browser...');
        await testPlaywrightProxy();
      }
    }, 2000);
  }
});

// Booleans-only view of what's configured. NEVER returns secret values.
// Used by /setup to show "already set" checkmarks next to each field.
// Shape: { proxy, email, prolific, mturk, daily_cap, prolific_balance, mturk_balance }
// - proxy/email/prolific/mturk are booleans: "is this credential set?"
// - daily_cap / *_balance are numbers: balances are non-secret integers the
//   user typed, fine to echo, and we want the UI to surface them.
app.get('/api/setup/status', (_req, res) => {
  try { config.reloadConfig(); } catch (_) { /* .env may not exist yet */ }
  res.json({
    proxy: !!config.PROXY_PASS,
    email: !!config.PROJECT_EMAIL,
    prolific: !!config.PROLIFIC_TOKEN,
    mturk: !!(config.MTURK_ACCESS_KEY_ID && config.MTURK_SECRET_ACCESS_KEY),
    daily_cap: Number(config.HUMANLOOP_DAILY_CAP_USD) || 50,
    prolific_balance: Number(config.PROLIFIC_BALANCE_USD) || 0,
    mturk_balance: Number(config.MTURK_BALANCE_USD) || 0,
  });
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

// --- Wizard debug gallery (mobile-friendly thumbnails + HTML-dump links) ---
// Scans public-debug/ and renders per-site, newest-first listings. Exists so
// the user can watch the wizard's view as fixes land, without SSH.
app.get('/debug', (_req, res) => {
  const escapeHtml = (s) => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  let sites = [];
  try {
    sites = fs.readdirSync(DEBUG_DUMP_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .sort();
  } catch { sites = []; }

  const sections = sites.map((site) => {
    const siteDir = path.join(DEBUG_DUMP_DIR, site);
    let files = [];
    try {
      files = fs.readdirSync(siteDir)
        .filter((f) => f.endsWith('.png') || f.endsWith('.html'));
    } catch { files = []; }

    // Group by base name (without extension) so PNG + HTML of same capture
    // appear together.
    const byBase = new Map();
    for (const f of files) {
      const base = f.replace(/\.(png|html)$/, '');
      const ext = f.endsWith('.png') ? 'png' : 'html';
      let stat = null;
      try { stat = fs.statSync(path.join(siteDir, f)); } catch { /* ok */ }
      if (!byBase.has(base)) byBase.set(base, { base, png: null, html: null, mtime: 0 });
      const entry = byBase.get(base);
      entry[ext] = f;
      if (stat && stat.mtimeMs > entry.mtime) entry.mtime = stat.mtimeMs;
    }

    const entries = Array.from(byBase.values())
      .sort((a, b) => b.mtime - a.mtime);

    if (entries.length === 0) {
      return `<section><h2>${escapeHtml(site)}</h2><p class="muted">No captures yet.</p></section>`;
    }

    const rows = entries.map((e) => {
      const when = e.mtime ? new Date(e.mtime).toISOString().replace('T', ' ').replace(/\..*$/, '') + ' UTC' : '';
      const pngHref = e.png ? `debug/${encodeURIComponent(site)}/${encodeURIComponent(e.png)}` : null;
      const htmlHref = e.html ? `debug/${encodeURIComponent(site)}/${encodeURIComponent(e.html)}` : null;
      const thumb = pngHref
        ? `<a href="${pngHref}" class="thumb"><img loading="lazy" src="${pngHref}" alt="${escapeHtml(e.base)}"></a>`
        : `<div class="thumb placeholder">no&nbsp;png</div>`;
      const links = [
        pngHref ? `<a href="${pngHref}">png</a>` : null,
        htmlHref ? `<a href="${htmlHref}">html</a>` : null,
      ].filter(Boolean).join(' &middot; ');
      return `<li>
        ${thumb}
        <div class="meta">
          <div class="name">${escapeHtml(e.base)}</div>
          <div class="when">${escapeHtml(when)}</div>
          <div class="links">${links}</div>
        </div>
      </li>`;
    }).join('\n');

    return `<section><h2>${escapeHtml(site)} <span class="count">${entries.length}</span></h2><ul class="captures">${rows}</ul></section>`;
  }).join('\n');

  const body = sites.length === 0
    ? '<p class="muted">No sites have captured debug output yet. Run a wizard with <code>debug: true</code>.</p>'
    : sections;

  res.set('Cache-Control', 'no-store');
  res.send(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>car-offers &middot; wizard debug captures</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font: 15px/1.45 -apple-system, system-ui, Segoe UI, Roboto, sans-serif; margin: 0; padding: 16px; background: #0b0d10; color: #e7edf3; }
  h1 { margin: 0 0 4px; font-size: 18px; }
  h2 { margin: 20px 0 10px; font-size: 16px; text-transform: uppercase; letter-spacing: .05em; color: #9fb3c8; }
  h2 .count { display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 10px; background: #1f2a36; color: #9fb3c8; font-size: 12px; letter-spacing: 0; text-transform: none; }
  .muted { color: #7a8a9a; }
  p.hint { margin: 0 0 16px; color: #7a8a9a; font-size: 13px; }
  ul.captures { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr; gap: 10px; }
  @media (min-width: 640px) { ul.captures { grid-template-columns: repeat(2, 1fr); } }
  @media (min-width: 960px) { ul.captures { grid-template-columns: repeat(3, 1fr); } }
  li { display: flex; gap: 10px; padding: 10px; background: #131821; border: 1px solid #1f2a36; border-radius: 8px; }
  a.thumb, .thumb.placeholder { flex: 0 0 96px; width: 96px; height: 96px; border-radius: 6px; overflow: hidden; background: #0b0d10; display: flex; align-items: center; justify-content: center; color: #536877; font-size: 12px; }
  a.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .meta { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .name { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; word-break: break-all; }
  .when { color: #7a8a9a; font-size: 12px; }
  .links a { color: #76a8ff; text-decoration: none; margin-right: 6px; }
  .links a:hover { text-decoration: underline; }
  code { background: #1f2a36; padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
  <h1>wizard debug captures</h1>
  <p class="hint">Newest first. Tap a thumbnail for full-size screenshot; tap <code>html</code> for the raw page dump.</p>
  ${body}
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

// --- Proxy test endpoint (uses curl, not Playwright) ---
app.get('/api/test-proxy', async (_req, res) => {
  try { config.reloadConfig(); } catch (_) {}
  if (!config.PROXY_HOST || !config.PROXY_PASS) {
    return res.json({ ok: false, error: 'Proxy not configured. Save your password first.' });
  }
  const diag = await runFullDiagnostic();
  return res.json({ ok: !!selfTest.proxyResult?.ok, result: selfTest.proxyResult, diag: diag.tests });
});

// --- Serve static results file (for QA/external tools) ---
app.get('/api/startup-results', (_req, res) => {
  const resultsPath = path.join(__dirname, 'startup-results.json');
  if (fs.existsSync(resultsPath)) {
    res.setHeader('Content-Type', 'application/json');
    return res.send(fs.readFileSync(resultsPath, 'utf8'));
  }
  res.json({ error: 'No results yet — server may still be starting up' });
});

/**
 * Test Playwright browser through proxy (after curl confirms proxy works).
 */
async function testPlaywrightProxy() {
  let browser = null;
  try {
    const proxyPort = '7000';
    const proxyUser = `user-${config.PROXY_USER}-country-us-zip-06880`;
    const pw = require('playwright');
    browser = await pw.chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      proxy: {
        server: `http://${config.PROXY_HOST}:${proxyPort}`,
        username: proxyUser,
        password: config.PROXY_PASS,
      },
    });
    const page = await browser.newPage();
    await page.goto('http://httpbin.org/ip', { timeout: 30000 });
    const body = await page.textContent('body');
    await browser.close();
    browser = null;

    const parsed = JSON.parse(body.trim());
    selfTest.playwrightProxy = { ok: true, ip: parsed.origin, testedAt: new Date().toISOString() };
    console.log(`[startup] Playwright proxy WORKS! IP: ${parsed.origin}`);
  } catch (err) {
    if (browser) try { await browser.close(); } catch (_) {}
    selfTest.playwrightProxy = { ok: false, error: err.message, testedAt: new Date().toISOString() };
    console.error(`[startup] Playwright proxy FAILED: ${err.message}`);
  }
  saveResults();
}

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
    <details>
      <summary style="color:#94a3b8;font-size:0.8rem;cursor:pointer;">Raw JSON (tap to expand)</summary>
      <pre id="rawJson" style="font-size:0.65rem;color:#64748b;overflow-x:auto;max-height:400px;margin-top:8px;white-space:pre-wrap;word-break:break-all;"></pre>
    </details>
  </div>

  <div class="card">
    <h2>Compare all 3 buyers (same VIN)</h2>
    <div style="font-size:0.8rem;color:#94a3b8;margin-bottom:8px;">
      Runs Carvana -> CarMax -> Driveway sequentially with the same inputs.
      Takes 10-20 min. Results persist in offers.db.
    </div>
    <label style="display:block;font-size:0.8rem;color:#94a3b8;margin-top:10px;">VIN</label>
    <input id="cmpVin" type="text" maxlength="17" autocapitalize="characters" placeholder="1HGCV2F9XNA008352" value="1HGCV2F9XNA008352" style="width:100%;padding:10px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#f1f5f9;font-size:0.9rem;outline:none;">
    <label style="display:block;font-size:0.8rem;color:#94a3b8;margin-top:10px;">Mileage</label>
    <input id="cmpMileage" type="number" inputmode="numeric" placeholder="48000" value="48000" style="width:100%;padding:10px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#f1f5f9;font-size:0.9rem;outline:none;">
    <label style="display:block;font-size:0.8rem;color:#94a3b8;margin-top:10px;">Zip</label>
    <input id="cmpZip" type="text" maxlength="5" inputmode="numeric" placeholder="06880" value="06880" style="width:100%;padding:10px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#f1f5f9;font-size:0.9rem;outline:none;">
    <label style="display:block;font-size:0.8rem;color:#94a3b8;margin-top:10px;">Condition</label>
    <select id="cmpCondition" style="width:100%;padding:10px;border:1px solid #334155;border-radius:6px;background:#0f172a;color:#f1f5f9;font-size:0.9rem;outline:none;">
      <option value="Excellent">Excellent</option>
      <option value="Good" selected>Good</option>
      <option value="Fair">Fair</option>
      <option value="Poor">Poor</option>
    </select>
    <button class="btn-orange" id="cmpBtn" onclick="runCompare()">Run comparison (10-20 min)</button>
    <div id="cmpLog" style="margin-top:8px;font-size:0.8rem;color:#94a3b8;text-align:center;"></div>
    <div id="cmpResults" style="margin-top:12px;"></div>
    <div style="margin-top:10px;font-size:0.8rem;color:#94a3b8;text-align:center;">
      <a href="#" id="cmpLatestLink" style="color:#38bdf8;text-decoration:none;">Check latest stored offers for this VIN</a>
    </div>
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
        document.getElementById('rawJson').textContent = JSON.stringify(data, null, 2);
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
          const loc = p.test_result.location || p.test_result.ip || '?';
          html += row('Test', '<span class="ok">PASS — ' + esc(loc) + '</span>');
          html += row('Method', esc(p.test_result.method || '?') + ' port ' + esc(p.test_result.port || '?'));
        } else {
          html += row('Test', '<span class="fail">FAIL — ' + esc(p.test_result.error || 'unknown') + '</span>');
          html += row('Method', esc(p.test_result.method || '?'));
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
      let html = '';
      if (r.offer) {
        html += '<div class="offer-big">' + esc(r.offer) + '</div>';
        html += row('VIN', r.vin || '');
        html += row('Browser', (r.details && r.details.launchMethod) || 'unknown');
        html += row('Completed', r.completed_at ? new Date(r.completed_at).toLocaleString() : '');
      } else if (r.error) {
        html += '<div class="error-big">' + esc(r.error) + '</div>';
        html += row('VIN', r.vin || '');
        html += row('Browser', (r.details && r.details.launchMethod) || 'unknown');
        html += row('Completed', r.completed_at ? new Date(r.completed_at).toLocaleString() : '');
        // Show full diagnostic details when there's an error
        if (r.details) {
          const d = r.details;
          if (d.pageState) {
            html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #334155;">';
            html += '<div style="color:#94a3b8;font-size:0.8rem;margin-bottom:8px;">PAGE DIAGNOSTICS</div>';
            if (d.pageState.url) html += row('URL', esc(d.pageState.url));
            if (d.pageState.title) html += row('Title', esc(d.pageState.title));
            if (d.pageState.bodySnippet) {
              html += '<div style="margin-top:8px;font-size:0.75rem;color:#94a3b8;">Body text (first 500 chars):</div>';
              html += '<div style="font-size:0.7rem;color:#64748b;word-break:break-all;padding:8px;background:#0f172a;border-radius:6px;margin-top:4px;max-height:200px;overflow-y:auto;">' + esc(d.pageState.bodySnippet.substring(0, 500)) + '</div>';
            }
            html += '</div>';
          }
          if (d.pageTitle) html += row('Page Title', esc(d.pageTitle));
          if (d.bodySnippet && !d.pageState) {
            html += '<div style="font-size:0.7rem;color:#64748b;word-break:break-all;padding:8px;background:#0f172a;border-radius:6px;margin-top:4px;">' + esc(d.bodySnippet.substring(0, 500)) + '</div>';
          }
          if (d.url) html += row('Page URL', esc(d.url));
        }
      }
      // Wizard log (shows step-by-step what happened)
      if (r.wizardLog && r.wizardLog.length > 0) {
        html += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #334155;">';
        html += '<details><summary style="color:#94a3b8;font-size:0.8rem;cursor:pointer;">Wizard Log (' + r.wizardLog.length + ' steps)</summary>';
        html += '<div style="font-size:0.7rem;color:#64748b;padding:8px;background:#0f172a;border-radius:6px;margin-top:4px;max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;">';
        html += r.wizardLog.map(function(l) { return esc(l); }).join('\\n');
        html += '</div></details></div>';
      }
      content.innerHTML = html;
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

    // --- Compare all 3 ---
    async function runCompare() {
      const btn = document.getElementById('cmpBtn');
      const log = document.getElementById('cmpLog');
      const out = document.getElementById('cmpResults');
      const vin = document.getElementById('cmpVin').value.trim().toUpperCase();
      const mileage = document.getElementById('cmpMileage').value.trim();
      const zip = document.getElementById('cmpZip').value.trim();
      const condition = document.getElementById('cmpCondition').value;
      if (!vin || !mileage || !zip) {
        log.innerHTML = '<span class="fail">Fill in VIN, mileage, zip</span>';
        return;
      }
      btn.disabled = true; btn.textContent = 'Running (10-20 min)...';
      log.innerHTML = '<span class="pending">Running Carvana -> CarMax -> Driveway sequentially...</span>';
      out.innerHTML = '';
      try {
        const resp = await fetch('/car-offers/api/quote-all', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vin, mileage, zip, condition }),
        });
        const data = await resp.json();
        if (data.error && !data.run_id) {
          log.innerHTML = '<span class="fail">' + esc(data.error) + '</span>';
        } else {
          log.innerHTML = '<span class="ok">Done — run ' + esc(data.run_id || '') + '</span>';
          out.innerHTML = renderCompareCols(data);
        }
      } catch (e) {
        log.innerHTML = '<span class="fail">' + esc(e.message) + '</span>';
      } finally {
        btn.disabled = false; btn.textContent = 'Run comparison (10-20 min)';
      }
    }

    function renderCompareCols(data) {
      var sites = ['carvana', 'carmax', 'driveway'];
      var cols = sites.map(function(s) {
        var r = data[s] || { status: 'missing' };
        var color = r.status === 'ok' ? '#4ade80'
                  : r.status === 'blocked' ? '#f87171'
                  : r.status === 'account_required' ? '#fbbf24'
                  : '#94a3b8';
        var amt = r.offer_usd ? ('$' + Number(r.offer_usd).toLocaleString())
                 : r.offer || '—';
        return '<div style="flex:1;min-width:0;background:#0f172a;border-radius:8px;padding:10px;margin:4px;">'
             + '<div style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;">' + esc(s) + '</div>'
             + '<div style="font-size:1.4rem;font-weight:700;color:' + color + ';margin:4px 0;">' + esc(amt) + '</div>'
             + '<div style="color:#94a3b8;font-size:0.7rem;">status: ' + esc(r.status || '?') + '</div>'
             + (r.offer_expires ? '<div style="color:#94a3b8;font-size:0.7rem;">expires: ' + esc(r.offer_expires) + '</div>' : '')
             + (r.error ? '<div style="color:#f87171;font-size:0.7rem;word-break:break-word;margin-top:4px;">' + esc(r.error.substring(0, 120)) + '</div>' : '')
             + '</div>';
      }).join('');
      return '<div style="display:flex;flex-wrap:wrap;margin:-4px;">' + cols + '</div>'
           + '<div style="margin-top:8px;font-size:0.75rem;color:#64748b;text-align:center;">VIN ' + esc(data.vin || '') + ' / ' + esc(String(data.mileage||'')) + ' mi / ' + esc(data.zip || '') + ' / ' + esc(data.condition || '') + '</div>';
    }

    // Wire up "check latest stored offers" link
    document.getElementById('cmpLatestLink').addEventListener('click', async function(ev) {
      ev.preventDefault();
      var vin = document.getElementById('cmpVin').value.trim().toUpperCase();
      if (!vin) return;
      var out = document.getElementById('cmpResults');
      out.innerHTML = '<span style="color:#94a3b8;font-size:0.8rem;">Loading stored offers...</span>';
      try {
        var r = await fetch('/car-offers/api/compare/' + encodeURIComponent(vin));
        var data = await r.json();
        out.innerHTML = renderCompareCols({
          carvana: data.carvana ? { status: data.carvana.status, offer_usd: data.carvana.offer_usd, offer_expires: data.carvana.offer_expires, error: null } : { status: 'none' },
          carmax:  data.carmax  ? { status: data.carmax.status,  offer_usd: data.carmax.offer_usd,  offer_expires: data.carmax.offer_expires,  error: null } : { status: 'none' },
          driveway: data.driveway ? { status: data.driveway.status, offer_usd: data.driveway.offer_usd, offer_expires: data.driveway.offer_expires, error: null } : { status: 'none' },
          vin: vin, mileage: (data.carvana||data.carmax||data.driveway||{}).mileage || '',
          zip: (data.carvana||data.carmax||data.driveway||{}).zip || '',
          condition: (data.carvana||data.carmax||data.driveway||{}).condition || '',
        });
      } catch (e) {
        out.innerHTML = '<span style="color:#f87171;font-size:0.8rem;">' + esc(e.message) + '</span>';
      }
    });

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
    playwrightProxy: selfTest.playwrightProxy || null,
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

// --- Last Carvana run result (full wizardLog for diagnostics) ---
app.get('/api/last-run', (_req, res) => {
  if (!selfTest.lastCarvanaRun) {
    return res.json({ status: 'pending', message: 'No Carvana run completed yet. Check back in 2-5 minutes.' });
  }
  // Return full result including wizardLog
  res.json(selfTest.lastCarvanaRun);
});

// --- Retest proxy endpoint ---
app.get('/api/retest-proxy', async (_req, res) => {
  res.json({ ok: true, message: 'Proxy retest started. Check /car-offers/api/status in 20-30s.' });
  await runFullDiagnostic();
});

// --- Browser diagnostic: can Chromium launch at all? ---
app.get('/api/diag-browser', async (_req, res) => {
  let browser = null;
  const steps = [];
  try {
    steps.push('Loading browser library...');
    let pw;
    try {
      pw = require('patchright');
      steps.push('Using patchright (CDP leak patched)');
    } catch (_) {
      try {
        pw = require('playwright');
        steps.push('Using playwright (patchright not available)');
      } catch (e) {
        steps.push(`playwright require failed: ${e.message}`);
        return res.json({ ok: false, steps, error: e.message });
      }
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
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
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

// ============================================================================
// Site-handler endpoints: /api/carvana, /api/carmax, /api/driveway
// All take the same body shape: { vin, mileage, zip, condition? }
// All persist to offers.db.
// ============================================================================

/**
 * Normalize + persist a single-site handler result, returning the JSON body
 * to send. `handler` is an async fn that takes {vin, mileage, zip, condition,
 * email} and returns a result object. `site` is 'carvana'|'carmax'|'driveway'.
 */
async function runSiteHandler({ site, handler, req, res, runId }) {
  let normalized;
  try {
    normalized = normalizeOfferRequest(req.body || {});
  } catch (e) {
    return res.status(400).json({ error: e.message });
  }
  const started = Date.now();
  const debug = !!(req.body && req.body.debug);
  try {
    const result = await handler({
      vin: normalized.vin,
      mileage: normalized.mileage,
      zip: normalized.zip,
      condition: normalized.condition,
      email: config.PROJECT_EMAIL,
      debug,
    });
    // Normalize: carvana.js returns { offer: '$...', details, wizardLog }.
    // carmax/driveway return { status, offer_usd, offer_expires, ... }.
    // Unify for persistence:
    const offerUsd = result.offer_usd != null
      ? Number(result.offer_usd)
      : extractUsdInt(result.offer);
    const status = result.status
      || (offerUsd ? 'ok' : (result.error ? 'error' : 'ok'));
    persistOffer({
      site,
      runId: runId || `${site}-${started}-${Math.random().toString(36).slice(2, 8)}`,
      normalized,
      result: { ...result, offer_usd: offerUsd, status },
      startedAt: started,
      durationMs: Date.now() - started,
    });
    return res.json({
      site,
      status,
      offer_usd: offerUsd,
      offer: result.offer || (offerUsd ? `$${offerUsd.toLocaleString()}` : null),
      offer_expires: result.offer_expires || null,
      error: result.error || null,
      details: result.details || null,
      wizardLog: result.wizardLog || [],
    });
  } catch (err) {
    console.error(`[server] ${site} error:`, err);
    persistOffer({
      site,
      runId: runId || `${site}-${started}-${Math.random().toString(36).slice(2, 8)}`,
      normalized,
      result: { status: 'error', error: err.message },
      startedAt: started,
      durationMs: Date.now() - started,
    });
    return res.status(500).json({ site, status: 'error', error: err.message || 'Internal server error' });
  }
}

app.post('/api/carvana', async (req, res) => {
  let getCarvanaOffer;
  try { ({ getCarvanaOffer } = require('./lib/carvana')); }
  catch (e) {
    console.error('[server] Carvana module load failed:', e.message);
    return res.status(503).json({ error: 'Carvana module not available — dependencies may still be installing.' });
  }
  return runSiteHandler({ site: 'carvana', handler: getCarvanaOffer, req, res });
});

app.post('/api/carmax', async (req, res) => {
  let getCarmaxOffer;
  try { ({ getCarmaxOffer } = require('./lib/carmax')); }
  catch (e) {
    console.error('[server] CarMax module load failed:', e.message);
    return res.status(503).json({ error: 'CarMax module not available — dependencies may still be installing.' });
  }
  return runSiteHandler({ site: 'carmax', handler: getCarmaxOffer, req, res });
});

app.post('/api/driveway', async (req, res) => {
  let getDrivewayOffer;
  try { ({ getDrivewayOffer } = require('./lib/driveway')); }
  catch (e) {
    console.error('[server] Driveway module load failed:', e.message);
    return res.status(503).json({ error: 'Driveway module not available — dependencies may still be installing.' });
  }
  return runSiteHandler({ site: 'driveway', handler: getDrivewayOffer, req, res });
});

// ============================================================================
// Comparison: /api/quote-all runs the three buyers sequentially against the
// SAME VIN/mileage/zip/condition, groups them under one run_id.
// ============================================================================

/** Random pause between site runs (30-90s) — avoids obvious bot-burst. */
function interSitePause() {
  const ms = 30000 + Math.floor(Math.random() * 60000);
  return new Promise((r) => setTimeout(r, ms));
}

app.post('/api/quote-all', async (req, res) => {
  let normalized;
  try {
    normalized = normalizeOfferRequest(req.body || {});
  } catch (e) {
    return res.status(400).json({ error: e.message });
  }

  const runId = `run-${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
  const comparedAt = new Date().toISOString();
  const results = { carvana: null, carmax: null, driveway: null };

  // Load handlers lazily so one missing module doesn't kill the others.
  const siteHandlers = [
    ['carvana', () => require('./lib/carvana').getCarvanaOffer],
    ['carmax',  () => require('./lib/carmax').getCarmaxOffer],
    ['driveway', () => require('./lib/driveway').getDrivewayOffer],
  ];

  for (let i = 0; i < siteHandlers.length; i++) {
    const [site, loader] = siteHandlers[i];
    const started = Date.now();
    let siteResult;
    try {
      const handler = loader();
      const raw = await handler({
        vin: normalized.vin,
        mileage: normalized.mileage,
        zip: normalized.zip,
        condition: normalized.condition,
        email: config.PROJECT_EMAIL,
      });
      const offerUsd = raw.offer_usd != null ? Number(raw.offer_usd) : extractUsdInt(raw.offer);
      const status = raw.status || (offerUsd ? 'ok' : (raw.error ? 'error' : 'ok'));
      siteResult = {
        site,
        status,
        offer_usd: offerUsd,
        offer: raw.offer || (offerUsd ? `$${offerUsd.toLocaleString()}` : null),
        offer_expires: raw.offer_expires || null,
        error: raw.error || null,
        duration_ms: Date.now() - started,
      };
      persistOffer({
        site, runId, normalized,
        result: { ...raw, status, offer_usd: offerUsd },
        startedAt: started, durationMs: siteResult.duration_ms,
      });
    } catch (err) {
      console.error(`[quote-all] ${site} failed:`, err.message);
      siteResult = {
        site, status: 'error', offer_usd: null, offer: null,
        error: err.message, duration_ms: Date.now() - started,
      };
      persistOffer({
        site, runId, normalized,
        result: { status: 'error', error: err.message },
        startedAt: started, durationMs: siteResult.duration_ms,
      });
    }
    results[site] = siteResult;
    // Gap between sites (skip after the last)
    if (i < siteHandlers.length - 1) {
      console.log(`[quote-all] ${site} done — pausing 30-90s before next site`);
      await interSitePause();
    }
  }

  return res.json({
    run_id: runId,
    vin: normalized.vin,
    mileage: normalized.mileage,
    zip: normalized.zip,
    condition: normalized.condition,
    comparedAt,
    ...results,
  });
});

/**
 * GET /api/compare/:vin
 * Returns the latest offer per site for the given VIN (across runs).
 * Always returns a well-formed object, even if there are no rows.
 */
app.get('/api/compare/:vin', (req, res) => {
  const db = getOffersDb();
  if (!db) {
    return res.json({
      vin: (req.params.vin || '').toUpperCase(),
      carvana: null, carmax: null, driveway: null,
      run_id: null, ran_at: null,
      error: 'offers DB not available',
    });
  }
  try {
    const { getLatestByVin } = require('./lib/offers-db');
    const latest = getLatestByVin(db, req.params.vin || '');
    return res.json(latest);
  } catch (e) {
    console.error('[compare] error:', e.message);
    return res.status(500).json({
      vin: (req.params.vin || '').toUpperCase(),
      carvana: null, carmax: null, driveway: null,
      run_id: null, ran_at: null,
      error: e.message,
    });
  }
});

/**
 * GET /api/runs?limit=N
 * Recent comparison runs grouped by run_id.
 */
app.get('/api/runs', (req, res) => {
  const db = getOffersDb();
  if (!db) return res.json({ runs: [], error: 'offers DB not available' });
  try {
    const { getRuns } = require('./lib/offers-db');
    const limit = parseInt(req.query.limit || '20', 10);
    return res.json({ runs: getRuns(db, limit) });
  } catch (e) {
    console.error('[runs] error:', e.message);
    return res.status(500).json({ runs: [], error: e.message });
  }
});

/**
 * GET /api/compare-all?limit=50
 * Flat, view-friendly projection of recent runs for the /compare page.
 * Shape:
 *   {
 *     total_runs: <number — distinct run_ids in DB>,
 *     runs: [
 *       {
 *         run_id, ran_at, vin, mileage, zip, condition,
 *         carvana: { status, offer_usd, offer_expires } | null,
 *         carmax:  { status, offer_usd, offer_expires } | null,
 *         driveway:{ status, offer_usd, offer_expires } | null
 *       }, ...
 *     ]
 *   }
 */
app.get('/api/compare-all', (req, res) => {
  const db = getOffersDb();
  if (!db) return res.json({ runs: [], total_runs: 0, error: 'offers DB not available' });
  try {
    const { getRuns } = require('./lib/offers-db');
    const limit = Math.max(1, Math.min(200, parseInt(req.query.limit || '50', 10) || 50));
    const grouped = getRuns(db, limit);

    // Count distinct runs overall (cheap)
    let totalRuns = 0;
    try {
      const row = db.prepare(`SELECT COUNT(DISTINCT run_id) AS c FROM offers`).get();
      totalRuns = (row && row.c) || 0;
    } catch (_) { /* table may not exist yet */ }

    const siteProjection = (r) => {
      if (!r) return null;
      return {
        status: r.status || null,
        offer_usd: r.offer_usd == null ? null : Number(r.offer_usd),
        offer_expires: r.offer_expires || null,
      };
    };

    const runs = grouped.map((g) => {
      // Pull meta from any available row (they all share vin/mileage/zip/condition within a run)
      const any = g.carvana || g.carmax || g.driveway || (g.rows && g.rows[0]) || {};
      return {
        run_id: g.run_id,
        ran_at: g.latest_at || any.ran_at || null,
        vin: g.vin || any.vin || null,
        mileage: any.mileage == null ? null : Number(any.mileage),
        zip: any.zip || null,
        condition: any.condition || null,
        carvana: siteProjection(g.carvana),
        carmax: siteProjection(g.carmax),
        driveway: siteProjection(g.driveway),
      };
    });

    return res.json({ total_runs: totalRuns, runs });
  } catch (e) {
    console.error('[compare-all] error:', e.message);
    return res.status(500).json({ runs: [], total_runs: 0, error: e.message });
  }
});

// ============================================================================
// Consumer panel — 12 permanent identities, biweekly shopping cadence.
// ============================================================================

/** GET /api/panel — summary + per-consumer latest offers. */
app.get('/api/panel', (_req, res) => {
  const db = getOffersDb();
  if (!db) return res.status(503).json({ error: 'offers DB not available' });
  try {
    const { getPanelStatus } = require('./lib/offers-db');
    return res.json(getPanelStatus(db));
  } catch (e) {
    console.error('[panel] status error:', e.message);
    return res.status(500).json({ error: e.message });
  }
});

/**
 * POST /api/panel/seed — one-time seed. Reads CONSUMERS from
 * lib/panel-seed.js and inserts each. Refuses to run if the consumers
 * table is already populated (idempotent). Optional JSON body with a
 * `consumers` array overrides the default seed list.
 */
app.post('/api/panel/seed', (req, res) => {
  const db = getOffersDb();
  if (!db) return res.status(503).json({ error: 'offers DB not available' });
  try {
    const { listConsumers, insertConsumer } = require('./lib/offers-db');
    const existing = listConsumers(db);
    if (existing.length > 0) {
      return res.status(409).json({
        error: 'consumers table already seeded',
        count: existing.length,
      });
    }
    const body = req.body || {};
    const seedList = Array.isArray(body.consumers) && body.consumers.length > 0
      ? body.consumers
      : require('./lib/panel-seed').CONSUMERS;
    const inserted = [];
    for (const c of seedList) {
      try {
        insertConsumer(db, c);
        inserted.push({ id: c.id, vin: c.vin, name: c.name });
      } catch (e) {
        console.error(`[panel/seed] skip consumer ${c && c.id}: ${e.message}`);
      }
    }
    return res.json({ ok: true, inserted: inserted.length, consumers: inserted });
  } catch (e) {
    console.error('[panel/seed] error:', e.message);
    return res.status(500).json({ error: e.message });
  }
});

/**
 * POST /api/panel/run — trigger runDueConsumers (hourly cron entry point).
 * Returns immediately after kicking off the run; actual work happens in
 * the background. The response describes how many consumers were due.
 */
app.post('/api/panel/run', async (_req, res) => {
  try {
    const { runDueConsumers } = require('./lib/panel-runner');
    // Fire and forget — panel runs take minutes, don't tie up the HTTP client.
    const promise = runDueConsumers({});
    // Give it ~800ms so we can report the `due` count; the rest runs async.
    let early;
    try {
      early = await Promise.race([
        promise,
        new Promise((r) => setTimeout(() => r({ pending: true }), 800)),
      ]);
    } catch (e) { early = { error: e.message }; }
    return res.json({ ok: true, early });
  } catch (e) {
    console.error('[panel/run] error:', e.message);
    return res.status(500).json({ error: e.message });
  }
});

/** POST /api/panel/run/:id — ad-hoc single-consumer run. */
app.post('/api/panel/run/:id', async (req, res) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id) || id <= 0) return res.status(400).json({ error: 'invalid id' });
  try {
    const { runConsumerById } = require('./lib/panel-runner');
    // Fire-and-forget; the run can take 5-15 min. Return 202 with the
    // consumer id so the client knows the work is queued.
    runConsumerById(id).catch((e) => console.error(`[panel/run/${id}] background failed: ${e.message}`));
    return res.status(202).json({ ok: true, consumer_id: id, status: 'queued' });
  } catch (e) {
    console.error(`[panel/run/${id}] error:`, e.message);
    return res.status(500).json({ error: e.message });
  }
});

/** GET /panel — mobile-first HTML view of the panel. */
app.get('/panel', (_req, res) => {
  res.set('Content-Type', 'text/html; charset=utf-8');
  res.send(`<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Car Offers &mdash; Panel</title>
<style>
  :root {
    --bg:#0e1116; --panel:#161b22; --panel-2:#1c232c; --border:#2a313a;
    --text:#e6edf3; --muted:#9aa5b1; --accent:#3fb950; --warn:#d29922;
    --err:#f85149; --info:#58a6ff;
  }
  * { box-sizing: border-box; }
  html,body { margin:0; padding:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    font-size:15px; line-height:1.4; -webkit-text-size-adjust:100%; }
  header { display:flex; justify-content:space-between; align-items:center;
    padding:12px 14px; border-bottom:1px solid var(--border); gap:10px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:17px; font-weight:600; }
  .badges { display:flex; gap:6px; flex-wrap:wrap; }
  .badge { padding:3px 8px; border-radius:999px; font-size:12px;
    background:var(--panel-2); border:1px solid var(--border); color:var(--muted); }
  .badge.live { color:var(--info); }
  .badge.inflight { color:var(--warn); }
  main { padding:14px; max-width:1200px; margin:0 auto; }
  .summary { background:var(--panel); border:1px solid var(--border);
    border-radius:10px; padding:14px; margin-bottom:14px; }
  .summary-row { display:flex; flex-wrap:wrap; gap:16px; font-size:13px; color:var(--muted); }
  .summary-row b { color:var(--text); }
  .table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch;
    border:1px solid var(--border); border-radius:10px; background:var(--panel); }
  table { width:100%; border-collapse:collapse; min-width:820px; }
  th,td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--border);
    vertical-align:top; white-space:nowrap; font-size:14px; }
  th { position:sticky; top:0; background:var(--panel-2); color:var(--muted);
    font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  tr:last-child td { border-bottom:none; }
  tr.detail-row td { background:var(--panel-2); white-space:normal; font-size:12px;
    color:var(--muted); padding:10px 14px; }
  tr.detail-row pre { white-space:pre-wrap; font-size:11px; margin:4px 0 0; max-height:260px; overflow:auto; }
  .mono { font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace; }
  .offer { font-weight:700; color:var(--accent); font-variant-numeric:tabular-nums; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px;
    font-weight:600; text-transform:uppercase; letter-spacing:.03em; }
  .pill.blocked { background:rgba(248,81,73,.12); color:var(--err); border:1px solid rgba(248,81,73,.3); }
  .pill.account_required { background:rgba(210,153,34,.15); color:var(--warn); border:1px solid rgba(210,153,34,.3); }
  .pill.error   { background:rgba(248,81,73,.10); color:var(--err); border:1px solid rgba(248,81,73,.25); }
  .pill.running { background:rgba(88,166,255,.10); color:var(--info); border:1px solid rgba(88,166,255,.25); }
  .pill.ok      { background:rgba(63,185,80,.10); color:var(--accent); border:1px solid rgba(63,185,80,.25); }
  .pill.none    { background:var(--panel-2); color:var(--muted); border:1px solid var(--border); }
  .btn { background:var(--info); color:#0b1220; border:none; border-radius:6px;
    padding:4px 10px; font-size:12px; font-weight:600; cursor:pointer; }
  .btn[disabled] { opacity:.4; cursor:not-allowed; }
  .name-cell { max-width:220px; white-space:normal; }
  .expander { cursor:pointer; user-select:none; }
  footer { padding:18px 14px 30px; color:var(--muted); font-size:13px; border-top:1px solid var(--border); margin-top:14px; }
  footer a { color:var(--info); }
  @media (max-width:520px) {
    header h1 { font-size:15px; }
    main { padding:10px; }
    th,td { padding:8px 10px; font-size:13px; }
  }
</style>
</head><body>
<header>
  <h1>Car Offers &mdash; Panel</h1>
  <div class="badges">
    <span class="badge" id="active-badge">&mdash; active</span>
    <span class="badge inflight" id="inflight-badge">0 in flight</span>
    <span class="badge live" id="updated-badge">never updated</span>
  </div>
</header>
<main>
  <div class="summary" id="summary">Loading&hellip;</div>
  <div class="table-wrap">
    <table id="panel-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Consumer</th>
          <th>Last Carvana</th>
          <th>Last CarMax</th>
          <th>Last Driveway</th>
          <th>Last Ran</th>
          <th>Next Scheduled</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="panel-body">
        <tr><td colspan="9" style="padding:24px;text-align:center;color:var(--muted);">Loading&hellip;</td></tr>
      </tbody>
    </table>
  </div>
</main>
<footer>
  <div>See all runs: <a href="compare">/compare</a></div>
</footer>
<script>
(function(){
  var isPreview = window.location.pathname.indexOf('/preview/') !== -1;
  var apiPanel = isPreview ? '/car-offers/preview/api/panel' : '/car-offers/api/panel';
  var apiRunOne = function (id) {
    return isPreview ? '/car-offers/preview/api/panel/run/' + id : '/car-offers/api/panel/run/' + id;
  };
  var summary = document.getElementById('summary');
  var body = document.getElementById('panel-body');
  var activeBadge = document.getElementById('active-badge');
  var inflightBadge = document.getElementById('inflight-badge');
  var updatedBadge = document.getElementById('updated-badge');

  function escapeHtml(s){ if(s==null) return ''; return String(s).replace(/[&<>"']/g,function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; }); }
  function fmtUsd(n){ if(n==null||isNaN(n)) return null; try { return '$' + Number(n).toLocaleString('en-US'); } catch(_) { return '$' + n; } }
  function fmtAt(iso){ if(!iso) return ''; var d = new Date(iso); if(isNaN(d.getTime())) return iso;
    var pad = function(n){ return n<10?'0'+n:''+n; };
    return pad(d.getMonth()+1) + '/' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function timeSince(iso){ if(!iso) return 'never'; var ms = Date.now() - new Date(iso).getTime(); if(ms<0) return fmtAt(iso);
    var s=Math.floor(ms/1000); if(s<60) return s+'s ago'; var m=Math.floor(s/60); if(m<60) return m+'m ago';
    var h=Math.floor(m/60); if(h<48) return h+'h ago'; return Math.floor(h/24)+'d ago';
  }
  function siteCell(r){
    if(!r) return '<span class="pill none">&mdash;</span>';
    var status=(r.status||'').toLowerCase();
    if(status==='ok' && r.offer_usd!=null) return '<span class="offer">' + escapeHtml(fmtUsd(r.offer_usd)) + '</span>';
    var cls='pill '+(status||'none').replace(/[^a-z_]/g,'');
    return '<span class="'+cls+'">'+escapeHtml(status||'none').replace(/_/g,' ')+'</span>';
  }

  function renderRows(rows){
    if(!rows || !rows.length){ body.innerHTML = '<tr><td colspan="9" style="padding:24px;text-align:center;color:var(--muted);">No consumers yet. The panel has not been seeded.</td></tr>'; return; }
    var html = [];
    rows.forEach(function(row){
      var c = row.consumer || {};
      var L = row.latest || {};
      var label = (c.year||'') + ' ' + (c.make||'') + ' ' + (c.model||'');
      var statusLbl = (row.latest_panel_run && row.latest_panel_run.status) || '-';
      html.push(
        '<tr data-id="'+c.id+'">'+
        '<td class="mono">'+escapeHtml(c.id)+'</td>'+
        '<td class="name-cell"><b>'+escapeHtml(c.name||'')+'</b><br><span class="mono" style="color:var(--muted);font-size:11px;">'+escapeHtml(label.trim())+' &middot; '+escapeHtml(c.home_zip||'')+' &middot; '+escapeHtml(c.vin||'')+'</span></td>'+
        '<td>'+siteCell(L.carvana)+'</td>'+
        '<td>'+siteCell(L.carmax)+'</td>'+
        '<td>'+siteCell(L.driveway)+'</td>'+
        '<td class="mono" style="color:var(--muted);">'+escapeHtml(timeSince(row.last_ran_at))+'</td>'+
        '<td class="mono" style="color:var(--muted);">'+escapeHtml(fmtAt(row.next_scheduled_at))+'</td>'+
        '<td><span class="pill '+statusLbl+'">'+escapeHtml(statusLbl)+'</span></td>'+
        '<td><button class="btn" data-run="'+c.id+'" title="Run now (ad-hoc)">Run</button> <button class="btn expander" data-expand="'+c.id+'" style="background:var(--panel-2);color:var(--text);">&plus;</button></td>'+
        '</tr>'+
        '<tr class="detail-row" id="detail-'+c.id+'" style="display:none;"><td colspan="9"><div><b>wizard_log (latest, Carvana):</b><pre>'+escapeHtml((L.carvana && L.carvana.wizard_log && JSON.stringify(L.carvana.wizard_log,null,2)) || '(none)')+'</pre></div><div><b>CarMax:</b><pre>'+escapeHtml((L.carmax && L.carmax.wizard_log && JSON.stringify(L.carmax.wizard_log,null,2)) || '(none)')+'</pre></div><div><b>Driveway:</b><pre>'+escapeHtml((L.driveway && L.driveway.wizard_log && JSON.stringify(L.driveway.wizard_log,null,2)) || '(none)')+'</pre></div></td></tr>'
      );
    });
    body.innerHTML = html.join('');

    body.querySelectorAll('button[data-run]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var id = btn.getAttribute('data-run');
        btn.disabled = true; btn.textContent='...';
        fetch(apiRunOne(id), { method:'POST', headers:{'Accept':'application/json'} })
          .then(function(r){ return r.json().catch(function(){return{};}); })
          .then(function(){ btn.textContent='queued'; setTimeout(refresh, 1000); })
          .catch(function(e){ btn.textContent='err'; console.error(e); });
      });
    });
    body.querySelectorAll('button[data-expand]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var id = btn.getAttribute('data-expand');
        var el = document.getElementById('detail-'+id);
        if(el) el.style.display = (el.style.display === 'none' ? '' : 'none');
      });
    });
  }

  function renderSummary(data){
    var active = data && data.active_count != null ? data.active_count : 0;
    var inflight = data && data.in_flight != null ? data.in_flight : 0;
    activeBadge.textContent = active + ' active';
    inflightBadge.textContent = inflight + ' in flight';
    summary.innerHTML = '<div class="summary-row">' +
      '<div><b>' + active + '</b> active consumers</div>' +
      '<div>Last run: <b>' + escapeHtml(timeSince(data && data.last_ran_at)) + '</b></div>' +
      '<div>Next scheduled: <b>' + escapeHtml(fmtAt(data && data.next_scheduled_at)) + ' UTC</b></div>' +
      '<div>In flight: <b>' + inflight + '</b></div>' +
      '</div>';
  }

  function refresh(){
    fetch(apiPanel, { headers:{'Accept':'application/json'} })
      .then(function(r){ return r.json(); })
      .then(function(data){
        renderSummary(data||{});
        renderRows((data && data.rows) || []);
        updatedBadge.textContent = 'updated ' + new Date().toLocaleTimeString();
      })
      .catch(function(err){
        summary.textContent = 'Could not load panel: ' + (err && err.message || 'error');
      });
  }

  refresh();
  setInterval(refresh, 30000);
})();
</script>
</body></html>`);
});

/**
 * GET /compare
 * Read-only, mobile-first side-by-side view of recent comparison runs.
 * Single HTML page, no external JS deps. Polls /api/compare-all every 30s.
 */
app.get('/compare', (_req, res) => {
  res.set('Content-Type', 'text/html; charset=utf-8');
  res.send(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Car Offers &mdash; Compare</title>
<style>
  :root {
    --bg: #0e1116;
    --panel: #161b22;
    --panel-2: #1c232c;
    --border: #2a313a;
    --text: #e6edf3;
    --muted: #9aa5b1;
    --accent: #3fb950;
    --warn: #d29922;
    --err: #f85149;
    --info: #58a6ff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 15px; line-height: 1.4; -webkit-text-size-adjust: 100%;
  }
  header { display: flex; justify-content: space-between; align-items: center;
    padding: 12px 14px; border-bottom: 1px solid var(--border); gap: 10px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 17px; font-weight: 600; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .badge { display: inline-block; padding: 3px 8px; border-radius: 999px;
    font-size: 12px; background: var(--panel-2); border: 1px solid var(--border); color: var(--muted); }
  .badge.live { color: var(--info); }
  .badge.inflight { color: var(--warn); }
  main { padding: 14px; max-width: 1200px; margin: 0 auto; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px; margin-bottom: 14px; }
  form.card { display: grid; grid-template-columns: 1fr; gap: 10px; }
  label { display: flex; flex-direction: column; font-size: 13px; color: var(--muted); gap: 4px; }
  input, select, button {
    font: inherit; color: var(--text); background: var(--panel-2);
    border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
    -webkit-appearance: none; appearance: none;
  }
  input:focus, select:focus { outline: 2px solid var(--info); outline-offset: 0; }
  button {
    background: var(--info); color: #0b1220; border-color: var(--info);
    font-weight: 600; cursor: pointer; padding: 12px 14px;
  }
  button[disabled] { opacity: 0.5; cursor: not-allowed; }
  .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  h2 { font-size: 15px; margin: 18px 0 8px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
  .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch;
    border: 1px solid var(--border); border-radius: 10px; background: var(--panel); }
  table { width: 100%; border-collapse: collapse; min-width: 820px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; white-space: nowrap; font-size: 14px; }
  th { position: sticky; top: 0; background: var(--panel-2); color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
  tr:last-child td { border-bottom: none; }
  .mono { font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace; }
  .offer { font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
  .pill.blocked       { background: rgba(248,81,73,.12); color: var(--err); border: 1px solid rgba(248,81,73,.3); }
  .pill.account_required { background: rgba(210,153,34,.15); color: var(--warn); border: 1px solid rgba(210,153,34,.3); }
  .pill.error         { background: rgba(248,81,73,.10); color: var(--err); border: 1px solid rgba(248,81,73,.25); }
  .pill.pending       { background: rgba(88,166,255,.10); color: var(--info); border: 1px solid rgba(88,166,255,.25); }
  .pill.ok            { background: rgba(63,185,80,.10); color: var(--accent); border: 1px solid rgba(63,185,80,.25); }
  .pill.none          { background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
  .empty { padding: 24px; text-align: center; color: var(--muted); }
  .notes { font-size: 12px; color: var(--muted); white-space: normal; max-width: 280px; }
  footer { padding: 18px 14px 30px; color: var(--muted); font-size: 13px; line-height: 1.7; border-top: 1px solid var(--border); margin-top: 14px; }
  footer div { word-break: break-all; }
  @media (max-width: 520px) {
    .row-2 { grid-template-columns: 1fr; }
    header h1 { font-size: 15px; }
    main { padding: 10px; }
    th, td { padding: 8px 10px; font-size: 13px; }
  }
</style>
</head>
<body>
<header>
  <h1>Car Offers &mdash; Compare</h1>
  <div class="badges">
    <span class="badge inflight" id="inflight-badge" title="Requests in flight">0 in flight</span>
    <span class="badge" id="total-badge" title="Total runs in DB">0 runs</span>
    <span class="badge live" id="updated-badge">never updated</span>
  </div>
</header>

<main>
  <form class="card" id="run-form" autocomplete="off">
    <label>VIN
      <input type="text" id="vin" name="vin" maxlength="17" required placeholder="17-char VIN" style="text-transform:uppercase">
    </label>
    <div class="row-2">
      <label>Mileage
        <input type="number" id="mileage" name="mileage" min="0" max="400000" required placeholder="48000">
      </label>
      <label>Zip
        <input type="text" id="zip" name="zip" maxlength="5" pattern="[0-9]{5}" required placeholder="06880">
      </label>
    </div>
    <label>Condition
      <select id="condition" name="condition">
        <option value="excellent">Excellent</option>
        <option value="good" selected>Good</option>
        <option value="fair">Fair</option>
        <option value="poor">Poor</option>
      </select>
    </label>
    <button type="submit" id="submit-btn">Run on all 3</button>
    <div id="form-note" class="notes" style="min-height:18px"></div>
  </form>

  <h2>Recent Runs</h2>
  <div class="table-wrap" id="table-wrap">
    <table id="runs-table">
      <thead>
        <tr>
          <th>Ran At</th>
          <th>VIN</th>
          <th>Mileage</th>
          <th>Zip</th>
          <th>Condition</th>
          <th>Carvana</th>
          <th>CarMax</th>
          <th>Driveway</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody id="runs-body">
        <tr><td colspan="9" class="empty">Loading&hellip;</td></tr>
      </tbody>
    </table>
  </div>
</main>

<footer>
  <div>Live:  http://159.223.127.125/car-offers/ </div>
  <div>Preview:  http://159.223.127.125/car-offers/preview/compare </div>
</footer>

<script>
(function () {
  var API_COMPARE_ALL = '/car-offers/api/compare-all?limit=50';
  var API_COMPARE_ALL_PREVIEW = '/car-offers/preview/api/compare-all?limit=50';
  var API_QUOTE_ALL = '/car-offers/api/quote-all';
  var API_QUOTE_ALL_PREVIEW = '/car-offers/preview/api/quote-all';

  // Detect whether we're being served from /preview/ so relative API calls
  // stay on the same deployment slot.
  var isPreview = window.location.pathname.indexOf('/preview/') !== -1;
  var apiCompareAll = isPreview ? API_COMPARE_ALL_PREVIEW : API_COMPARE_ALL;
  var apiQuoteAll = isPreview ? API_QUOTE_ALL_PREVIEW : API_QUOTE_ALL;

  var inflight = 0;
  var inflightBadge = document.getElementById('inflight-badge');
  var totalBadge = document.getElementById('total-badge');
  var updatedBadge = document.getElementById('updated-badge');
  var tbody = document.getElementById('runs-body');
  var form = document.getElementById('run-form');
  var btn = document.getElementById('submit-btn');
  var note = document.getElementById('form-note');

  function fmtInflight() {
    inflightBadge.textContent = inflight + ' in flight';
    inflightBadge.style.display = inflight > 0 ? '' : 'inline-block';
  }
  function fmtUsd(n) {
    if (n == null || isNaN(n)) return null;
    try { return '$' + Number(n).toLocaleString('en-US'); } catch (_) { return '$' + n; }
  }
  function fmtAt(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    // Mobile-friendly: MM/DD HH:MM
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function siteCell(site) {
    if (!site) return '<span class="pill none">&mdash;</span>';
    var status = (site.status || '').toLowerCase();
    if (status === 'ok' && site.offer_usd != null) {
      var usd = fmtUsd(site.offer_usd);
      return '<span class="offer">' + escapeHtml(usd) + '</span>';
    }
    var cls = 'pill';
    if (status === 'blocked') cls += ' blocked';
    else if (status === 'account_required') cls += ' account_required';
    else if (status === 'error') cls += ' error';
    else if (status === 'pending' || status === 'running') cls += ' pending';
    else if (status === 'ok') cls += ' ok';
    else cls += ' none';
    var label = status ? status.replace(/_/g, ' ') : 'unknown';
    return '<span class="' + cls + '">' + escapeHtml(label) + '</span>';
  }
  function notesCell(run) {
    // Collect any non-ok status labels as a short rollup, or show offer_expires if any.
    var bits = [];
    ['carvana', 'carmax', 'driveway'].forEach(function (s) {
      var r = run[s];
      if (!r) return;
      if (r.status && r.status !== 'ok') {
        bits.push(s + ': ' + r.status);
      } else if (r.offer_expires) {
        bits.push(s + ' exp ' + r.offer_expires);
      }
    });
    return escapeHtml(bits.join(' &middot; ')).replace(/&amp;middot;/g, '&middot;');
  }

  function renderRuns(data) {
    var runs = (data && data.runs) || [];
    if (typeof data.total_runs === 'number') {
      totalBadge.textContent = data.total_runs + ' runs';
    }
    if (!runs.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty">No runs yet &mdash; submit a VIN above to start.</td></tr>';
      return;
    }
    var html = runs.map(function (r) {
      return '<tr>' +
        '<td class="mono">' + escapeHtml(fmtAt(r.ran_at)) + '</td>' +
        '<td class="mono">' + escapeHtml(r.vin || '') + '</td>' +
        '<td>' + (r.mileage == null ? '' : Number(r.mileage).toLocaleString('en-US')) + '</td>' +
        '<td>' + escapeHtml(r.zip || '') + '</td>' +
        '<td>' + escapeHtml(r.condition || '') + '</td>' +
        '<td>' + siteCell(r.carvana) + '</td>' +
        '<td>' + siteCell(r.carmax) + '</td>' +
        '<td>' + siteCell(r.driveway) + '</td>' +
        '<td class="notes">' + notesCell(r) + '</td>' +
      '</tr>';
    }).join('');
    tbody.innerHTML = html;
  }

  function refresh() {
    fetch(apiCompareAll, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderRuns(data || {});
        var now = new Date();
        updatedBadge.textContent = 'updated ' + now.toLocaleTimeString();
      })
      .catch(function (err) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty">Could not load runs: ' + escapeHtml(err && err.message || 'error') + '</td></tr>';
      });
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var body = {
      vin: (document.getElementById('vin').value || '').trim().toUpperCase(),
      mileage: document.getElementById('mileage').value,
      zip: (document.getElementById('zip').value || '').trim(),
      condition: document.getElementById('condition').value,
    };
    if (!body.vin || body.vin.length !== 17) {
      note.textContent = 'VIN must be 17 characters.';
      return;
    }
    if (!body.mileage) {
      note.textContent = 'Mileage required.';
      return;
    }
    if (!/^[0-9]{5}$/.test(body.zip)) {
      note.textContent = 'Zip must be 5 digits.';
      return;
    }
    note.textContent = 'Submitted; Carvana/CarMax/Driveway run sequentially (2-5 min total). Table auto-refreshes.';
    btn.disabled = true;
    inflight++; fmtInflight();
    fetch(apiQuoteAll, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        note.textContent = 'Run complete' + (data && data.run_id ? ' (' + data.run_id + ')' : '') + '. See table below.';
      })
      .catch(function (err) {
        note.textContent = 'Run failed: ' + (err && err.message || 'error');
      })
      .then(function () {
        inflight = Math.max(0, inflight - 1); fmtInflight();
        btn.disabled = false;
        refresh();
      });
    // Also refresh now so the user sees previous runs update as this runs.
    refresh();
  });

  fmtInflight();
  refresh();
  setInterval(refresh, 30000);
})();
</script>
</body>
</html>`);
});

// --- Start server ---
const port = config.PORT;
app.listen(port, '0.0.0.0', () => {
  console.log(`Car Offer Tool running on http://0.0.0.0:${port}`);

  // Run full diagnostics 5 seconds after startup
  setTimeout(async () => {
    try { config.reloadConfig(); } catch (_) {}
    console.log(`[startup] Config: host=${config.PROXY_HOST} port=${config.PROXY_PORT} user=${config.PROXY_USER} pass=${config.PROXY_PASS ? config.PROXY_PASS.length + ' chars' : 'NOT SET'}`);

    console.log('[startup] Running full curl-based diagnostics...');
    await runFullDiagnostic();

    // If curl proxy works, skip Playwright proxy test and go straight to Carvana.
    // Reason: curl with geo-targeting on port 7000 works perfectly (US residential IPs),
    // but Playwright's CONNECT-based proxy auth gets "Access denied" on the test endpoint.
    // The actual Carvana flow uses launchBrowser() which sets proxy at launch — different
    // auth path that should work. No point blocking on a test that doesn't reflect reality.
    if (selfTest.proxyResult && selfTest.proxyResult.ok) {
      // Check if a recent Carvana result already exists (avoid hammering on rapid redeploys)
      let shouldRun = true;
      // Kill-switch: SKIP_STARTUP_AUTORUN=1 env var disables the startup
      // Carvana quote entirely. Used during manual wizard debugging so the
      // auto-run doesn't contend for the shared Chromium profile with whatever
      // wizard the developer kicked off via POST /api/<site>.
      if (process.env.SKIP_STARTUP_AUTORUN === '1' || process.env.SKIP_STARTUP_AUTORUN === 'true') {
        console.log('[startup] SKIP_STARTUP_AUTORUN set — skipping Carvana auto-run');
        shouldRun = false;
      }
      try {
        const resultsPath = path.join(__dirname, 'startup-results.json');
        if (fs.existsSync(resultsPath)) {
          const existing = JSON.parse(fs.readFileSync(resultsPath, 'utf8'));
          if (existing.lastCarvanaRun && existing.lastCarvanaRun.completed_at) {
            const age = Date.now() - new Date(existing.lastCarvanaRun.completed_at).getTime();
            if (age < 10 * 60 * 1000) { // Less than 10 minutes old
              console.log(`[startup] Recent Carvana result exists (${Math.round(age/1000)}s old). Skipping auto-run.`);
              selfTest.lastCarvanaRun = existing.lastCarvanaRun;
              shouldRun = false;
            }
          }
        }
      } catch { /* no existing results, run anyway */ }

      if (shouldRun) {
        console.log('[startup] Curl proxy works (US IP confirmed). Running Carvana flow...');
        // Wait 30s before starting to let the proxy session stabilize
        // and avoid looking like a rapid bot restart
        await new Promise(r => setTimeout(r, 30000));
        try {
          const { getCarvanaOffer } = require('./lib/carvana');
          const result = await getCarvanaOffer({
            vin: '1HGCV2F9XNA008352',
            mileage: '48000',
            zip: '06880',
            email: config.PROJECT_EMAIL || 'caroffers.tool@gmail.com',
          });
          selfTest.lastCarvanaRun = {
            ...result,
            vin: '1HGCV2F9XNA008352',
            mileage: '48000',
            zip: '06880',
            completed_at: new Date().toISOString(),
          };
          // Log a compact summary that will appear in status.json's 3-line recent_log
          const r = selfTest.lastCarvanaRun;
          const summary = r.offer
            ? `OFFER=${r.offer} VIN=${r.vin}`
            : `ERROR=${(r.error || 'unknown').substring(0, 80)}`;
          const wSteps = (r.wizardLog || []).length;
          const method = (r.details && r.details.launchMethod) || 'unknown';
          console.log(`[CARVANA-RESULT] ${summary} browser=${method} steps=${wSteps}`);
          // Log first 3 wizard steps for diagnostics
          if (r.wizardLog && r.wizardLog.length > 0) {
            console.log(`[CARVANA-LOG] ${r.wizardLog.slice(0, 5).join(' | ')}`);
          }
        } catch (err) {
          selfTest.lastCarvanaRun = {
            error: err.message,
            vin: '1HGCV2F9XNA008352',
            completed_at: new Date().toISOString(),
          };
          console.error('[startup] Carvana error:', err.message);
        }
      }
      saveResults();
    }
  }, 5000);
});
