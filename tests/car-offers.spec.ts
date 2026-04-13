import { test, expect } from '@playwright/test';

/**
 * Car-offers smoke + contract tests.
 *
 * These run against the deployed droplet (BASE_URL from playwright.config).
 * The service is preview-first (port 3101 via /car-offers/preview/) and
 * live (port 3100 via /car-offers/). Both should answer 200 and expose
 * the same shape; QA should not require a real Carvana offer because that
 * flow is inherently flaky (CF Turnstile).
 */

test.describe('Car-offers UI shell', () => {
  test('live /car-offers/ serves the main UI or the setup page', async ({ page }) => {
    const response = await page.goto('/car-offers/');
    expect(response?.status(), 'live root should answer 200').toBe(200);
    const heading = await page.locator('h1').first().textContent();
    // Configured instance shows "Car Offer Tool"; unconfigured redirects to Setup.
    expect(
      heading === 'Car Offer Tool' || heading === 'Server Setup',
      `unexpected heading: ${heading}`,
    ).toBeTruthy();
  });

  test('preview /car-offers/preview/ serves the main UI or the setup page', async ({ page, request }) => {
    const headResp = await request.get('/car-offers/preview/');
    if (headResp.status() === 404) {
      test.skip(true, 'preview URL not wired on this droplet yet');
    }
    const response = await page.goto('/car-offers/preview/');
    expect(response?.status()).toBe(200);
    const heading = await page.locator('h1').first().textContent();
    expect(
      heading === 'Car Offer Tool' || heading === 'Server Setup',
      `unexpected heading: ${heading}`,
    ).toBeTruthy();
  });

  test('car-offers page has no JS errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/car-offers/');
    expect(errors, 'car-offers should have no JS errors').toHaveLength(0);
  });
});

test.describe('Car-offers API contract', () => {
  test('GET /car-offers/api/last-run returns well-formed JSON', async ({ request }) => {
    const resp = await request.get('/car-offers/api/last-run');
    expect(resp.ok(), 'last-run should be 200').toBeTruthy();
    const body = await resp.json();
    // Either {status:'pending', message:...} (no run yet) or a full result.
    const okShape =
      (body.status === 'pending' && typeof body.message === 'string') ||
      (typeof body.completed_at === 'string' && (body.offer || body.error));
    expect(okShape, `unexpected last-run shape: ${JSON.stringify(body).slice(0, 300)}`).toBeTruthy();
  });

  test('GET /car-offers/api/status returns diagnostic JSON', async ({ request }) => {
    const resp = await request.get('/car-offers/api/status');
    if (resp.status() === 404) {
      test.skip(true, 'status endpoint not present on this build');
    }
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(typeof body).toBe('object');
  });

  test('POST /car-offers/api/carvana returns valid shape (offer or error, never crash)', async ({ request }) => {
    // Dry run: hit the flow with a known-good VIN and minimal fields.
    // We don't require a real offer — CI can't reliably pass Turnstile —
    // but the server MUST return one of the documented shapes, not 500.
    const resp = await request.post('/car-offers/api/carvana', {
      data: { vin: '1HGCV2F9XNA008352', mileage: '48000', zip: '06880' },
      timeout: 600_000,
    });
    // 200 with JSON body, OR 503 if dependencies aren't loaded yet.
    expect(
      [200, 503].includes(resp.status()),
      `unexpected status ${resp.status()}`,
    ).toBeTruthy();
    if (resp.status() === 200) {
      const body = await resp.json();
      // Must be either { offer, details } or { error, ... }; never NaN/empty.
      const okShape = (typeof body.offer === 'string' && body.offer.startsWith('$')) ||
        (typeof body.error === 'string' && body.error.length > 0);
      expect(okShape, `bad shape: ${JSON.stringify(body).slice(0, 300)}`).toBeTruthy();
    }
  });
});

test.describe('Car-offers comparison (CarMax + Driveway + /api/compare + /api/quote-all)', () => {
  test('GET /api/compare/:vin with unknown VIN returns well-formed empty (never 500)', async ({ request }) => {
    const resp = await request.get('/car-offers/api/compare/NONEXISTENTVIN123');
    expect(resp.status(), 'compare endpoint must not 500 on missing VIN').toBe(200);
    const body = await resp.json();
    expect(typeof body).toBe('object');
    // Shape: { vin, carvana, carmax, driveway, run_id, ran_at }
    expect(body).toHaveProperty('vin');
    expect(body).toHaveProperty('carvana');
    expect(body).toHaveProperty('carmax');
    expect(body).toHaveProperty('driveway');
    expect(body).toHaveProperty('run_id');
    expect(body).toHaveProperty('ran_at');
    // All three site rows should be null (no data yet)
    expect(body.carvana === null || typeof body.carvana === 'object').toBeTruthy();
    expect(body.carmax === null || typeof body.carmax === 'object').toBeTruthy();
    expect(body.driveway === null || typeof body.driveway === 'object').toBeTruthy();
  });

  test('GET /api/runs returns a runs array', async ({ request }) => {
    const resp = await request.get('/car-offers/api/runs');
    // This endpoint is new — tolerate a 404 on older instances.
    if (resp.status() === 404) test.skip(true, '/api/runs not on this build');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body.runs)).toBeTruthy();
  });

  test('POST /api/quote-all with bad VIN returns 400 with error message', async ({ request }) => {
    const resp = await request.post('/car-offers/api/quote-all', {
      data: { vin: 'bad', mileage: '48000', zip: '06880' },
    });
    // 400 (validation) or 404 (old build) — not 500
    if (resp.status() === 404) test.skip(true, '/api/quote-all not on this build');
    expect(resp.status()).toBe(400);
    const body = await resp.json();
    expect(typeof body.error).toBe('string');
  });

  test('POST /api/carmax with bad input returns 400, not 500', async ({ request }) => {
    const resp = await request.post('/car-offers/api/carmax', {
      data: { vin: 'bad', mileage: 'x', zip: 'y' },
    });
    if (resp.status() === 404) test.skip(true, '/api/carmax not on this build');
    expect(resp.status()).toBe(400);
  });

  test('POST /api/driveway with bad input returns 400, not 500', async ({ request }) => {
    const resp = await request.post('/car-offers/api/driveway', {
      data: { vin: 'bad', mileage: 'x', zip: 'y' },
    });
    if (resp.status() === 404) test.skip(true, '/api/driveway not on this build');
    expect(resp.status()).toBe(400);
  });

  test('dashboard renders the "Compare all 3 buyers" card', async ({ page }) => {
    await page.goto('/car-offers/dashboard');
    const heading = page.locator('h2', { hasText: 'Compare all 3 buyers' });
    if (await heading.count() === 0) test.skip(true, 'compare card not on this build');
    await expect(heading).toBeVisible();
    await expect(page.locator('#cmpVin')).toBeVisible();
    await expect(page.locator('#cmpCondition')).toBeVisible();
    await expect(page.locator('#cmpBtn')).toBeVisible();
  });
});

test.describe('Car-offers consumer panel', () => {
  test('GET /panel renders the panel HTML', async ({ page, request }) => {
    const headResp = await request.get('/car-offers/panel');
    if (headResp.status() === 404) test.skip(true, '/panel not on this build');
    await page.goto('/car-offers/panel');
    await expect(page.locator('h1', { hasText: 'Panel' })).toBeVisible();
    await expect(page.locator('table')).toBeVisible();
  });

  test('GET /api/panel returns well-formed JSON', async ({ request }) => {
    const resp = await request.get('/car-offers/api/panel');
    if (resp.status() === 404) test.skip(true, '/api/panel not on this build');
    expect([200, 503]).toContain(resp.status());
    if (resp.status() === 200) {
      const body = await resp.json();
      expect(body).toHaveProperty('active_count');
      expect(body).toHaveProperty('in_flight');
      expect(body).toHaveProperty('rows');
      expect(Array.isArray(body.rows)).toBeTruthy();
    }
  });

  test('POST /api/panel/run/:id with bad id returns 400', async ({ request }) => {
    const resp = await request.post('/car-offers/api/panel/run/0');
    if (resp.status() === 404) test.skip(true, '/api/panel/run/:id not on this build');
    expect(resp.status()).toBe(400);
  });

  test('POST /api/panel/seed is idempotent (409 or 200 after first)', async ({ request }) => {
    // First seed (may be 200 OK or 409 if already seeded). Second must be 409.
    const resp1 = await request.post('/car-offers/api/panel/seed', { data: {} });
    if (resp1.status() === 404) test.skip(true, '/api/panel/seed not on this build');
    expect([200, 409, 503]).toContain(resp1.status());
    if (resp1.status() === 200 || resp1.status() === 409) {
      const resp2 = await request.post('/car-offers/api/panel/seed', { data: {} });
      expect(resp2.status()).toBe(409);
    }
  });
});

test.describe('Car-offers security', () => {
  test('.env is not served', async ({ request }) => {
    const resp = await request.get('/car-offers/.env');
    expect([403, 404]).toContain(resp.status());
  });

  test('startup-results.json does not leak secrets', async ({ request }) => {
    const resp = await request.get('/car-offers/startup-results.json');
    if (resp.ok()) {
      const body = await resp.text();
      expect(body, 'should not include PROXY_PASS').not.toContain('PROXY_PASS=');
      // The only credential field, if present, should be truncated/redacted.
    }
  });
});
