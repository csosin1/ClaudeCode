import { test, expect } from '@playwright/test';

const VIEWPORTS = [
  { name: 'mobile',  width: 390,  height: 844 },
  { name: 'desktop', width: 1280, height: 800 },
];

// Preview is where Claude's code lands first; live is only promoted after
// explicit user acceptance. Both must serve a 200 and render the same core
// surfaces. Regression checks against live catch cases where a preview
// deploy quietly broke the promoted copy during a previous cycle.
const BASES = [
  { label: 'preview', path: '/gym-intelligence/preview/' },
  { label: 'live',    path: '/gym-intelligence/' },
];

for (const vp of VIEWPORTS) {
  for (const base of BASES) {
    test.describe(`Gym Intelligence ${base.label} (${vp.name} ${vp.width}x${vp.height})`, () => {
      test.use({ viewport: { width: vp.width, height: vp.height } });

      test('dashboard loads at 200', async ({ page }) => {
        const resp = await page.goto(base.path);
        expect(resp?.status()).toBe(200);
        // Tab bar is the top-level landmark on this dashboard.
        await expect(page.locator('.tab-bar')).toBeVisible();
        await expect(page.locator('button.tab-btn', { hasText: 'Market' })).toBeVisible();
      });

      test('chain table renders with at least 45 direct_competitor rows', async ({ page }) => {
        test.skip(base.label !== 'preview', 'testid-based rendering ships on preview only');
        await page.goto(base.path);
        const table = page.getByTestId('chain-table');
        await expect(table).toBeVisible({ timeout: 20000 });
        const directRows = page.getByTestId('direct-row');
        const count = await directRows.count();
        expect(count).toBeGreaterThanOrEqual(45);
      });

      test('Public pill renders when any chain has public ownership', async ({ page }) => {
        test.skip(base.label !== 'preview', 'Public pill ships on preview only');
        const apiResp = await page.request.get(
          base.path + 'api/chains-table?country=All%20Europe&show=all'
        );
        expect(apiResp.ok()).toBeTruthy();
        const rows = await apiResp.json();
        const hasPublic = rows.some((r: any) => r.ownership_type === 'public');
        if (!hasPublic) {
          test.info().annotations.push({
            type: 'skip-reason',
            description: 'No public-ownership chains in DB yet; pill cannot render.',
          });
          test.skip();
        }
        // Altafit (public + direct_competitor) appears in the default
        // competitors-only view, so no toggle needed. Unchecking would render
        // 31k rows and choke the browser.
        await page.goto(base.path);
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });
        await expect(page.getByTestId('public-pill').first()).toBeVisible({ timeout: 15000 });
      });

      test('competitors-only toggle defaults ON and filters table', async ({ page }) => {
        test.skip(base.label !== 'preview', 'toggle only ships on preview');
        await page.goto(base.path);
        const checkbox = page.locator('#competitors-only');
        await expect(checkbox).toBeChecked();
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });
        const onlyCount = await page.getByTestId('direct-row').count();
        expect(onlyCount).toBeGreaterThan(0);
        // Untoggle → API returns strictly more rows (non-competitors + others).
        // Don't assert DOM count because rendering 31k rows chokes the browser;
        // assert via the API payload instead.
        const allResp = await page.request.get(
          base.path + 'api/chains-table?country=All%20Europe&show=all'
        );
        const allRows = await allResp.json();
        expect(allRows.length).toBeGreaterThan(onlyCount);
      });

      test('overview shows Municipal competitors counter', async ({ page }) => {
        test.skip(base.label !== 'preview', 'counter ships on preview only');
        await page.goto(base.path);
        // Wait for table render to complete before checking counter text —
        // the counter is populated by loadTable() after the status API call.
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });
        const muni = page.getByTestId('municipal-counter');
        await expect(muni).toContainText('Municipal competitors:', { timeout: 15000 });
      });

      test('trend cell renders for at least one competitor', async ({ page }) => {
        test.skip(base.label !== 'preview', 'trend column ships on preview only');
        // Gate on snapshot-dates: if only one distinct snapshot_date exists
        // in the live DB (pre-backfill), the column is intentionally hidden
        // and there's nothing to assert. Skip rather than fail in that case.
        const datesResp = await page.request.get(base.path + 'api/snapshot-dates');
        expect(datesResp.ok()).toBeTruthy();
        const datesBody = await datesResp.json();
        const count = typeof datesBody.count === 'number'
          ? datesBody.count
          : (Array.isArray(datesBody) ? datesBody.length : 0);
        if (count < 2) {
          test.info().annotations.push({
            type: 'skip-reason',
            description: 'Backfill not yet run; only one snapshot_date present.',
          });
          test.skip();
        }
        await page.goto(base.path);
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });
        // At least one trend cell should move off the placeholder within 15s.
        await expect(async () => {
          const cells = page.getByTestId('trend-cell');
          const total = await cells.count();
          expect(total).toBeGreaterThan(0);
          let nonPlaceholder = 0;
          for (let i = 0; i < Math.min(total, 20); i++) {
            const txt = (await cells.nth(i).innerText()).trim();
            // Placeholder row renders as a lone em-dash "—". A populated cell
            // contains an arrow + pill with digits or "no change".
            if (txt && txt !== '—' && /\d|no change/.test(txt)) nonPlaceholder++;
          }
          expect(nonPlaceholder).toBeGreaterThanOrEqual(1);
        }).toPass({ timeout: 15000 });
      });

      test('trend column hidden when only one snapshot_date exists', async ({ page }) => {
        test.skip(base.label !== 'preview', 'trend column ships on preview only');
        // Stub snapshot-dates to simulate pre-backfill state.
        await page.route('**/api/snapshot-dates', async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ dates: ['2026-04-12'], count: 1 }),
          });
        });
        await page.goto(base.path);
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });
        // Notice banner must appear, trend cells must not.
        await expect(page.getByTestId('no-trend-notice')).toBeVisible();
        await expect(page.getByTestId('trend-cell')).toHaveCount(0);
      });

      test('YoY pill color matches sign', async ({ page }) => {
        test.skip(base.label !== 'preview', 'trend column ships on preview only');
        // Force the multi-snapshot code path so the trend column renders.
        await page.route('**/api/snapshot-dates', async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              dates: ['2025-04-12', '2026-04-12'],
              count: 2,
            }),
          });
        });

        // Return a different yoy_pct depending on a canonical_name match in
        // the query. We control three known competitors via URL inspection
        // and cycle green / red / gray.
        await page.route('**/api/chain-history*', async (route) => {
          const url = route.request().url();
          // URL-decode the `name=` param so we can compare cleanly.
          const m = url.match(/[?&]name=([^&]+)/);
          const name = m ? decodeURIComponent(m[1]) : '';
          // Build a 2-point series; yoy_pct is what the frontend styles on.
          let yoy_pct = 0;
          if (/green/i.test(name)) yoy_pct = 12;
          else if (/red/i.test(name)) yoy_pct = -8;
          else yoy_pct = 1.2;  // flat
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              canonical_name: name,
              country: 'All Europe',
              series: [
                { snapshot_date: '2025-04-12', location_count: 100 },
                { snapshot_date: '2026-04-12', location_count: 100 + yoy_pct },
              ],
              yoy_delta: yoy_pct,
              yoy_pct,
            }),
          });
        });

        // Also stub the chains-table call so we get exactly three rows with
        // predictable names. This removes the dependency on whatever the
        // live DB contains (and keeps the test fast).
        await page.route('**/api/chains-table*', async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify([
              { canonical_name: 'GreenChain', competitive_classification: 'direct_competitor', ownership_type: 'private', location_count: 300, region_count: 300 },
              { canonical_name: 'RedChain',   competitive_classification: 'direct_competitor', ownership_type: 'private', location_count: 200, region_count: 200 },
              { canonical_name: 'FlatChain',  competitive_classification: 'direct_competitor', ownership_type: 'private', location_count: 100, region_count: 100 },
            ]),
          });
        });

        await page.goto(base.path);
        await expect(page.getByTestId('chain-table')).toBeVisible({ timeout: 20000 });

        // Wait for the trend cells to populate (move off the placeholder).
        const arrows = page.getByTestId('trend-arrow');
        await expect(arrows).toHaveCount(3, { timeout: 10000 });

        // Each arrow sits inside a row. Grab the row's canonical_name via the
        // sibling trend-cell's data-chain attribute so we can pair sign→color.
        const rows = await page.locator('[data-testid="trend-cell"]').all();
        expect(rows.length).toBe(3);
        const greenArrow = page.locator('[data-testid="trend-cell"][data-chain="GreenChain"] [data-testid="trend-arrow"]');
        const redArrow = page.locator('[data-testid="trend-cell"][data-chain="RedChain"] [data-testid="trend-arrow"]');
        const flatArrow = page.locator('[data-testid="trend-cell"][data-chain="FlatChain"] [data-testid="trend-arrow"]');

        await expect(greenArrow).toHaveClass(/trend-up/);
        await expect(redArrow).toHaveClass(/trend-down/);
        await expect(flatArrow).toHaveClass(/trend-flat/);
      });

      test('no JS console errors', async ({ page }) => {
        const errors: string[] = [];
        page.on('pageerror', (e) => errors.push(e.message));
        page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
        await page.goto(base.path);
        await page.waitForLoadState('networkidle');
        const real = errors.filter((e) => !/favicon/i.test(e));
        expect(real, `unexpected console errors: ${real.join('\n')}`).toEqual([]);
      });
    });
  }
}

test.describe('Landing page link', () => {
  test('landing has a Gym Intelligence card pointing at the live URL', async ({ page }) => {
    await page.goto('/');
    const card = page.locator('a.card[href="/gym-intelligence/"]');
    await expect(card).toBeVisible();
  });
});
