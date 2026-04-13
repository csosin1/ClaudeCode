import { test, expect } from '@playwright/test';

const VIEWPORTS = [
  { name: 'mobile',  width: 390,  height: 844 },
  { name: 'desktop', width: 1280, height: 800 },
];

const PREVIEW = '/timeshare-surveillance/preview/';

for (const vp of VIEWPORTS) {
  test.describe(`Timeshare Surveillance (${vp.name} ${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test('dashboard loads at 200 with header + no console errors', async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

      const resp = await page.goto(PREVIEW);
      expect(resp?.status()).toBe(200);
      const hdr = page.getByTestId('hdr');
      await expect(hdr).toBeVisible();
      await expect(hdr).toContainText('Timeshare Receivable Surveillance');
      await expect(hdr).toContainText('HGV');
      await expect(hdr).toContainText('VAC');
      await expect(hdr).toContainText('TNL');

      // Allow combined.json fetch errors when the pipeline hasn't ingested yet.
      await page.waitForLoadState('networkidle');
      const real = errors.filter((e) => !/favicon/i.test(e) && !/combined\.json/i.test(e));
      expect(real, `unexpected console errors: ${real.join('\n')}`).toEqual([]);
    });

    test('renders either snapshot+charts OR pipeline-warming-up state', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');

      const empty = page.getByTestId('empty-state');
      const charts = page.getByTestId('charts-grid');
      const eitherVisible = await Promise.race([
        empty.waitFor({ state: 'visible', timeout: 4000 }).then(() => 'empty').catch(() => null),
        charts.waitFor({ state: 'visible', timeout: 4000 }).then(() => 'charts').catch(() => null),
      ]);
      expect(eitherVisible, 'expected either empty-state or charts-grid to be visible').not.toBeNull();
    });

    test('snapshot strip shows all 3 tickers when data is present', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const empty = page.getByTestId('empty-state');
      if (await empty.isVisible().catch(() => false)) {
        test.skip(true, 'pipeline not populated yet');
      }
      const strip = page.getByTestId('snapshot-strip');
      await expect(strip).toBeVisible();
      await expect(strip.locator('[data-ticker="HGV"]')).toBeVisible();
      await expect(strip.locator('[data-ticker="VAC"]')).toBeVisible();
      await expect(strip.locator('[data-ticker="TNL"]')).toBeVisible();
    });

    test('default range is 5y and grid renders 9 charts', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const empty = page.getByTestId('empty-state');
      if (await empty.isVisible().catch(() => false)) {
        test.skip(true, 'pipeline not populated yet');
      }
      const pill5y = page.locator('[data-range="5y"]');
      await expect(pill5y).toHaveClass(/active/);

      const cards = page.getByTestId('chart-card');
      await expect(cards).toHaveCount(9);
    });

    test('switching range to 1y reduces or holds the visible x-axis tick count', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const empty = page.getByTestId('empty-state');
      if (await empty.isVisible().catch(() => false)) {
        test.skip(true, 'pipeline not populated yet');
      }

      const firstChart = page.getByTestId('chart-card').first();
      const ticksAt5y = await firstChart.locator('.recharts-xAxis .recharts-cartesian-axis-tick').count();

      await page.locator('[data-range="1y"]').click();
      await expect(page.locator('[data-range="1y"]')).toHaveClass(/active/);
      const ticksAt1y = await firstChart.locator('.recharts-xAxis .recharts-cartesian-axis-tick').count();

      // Equal is acceptable on tiny datasets.
      expect(ticksAt1y).toBeLessThanOrEqual(ticksAt5y);
    });

    test('toggling HGV breakdown adds at least 2 HGV-segment lines on a chart', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const empty = page.getByTestId('empty-state');
      if (await empty.isVisible().catch(() => false)) {
        test.skip(true, 'pipeline not populated yet');
      }

      const toggle = page.getByTestId('hgv-toggle').locator('.switch');
      await toggle.click();
      await expect(page.getByTestId('hgv-toggle').locator('.switch')).toHaveClass(/on/);

      const segLines = page.locator('[data-line^="HGV_legacy_hgv"], [data-line^="HGV_diamond"], [data-line^="HGV_bluegreen"]');
      const count = await segLines.count();
      expect(count).toBeGreaterThanOrEqual(2);
    });
  });
}

test.describe('Admin setup page', () => {
  test('loads publicly and shows the credentials form', async ({ page }) => {
    const resp = await page.goto('/timeshare-surveillance/preview/admin/');
    expect(resp?.status()).toBe(200);
    await expect(page.getByTestId('admin-form')).toBeVisible();
    await expect(page.getByTestId('admin-save')).toBeVisible();
  });
});

test.describe('Landing page link', () => {
  test('landing has Timeshare Surveillance card linking to /timeshare-surveillance/', async ({ page }) => {
    await page.goto('/');
    const card = page.locator('a.card[href="/timeshare-surveillance/"]');
    await expect(card).toBeVisible();
    await expect(card).toContainText(/Timeshare/i);
  });
});

test.describe('combined.json shape', () => {
  test('served at the expected URL with a JSON array body', async ({ page }) => {
    const resp = await page.goto('/timeshare-surveillance/preview/data/combined.json');
    if (resp && resp.status() === 200) {
      const body = await resp.json();
      expect(Array.isArray(body)).toBeTruthy();
      if (body.length > 0) {
        const first = body[0];
        for (const k of ['ticker', 'period_end', 'accession']) {
          expect(first).toHaveProperty(k);
        }
        // Every record has a segments array (may be empty if not disclosed).
        expect(first).toHaveProperty('segments');
        expect(Array.isArray(first.segments)).toBeTruthy();
      }
    }
  });

  test('dashboard HTML references ./data/combined.json', async ({ page }) => {
    const resp = await page.goto(PREVIEW);
    expect(resp?.status()).toBe(200);
    const html = await page.content();
    expect(html).toContain('data/combined.json');
  });
});
