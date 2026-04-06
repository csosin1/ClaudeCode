# Change Log
# Webhook test 1775397948

## 2026-04-06 Car Offers: Dashboard + Auto-Run + Self-Test
- What was built: Added dashboard page, startup proxy self-test, and auto-run endpoint to car-offers
- Files modified:
  - `car-offers/server.js` — Added `/dashboard` (status page with one-tap actions), `/api/status` (JSON health), `/api/auto-run` (triggers test VIN), `/api/retest-proxy`, startup self-test
- Tests added: None (infrastructure chat owns QA tests)
- What the dashboard shows: proxy health (IP, country, pass/fail), one-tap "Get Carvana Offer" for test VIN, auto-polling for results
- How to use: Visit http://159.223.127.125/car-offers/dashboard from phone

### INFRASTRUCTURE CHANGE PROPOSALS (for infrastructure chat)

**Proposal 1: Add QA test for car-offers dashboard**
Add to `tests/qa-smoke.spec.ts`:
```typescript
test.describe('Car Offers Dashboard', () => {
  test('dashboard loads', async ({ page }) => {
    await page.goto('/car-offers/dashboard');
    await expect(page.locator('h1')).toContainText('Car Offers Dashboard');
  });
  test('status API returns JSON', async ({ page }) => {
    const resp = await page.request.get('/car-offers/api/status');
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.service).toBeTruthy();
    expect(data.proxy).toBeTruthy();
  });
});
```

**Proposal 2: Add car-offers error log to diagnostics**
In `deploy/auto_deploy_general.sh`, add to the diagnostics step:
```bash
echo "  \"car_offers_error_log\": \"$(tail -5 /var/log/car-offers/error.log 2>/dev/null | tr '\n' ' ' || echo 'no log')\","
```
This would let us see recent server errors from debug.json.

**Proposal 3: npm install on every deploy (not just first time)**
Currently the deploy script only runs `npm install` if `node_modules/express` is missing. This means new dependencies (like `playwright` which was added later) don't get installed on redeploy. Change the condition to check `package.json` mtime:
```bash
# npm install if package.json is newer than node_modules
if [ "$REPO_DIR/car-offers/package.json" -nt /opt/car-offers/node_modules/.package-lock.json ] || [ ! -d /opt/car-offers/node_modules/express ]; then
    echo "$(date): npm install for car-offers..." >> "$LOG"
    cd /opt/car-offers && "$NPM_BIN" install --production >> "$LOG" 2>&1
fi
```

---

## 2026-04-05 Goal 1: Carvana Offer Automation
- What was built: Full Carvana "Sell My Car" automation — stealth browser launcher, Carvana flow script, CLI entry point, and Express web UI for iPhone use
- Files created:
  - `car-offers/package.json` — project manifest with playwright-extra, stealth plugin, dotenv, express
  - `car-offers/.env.example` — template for proxy, email, and port config
  - `car-offers/lib/config.js` — loads .env, exports all config vars
  - `car-offers/lib/browser.js` — stealth Chromium launcher with proxy support, humanDelay, humanType, randomMouseMove
  - `car-offers/lib/carvana.js` — full Carvana sell flow automation (VIN entry, mileage, conditions, zip, email, offer extraction)
  - `car-offers/index.js` — CLI: `node index.js carvana <vin> <mileage> <zip>`
  - `car-offers/server.js` — Express server with mobile-first HTML UI and POST /api/carvana endpoint
- Assumptions made:
  - Carvana form selectors are based on reasonable guesses (placeholder text, input types, button text) since we can't test from the sandbox. Multiple fallback selectors used for resilience.
  - Condition questions default to "Good" / "None" / "Clean" / "Excellent" options
  - The stealth plugin (puppeteer-extra-plugin-stealth) works with playwright-extra to bypass PerimeterX
  - A residential proxy is required — datacenter IPs will be blocked by Carvana
  - 120-second total timeout for the entire flow; 45-second wait for offer calculation
- Things the reviewer should check:
  - No credentials or emails are hardcoded — all come from .env
  - The HTML UI is mobile-first and works at 390px (dark theme, large touch targets)
  - Browser is always closed in finally blocks
  - CAPTCHA/block detection returns immediately without retrying
  - The offer extraction scans both specific selectors and full body text for dollar amounts

## 2026-04-05 Dice Roller App
- What was built: A single-file dice roller game with a Roll button, Unicode die face display, numeric result, and a rolling history of the last 10 rolls. Dark theme, mobile-first layout matching button-test style.
- Files modified:
  - `games/dice-roller/index.html` (new) — the complete app
  - `tests/qa-smoke.spec.ts` — added "Dice Roller App" test.describe block
- Tests added:
  - "page loads with correct heading" — verifies 200 status and h1 text
  - "clicking roll produces a number 1-6 and updates history" — clicks roll twice, verifies both results are 1-6, verifies history has at least 2 entries, logs values for debugging
  - "no JS errors on page" — loads page, clicks roll, checks for JS errors
- Assumptions:
  - Used Unicode dice characters (U+2680 to U+2685) for die faces — these render on all modern browsers/phones
  - History shows most recent roll first
  - History capped at 10 entries as specified
- Things the reviewer should check:
  - Unicode dice characters render correctly at the chosen font size
  - History items wrap properly on narrow (390px) screens
  - The #result element contains only the numeric value (no extra text) for test compatibility

## 2026-04-06 Gym Intelligence — Streamlit App Deployment

### What was built
Deploy the gym-intelligence Streamlit app to the droplet at `/gym-intelligence/`. The app provides Basic-Fit competitive tracking — European gym market data collection, AI classification, and quarterly analysis.

### Files modified
- `gym-intelligence/app.py` — Added docstring noting baseUrlPath configuration. Changed default page to "Setup" when ANTHROPIC_API_KEY is not yet configured (first-run UX: user lands on Setup page to enter their API key from their phone).

### Infrastructure changes needed (for infra chat)

---

#### A. `deploy/auto_deploy_general.sh` — Add gym-intelligence block

Insert the following **inside the `if [ "$LOCAL" != "$REMOTE" ]` block**, in **STEP 3: SERVER-SIDE PROJECTS**, after the car-offers block (before STEP 4):

```bash
    # --- gym-intelligence (Streamlit on port 8502) ---
    if [ -d "$REPO_DIR/gym-intelligence" ]; then
        mkdir -p /opt/gym-intelligence
        mkdir -p /var/log/gym-intelligence

        # Sync code (preserve venv, .env, *.db)
        rsync -a --delete \
            --exclude='venv' \
            --exclude='*.db' \
            --exclude='.env' \
            --exclude='__pycache__' \
            "$REPO_DIR/gym-intelligence/" /opt/gym-intelligence/

        # .env (one-time — user fills in API key via /gym-intelligence/ Setup page)
        if [ ! -f /opt/gym-intelligence/.env ]; then
            cat > /opt/gym-intelligence/.env << 'ENVEOF'
ANTHROPIC_API_KEY=
ENVEOF
        fi

        # One-time: Python venv + pip install
        if [ ! -f /opt/.gym-intelligence-setup ]; then
            echo "$(date): Setting up gym-intelligence venv..." >> "$LOG"

            # Find python3
            PYTHON_BIN=""
            for candidate in /usr/bin/python3 /usr/local/bin/python3; do
                if [ -x "$candidate" ]; then
                    PYTHON_BIN="$candidate"
                    break
                fi
            done
            if [ -z "$PYTHON_BIN" ]; then
                PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
            fi
            if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
                echo "$(date): python3 not found, installing..." >> "$LOG"
                apt-get update >> "$LOG" 2>&1
                apt-get install -y python3 python3-venv python3-pip >> "$LOG" 2>&1
                PYTHON_BIN="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"
            fi

            # Ensure python3-venv is available
            if ! "$PYTHON_BIN" -m venv --help > /dev/null 2>&1; then
                apt-get install -y python3-venv >> "$LOG" 2>&1
            fi

            # Create venv
            "$PYTHON_BIN" -m venv /opt/gym-intelligence/venv >> "$LOG" 2>&1

            # Install dependencies
            /opt/gym-intelligence/venv/bin/pip install --upgrade pip >> "$LOG" 2>&1
            /opt/gym-intelligence/venv/bin/pip install -r /opt/gym-intelligence/requirements.txt >> "$LOG" 2>&1

            # Verify streamlit installed
            if /opt/gym-intelligence/venv/bin/python -c "import streamlit" 2>/dev/null; then
                touch /opt/.gym-intelligence-setup
                echo "$(date): gym-intelligence venv setup complete." >> "$LOG"
            else
                echo "$(date): ERROR — gym-intelligence pip install failed (streamlit missing)." >> "$LOG"
            fi
        fi

        # systemd service (always rewrite to pick up changes)
        cat > /etc/systemd/system/gym-intelligence.service << 'SVCEOF'
[Unit]
Description=Gym Intelligence (Streamlit on port 8502)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/gym-intelligence
ExecStart=/opt/gym-intelligence/venv/bin/python -m streamlit run app.py --server.port=8502 --server.baseUrlPath=/gym-intelligence --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false
Restart=always
RestartSec=5
Environment=HOME=/root
StandardOutput=append:/var/log/gym-intelligence/app.log
StandardError=append:/var/log/gym-intelligence/app.log

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable gym-intelligence >> "$LOG" 2>&1
        systemctl restart gym-intelligence >> "$LOG" 2>&1
        echo "$(date): gym-intelligence service restarted." >> "$LOG"

        # Observability (one-time)
        if [ ! -f /opt/.gym_intelligence_logs_initialized ]; then
            touch /var/log/gym-intelligence/app.log
            cat > /etc/logrotate.d/gym-intelligence << 'LREOF'
/var/log/gym-intelligence/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    create 0644 root root
}
LREOF
            touch /opt/.gym_intelligence_logs_initialized
        fi
    fi
```

Also update the **STEP 4: LIGHTWEIGHT DIAGNOSTICS** block to include gym-intelligence status. Replace the existing diagnostics JSON block with:

```bash
    # === STEP 4: LIGHTWEIGHT DIAGNOSTICS ===
    mkdir -p /var/www/landing
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"node_version\": \"$("$NODE_BIN" --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"car_offers_status\": \"$(systemctl is-active car-offers 2>&1)\","
        echo "  \"port_3100\": $(ss -tlnp | grep -q ':3100' && echo true || echo false),"
        echo "  \"gym_intelligence_status\": \"$(systemctl is-active gym-intelligence 2>&1)\","
        echo "  \"port_8502\": $(ss -tlnp | grep -q ':8502' && echo true || echo false)"
        echo "}"
    } > /var/www/landing/debug.json
```

---

#### B. `deploy/update_nginx.sh` — Add gym-intelligence location block

Add the following **inside the `server {}` block**, after the car-offers location block and before the games block:

```nginx
    # Gym Intelligence — reverse proxy to Streamlit on port 8502
    location = /gym-intelligence { return 301 /gym-intelligence/; }
    location /gym-intelligence/ {
        proxy_pass http://127.0.0.1:8502/gym-intelligence/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;

        # WebSocket support (required by Streamlit)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Streamlit internal paths (health check, static assets, API)
    location /gym-intelligence/_stcore/ {
        proxy_pass http://127.0.0.1:8502/gym-intelligence/_stcore/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
```

---

#### C. `deploy/NGINX_VERSION` — Bump version

Change from `4` to `5`.

---

#### D. `deploy/landing.html` — Add Gym Intelligence card

Add the following card inside the `<div class="projects">` block, after the Games card:

```html
            <a class="card" href="/gym-intelligence/">
                <div class="card-title">Gym Intelligence</div>
                <div class="card-desc">Basic-Fit competitive tracker — European gym market data</div>
                <div class="card-path">/gym-intelligence/</div>
            </a>
```

Also update the landing page test expectation: the card count in `tests/qa-smoke.spec.ts` line 8 should change from `toHaveCount(2)` to `toHaveCount(3)`.

---

#### E. `tests/qa-smoke.spec.ts` — Add Gym Intelligence tests

Add the following test block:

```typescript
test.describe('Gym Intelligence', () => {
  test('page loads (setup or main)', async ({ page }) => {
    const response = await page.goto('/gym-intelligence/');
    expect(response?.status()).toBe(200);
    // Streamlit apps take a moment to render — wait for any content
    await page.waitForTimeout(3000);
    const body = await page.textContent('body');
    expect(
      body?.includes('Gym Intelligence') || body?.includes('Market Overview') || body?.includes('Setup'),
      'Page should contain app content'
    ).toBeTruthy();
  });

  test('no JS errors on gym-intelligence page', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/gym-intelligence/');
    await page.waitForTimeout(3000);
    expect(errors, 'Gym Intelligence should have no JS errors').toHaveLength(0);
  });
});
```

Also update the **Landing Page** test: change `toHaveCount(2)` to `toHaveCount(3)` on line 8 to account for the new card.

Also update the **Landing Page** `all project links return 200` test — it currently checks all card hrefs. The `/gym-intelligence/` link will need Streamlit to be running, so this test should pass if the deploy is working. No code change needed, but be aware it will fail if the service isn't up yet.

Also update the **Server Health** test `debug.json reports healthy server state` to check the new fields:

```typescript
    expect(body.gym_intelligence_status).toBe('active');
    expect(body.port_8502).toBe(true);
```

---

### Assumptions
- Port 8502 is available on the droplet (8501 is Streamlit's default, using 8502 to avoid conflicts)
- Python 3.10+ is available on Ubuntu 22.04 (default `python3` package)
- The SQLite database (`gyms.db`) is created in `/opt/gym-intelligence/` at runtime by `init_db()`
- Streamlit's `--server.enableCORS=false` and `--server.enableXsrfProtection=false` are needed when behind a reverse proxy
- `proxy_read_timeout` and `proxy_send_timeout` set to 86400 (24h) for WebSocket long-lived connections
- The `_stcore/` path handles Streamlit's internal static assets and WebSocket connections

### Things the reviewer should check
- The systemd ExecStart uses absolute path `/opt/gym-intelligence/venv/bin/python` (lesson learned: never rely on PATH)
- The setup flag `/opt/.gym-intelligence-setup` is only set AFTER verifying streamlit imports successfully (lesson learned: verify before flagging)
- The rsync excludes `venv/`, `*.db`, `.env` to avoid overwriting runtime state on redeploy
- The code sync happens EVERY deploy (not gated), only the venv setup is one-time gated
- WebSocket headers (`Upgrade`, `Connection`) are set in nginx for Streamlit live reload
- The `.env` template is created one-time with empty `ANTHROPIC_API_KEY=` — user fills it in via the Setup page in the app
- The app defaults to the Setup page when no API key is configured (first-run experience)

## 2026-04-06 Gym Intelligence — Streamlit to Flask Migration

### What was built
Replaced the Streamlit UI with a lightweight Flask app and single-page HTML frontend for fast mobile loading (sub-2-second page loads vs 30+ seconds with Streamlit). The Flask backend was already in place from a prior migration; this change adds the complete frontend template and cleans up requirements.

### Files modified
- `gym-intelligence/templates/index.html` (new) — Full single-page app with four tabs: Market Overview, Chain Explorer, Competitive Analysis, Admin. Built with vanilla JS, Chart.js for charts, Leaflet/OpenStreetMap for maps, and marked.js for markdown rendering. Mobile-first dark theme, touch-friendly controls, no frameworks.
- `gym-intelligence/requirements.txt` (updated) — Removed streamlit, plotly, pandas (no longer needed). Kept flask, anthropic, httpx, thefuzz.
- `CHANGES.md` (updated) — This entry.

### Frontend features
- **Market tab**: Country filter, min-locations slider, horizontal bar chart of market share, expandable chain detail cards
- **Chains tab**: Chain selector dropdown, profile card with classification/tier/rationale, line chart of locations over time by country, Leaflet map with location markers and popups, growth metric cards
- **Analysis tab**: Analysis selector, metadata cards, rendered markdown analysis text
- **Admin tab**: Status dashboard, background data refresh with live log polling, chain review forms with inline save, CSV export download, API key management

### Proposed infra changes (for infra chat)
- **systemd ExecStart**: Update from `python -m streamlit run app.py --server.port=8502 ...` to `/opt/gym-intelligence/venv/bin/python app.py`. The Flask app serves on port 8502 directly.
- **nginx**: WebSocket proxy headers (`Upgrade`, `Connection`) and the `_stcore/` location block are no longer needed (Flask does not use WebSockets). They can be removed for cleanliness but will not cause harm if left in place.
- **Setup verification**: Change the deploy script check from `import streamlit` to `import flask` to verify the venv was set up correctly.
- **pip install**: The new requirements.txt is much smaller; a `pip install -r requirements.txt` in the venv will pick up flask and drop streamlit/plotly/pandas.

### Proposed QA test update
- The existing test should still check that `/gym-intelligence/` returns 200
- Update expected body text: check for "Market" or "Gym Intelligence" (the page now renders instantly, no 3-second Streamlit wait needed)
- The "no JS errors" test should continue to pass
