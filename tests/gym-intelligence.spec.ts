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
