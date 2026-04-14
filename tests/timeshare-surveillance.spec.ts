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

    test('charts with zero non-null values show the "No data in this range" message', async ({ page }) => {
      // Intercept combined.json and supply a single-row payload where every
      // metric is null for every ticker. This triggers the empty-range state
      // for all 9 charts.
      await page.route('**/timeshare-surveillance/preview/data/combined.json', async (route) => {
        const body = [
          { ticker: 'HGV', period_end: '2025-06-30', accession: 'x', segments: [],
            delinquent_90_plus_days_pct: null, delinquent_total_pct: null,
            allowance_coverage_pct: null, provision_for_loan_losses_mm: null,
            weighted_avg_fico_origination: null, fico_below_600_pct: null,
            gain_on_sale_margin_pct: null, new_securitization_advance_rate_pct: null,
            originations_mm: null },
          { ticker: 'VAC', period_end: '2025-06-30', accession: 'y', segments: [],
            delinquent_90_plus_days_pct: null, delinquent_total_pct: null,
            allowance_coverage_pct: null, provision_for_loan_losses_mm: null,
            weighted_avg_fico_origination: null, fico_below_600_pct: null,
            gain_on_sale_margin_pct: null, new_securitization_advance_rate_pct: null,
            originations_mm: null },
          { ticker: 'TNL', period_end: '2025-06-30', accession: 'z', segments: [],
            delinquent_90_plus_days_pct: null, delinquent_total_pct: null,
            allowance_coverage_pct: null, provision_for_loan_losses_mm: null,
            weighted_avg_fico_origination: null, fico_below_600_pct: null,
            gain_on_sale_margin_pct: null, new_securitization_advance_rate_pct: null,
            originations_mm: null },
        ];
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });

      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const cards = page.getByTestId('chart-card');
      await expect(cards).toHaveCount(9);
      const empties = page.getByTestId('chart-empty');
      await expect.poll(() => empties.count()).toBe(9);
      await expect(empties.first()).toContainText(/no data in this range/i);
    });

    test('tickers without data are absent from the chart legend', async ({ page }) => {
      // One ticker (TNL) fully populated; HGV and VAC entirely null for one
      // metric. That metric's chart should show only a TNL line + legend.
      await page.route('**/timeshare-surveillance/preview/data/combined.json', async (route) => {
        const body: any[] = [];
        for (let i = 0; i < 6; i++) {
          const y = 2024 + Math.floor(i / 4);
          const q = (i % 4) + 1;
          const month = q * 3;
          const day = month === 3 ? 31 : month === 6 ? 30 : month === 9 ? 30 : 31;
          const pe = `${y}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          body.push({ ticker: 'HGV', period_end: pe, accession: 'h' + i, segments: [],
            delinquent_90_plus_days_pct: null });
          body.push({ ticker: 'VAC', period_end: pe, accession: 'v' + i, segments: [],
            delinquent_90_plus_days_pct: null });
          body.push({ ticker: 'TNL', period_end: pe, accession: 't' + i, segments: [],
            delinquent_90_plus_days_pct: 0.03 + i * 0.001 });
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });

      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const dpdChart = page.locator('[data-chart="delinquent_90_plus_days_pct"]');
      await expect(dpdChart).toBeVisible();
      await expect(dpdChart.locator('[data-line="TNL"]')).toHaveCount(1);
      await expect(dpdChart.locator('[data-line="HGV"]')).toHaveCount(0);
      await expect(dpdChart.locator('[data-line="VAC"]')).toHaveCount(0);
      const legendItems = dpdChart.locator('.recharts-legend-item');
      await expect.poll(() => legendItems.count()).toBe(1);
    });

    test('snapshot badge annotates " · Narrative" when only mgmt flag fires', async ({ page }) => {
      await page.route('**/timeshare-surveillance/preview/data/combined.json', async (route) => {
        // All metrics CLEAN, but management flag set -> CRITICAL · Narrative.
        const clean = {
          delinquent_90_plus_days_pct: 0.01,
          delinquent_total_pct: 0.02,
          allowance_coverage_pct: 0.20,
          weighted_avg_fico_origination: 740,
          fico_below_600_pct: 0.05,
          gain_on_sale_margin_pct: 0.30,
          provision_for_loan_losses_mm: 10,
          new_securitization_advance_rate_pct: 0.95,
          originations_mm: 500,
        };
        const body = [
          { ticker: 'HGV', period_end: '2025-06-30', accession: 'h', segments: [],
            management_flagged_credit_concerns: true, ...clean },
          { ticker: 'VAC', period_end: '2025-06-30', accession: 'v', segments: [],
            management_flagged_credit_concerns: false, ...clean,
            delinquent_90_plus_days_pct: 0.09 }, // fires CRITICAL threshold
          { ticker: 'TNL', period_end: '2025-06-30', accession: 't', segments: [],
            management_flagged_credit_concerns: false, ...clean },
        ];
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });

      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');

      const hgvBadge = page.locator('[data-testid="sev-badge"][data-ticker-sev="HGV"]');
      await expect(hgvBadge).toContainText('Narrative');

      const vacBadge = page.locator('[data-testid="sev-badge"][data-ticker-sev="VAC"]');
      await expect(vacBadge).toContainText('Threshold');

      const tnlBadge = page.locator('[data-testid="sev-badge"][data-ticker-sev="TNL"]');
      // CLEAN has no suffix.
      await expect(tnlBadge).toHaveText(/^CLEAN$/);
    });

    test('HGV provision chart draws a visible line extending to the latest period', async ({ page }) => {
      await page.route('**/timeshare-surveillance/preview/data/combined.json', async (route) => {
        // HGV has provision values through Q4 2025 but null for some
        // intermediate metrics — the fix ensures the provision line is still
        // drawn end-to-end.
        const body: any[] = [];
        const periods = [
          '2023-03-31', '2023-06-30', '2023-09-30', '2023-12-31',
          '2024-03-31', '2024-06-30', '2024-09-30', '2024-12-31',
          '2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31',
        ];
        periods.forEach((pe, i) => {
          body.push({ ticker: 'HGV', period_end: pe, accession: 'h' + i, segments: [],
            provision_for_loan_losses_mm: 200 + i * 20,
            // intermediate null on another metric shouldn't break provision line
            allowance_coverage_pct: i % 2 === 0 ? 0.15 : null });
          body.push({ ticker: 'VAC', period_end: pe, accession: 'v' + i, segments: [],
            provision_for_loan_losses_mm: 50 + i * 2 });
          body.push({ ticker: 'TNL', period_end: pe, accession: 't' + i, segments: [],
            provision_for_loan_losses_mm: 80 + i * 3 });
        });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });

      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      await page.locator('[data-range="3y"]').click();
      const chart = page.locator('[data-chart="provision_for_loan_losses_mm"]');
      await expect(chart).toBeVisible();

      const hgvLine = chart.locator('[data-line="HGV"] .recharts-line-curve').first();
      await expect(hgvLine).toBeVisible();
      const box = await hgvLine.boundingBox();
      expect(box, 'HGV provision line must have a bounding box').not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);

      // Last x-axis tick should include a 2025 label.
      const lastTick = chart.locator('.recharts-xAxis .recharts-cartesian-axis-tick-value').last();
      await expect(lastTick).toContainText('2025');
    });

    test('segment labels render in Title Case (not snake_case)', async ({ page }) => {
      await page.route('**/timeshare-surveillance/preview/data/combined.json', async (route) => {
        const body: any[] = [];
        const periods = ['2024-03-31', '2024-06-30', '2024-09-30', '2024-12-31', '2025-03-31'];
        periods.forEach((pe, i) => {
          body.push({
            ticker: 'HGV', period_end: pe, accession: 'h' + i,
            delinquent_90_plus_days_pct: 0.04 + i * 0.001,
            segments: [
              { segment_key: 'legacy_hgv', delinquent_90_plus_days_pct: 0.03 + i * 0.001 },
              { segment_key: 'diamond',    delinquent_90_plus_days_pct: 0.05 + i * 0.001 },
              { segment_key: 'bluegreen',  delinquent_90_plus_days_pct: 0.04 + i * 0.001 },
            ],
          });
          body.push({ ticker: 'VAC', period_end: pe, accession: 'v' + i, segments: [],
            delinquent_90_plus_days_pct: 0.03 });
          body.push({ ticker: 'TNL', period_end: pe, accession: 't' + i, segments: [],
            delinquent_90_plus_days_pct: 0.02 });
        });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });

      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      await page.getByTestId('hgv-toggle').locator('.switch-wrap').click();
      const chart = page.locator('[data-chart="delinquent_90_plus_days_pct"]');
      await expect(chart).toBeVisible();
      // Legend should use Title Case, not raw snake_case.
      const legend = chart.locator('.recharts-legend-wrapper');
      await expect(legend).toContainText('HGV Legacy HGV');
      await expect(legend).toContainText('HGV Diamond');
      await expect(legend).toContainText('HGV Bluegreen');
      await expect(legend).not.toContainText('legacy_hgv');
      await expect(legend).not.toContainText('acquired_at_fv');
    });

    test('range pills and HGV toggle meet 44px tap-target size', async ({ page }) => {
      await page.goto(PREVIEW);
      await page.waitForLoadState('networkidle');
      const empty = page.getByTestId('empty-state');
      if (await empty.isVisible().catch(() => false)) {
        test.skip(true, 'pipeline not populated yet');
      }
      const pill = page.locator('[data-range="1y"]');
      const pillBox = await pill.boundingBox();
      expect(pillBox!.height).toBeGreaterThanOrEqual(44);
      expect(pillBox!.width).toBeGreaterThanOrEqual(44);
      const wrap = page.getByTestId('hgv-toggle').locator('.switch-wrap');
      const wrapBox = await wrap.boundingBox();
      expect(wrapBox!.height).toBeGreaterThanOrEqual(44);
      expect(wrapBox!.width).toBeGreaterThanOrEqual(44);
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
