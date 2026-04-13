import { test, expect } from '@playwright/test';

const VIEWPORTS = [
  { name: 'mobile',  width: 390,  height: 844 },
  { name: 'desktop', width: 1280, height: 800 },
];

for (const vp of VIEWPORTS) {
  test.describe(`Timeshare Surveillance (${vp.name} ${vp.width}x${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test('dashboard loads at 200', async ({ page }) => {
      const resp = await page.goto('/timeshare-surveillance/preview/');
      expect(resp?.status()).toBe(200);
      const hdr = page.getByTestId('hdr');
      await expect(hdr).toBeVisible();
      await expect(hdr).toContainText('Timeshare Receivable Surveillance');
      await expect(hdr).toContainText('HGV');
      await expect(hdr).toContainText('VAC');
      await expect(hdr).toContainText('TNL');
      // active-flags badge is present
      await expect(page.getByTestId('active-flags-count')).toBeVisible();
    });

    test('KPI scorecard renders three ticker columns', async ({ page }) => {
      await page.goto('/timeshare-surveillance/preview/');
      const scorecard = page.getByTestId('kpi-scorecard');
      await expect(scorecard).toBeVisible();
      await expect(scorecard.locator('[data-ticker]')).toHaveCount(3);
      await expect(scorecard.locator('[data-ticker="HGV"]')).toBeVisible();
      await expect(scorecard.locator('[data-ticker="VAC"]')).toBeVisible();
      await expect(scorecard.locator('[data-ticker="TNL"]')).toBeVisible();
    });

    test('charts grid has 6 chart containers', async ({ page }) => {
      await page.goto('/timeshare-surveillance/preview/');
      const grid = page.getByTestId('charts-grid');
      await expect(grid).toBeVisible();
      await expect(grid.locator('[data-chart]')).toHaveCount(6);
    });

    test('flag panel, peer table, vintages, commentary, and footer render', async ({ page }) => {
      await page.goto('/timeshare-surveillance/preview/');
      await expect(page.getByTestId('flag-panel')).toBeVisible();
      await expect(page.getByTestId('peer-table')).toBeVisible();
      await expect(page.getByTestId('vintages')).toBeVisible();
      await expect(page.getByTestId('commentary')).toBeVisible();
      await expect(page.getByTestId('footer')).toBeVisible();
      await expect(page.getByTestId('footer')).toContainText('SEC EDGAR');
      await expect(page.getByTestId('footer')).toContainText('https://casinv.dev/timeshare-surveillance/');
    });

    test('no JS console errors', async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      await page.goto('/timeshare-surveillance/preview/');
      await page.waitForLoadState('networkidle');
      const real = errors.filter((e) => !/favicon/i.test(e) && !/combined\.json/i.test(e));
      expect(real, `unexpected console errors: ${real.join('\n')}`).toEqual([]);
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
