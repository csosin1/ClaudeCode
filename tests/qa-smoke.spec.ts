import { test, expect } from '@playwright/test';

test.describe('Landing Page', () => {
  test('loads and shows project cards', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);
    await expect(page.locator('h1')).toContainText('Projects');
    await expect(page.locator('a.card')).toHaveCount(3);
  });

  test('all project links return 200', async ({ page, request }) => {
    await page.goto('/');
    const links = await page.locator('a.card').evaluateAll(
      (els) => els.map((el) => el.getAttribute('href')).filter(Boolean)
    );
    for (const link of links) {
      const resp = await request.get(link!);
      expect(resp.status(), `Link ${link} should return 200`).toBe(200);
    }
  });
});

test.describe('Games Hub', () => {
  test('loads and shows game cards', async ({ page }) => {
    const response = await page.goto('/games/');
    expect(response?.status()).toBe(200);
    await expect(page.locator('h1')).toContainText('Games');
    const cards = page.locator('a.card');
    expect(await cards.count()).toBeGreaterThan(0);
  });

  test('each game link loads without JS errors', async ({ page }) => {
    await page.goto('/games/');
    const links = await page.locator('a.card').evaluateAll(
      (els) => els.map((el) => el.getAttribute('href')).filter(Boolean)
    );

    for (const link of links) {
      const errors: string[] = [];
      page.on('pageerror', (err) => errors.push(err.message));

      const resp = await page.goto(link!);
      expect(resp?.status(), `${link} should return 200`).toBe(200);
      expect(errors, `${link} should have no JS errors`).toHaveLength(0);

      page.removeAllListeners('pageerror');
    }
  });
});

test.describe('Carvana Dashboard', () => {
  test('live dashboard loads', async ({ request }) => {
    const response = await request.get('/CarvanaLoanDashBoard/');
    // Accept 200 (deployed) or 403/404 (not yet deployed on this droplet)
    expect([200, 403, 404]).toContain(response.status());
    if (response.status() !== 200) {
      test.skip(true, 'Carvana dashboard not deployed yet');
    }
  });

  test('preview dashboard loads', async ({ request }) => {
    const response = await request.get('/CarvanaLoanDashBoard/preview/');
    expect([200, 403, 404]).toContain(response.status());
    if (response.status() !== 200) {
      test.skip(true, 'Carvana preview not deployed yet');
    }
  });
});

test.describe('Security', () => {
  test('.env returns 404', async ({ request }) => {
    const resp = await request.get('/.env');
    expect(resp.status()).toBe(404);
  });

  test('.md files return 404', async ({ request }) => {
    const resp = await request.get('/README.md');
    expect(resp.status()).toBe(404);
  });

  test('dotfiles return 404', async ({ request }) => {
    const resp = await request.get('/.git/config');
    expect(resp.status()).toBe(404);
  });
});

test.describe('Performance', () => {
  test('landing page loads under 8 seconds', async ({ page }) => {
    const start = Date.now();
    await page.goto('/');
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(8000);
  });

  test('games hub loads under 8 seconds', async ({ page }) => {
    const start = Date.now();
    await page.goto('/games/');
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(8000);
  });
});

test.describe('Button Test App', () => {
  test('clicking button generates a number between 1-100', async ({ page }) => {
    await page.goto('/games/button-test/');
    await expect(page.locator('h1')).toContainText('Button Test');

    // Result should be empty before clicking
    const result = page.locator('#result');
    await expect(result).toHaveText('');

    // Click the button
    await page.locator('#generate-btn').click();

    // Result should now show a number
    const text = await result.textContent();
    console.log(`>>> BUTTON TEST: Clicked button, got number: ${text}`);
    expect(text).toBeTruthy();
    const num = parseInt(text!, 10);
    expect(num).toBeGreaterThanOrEqual(1);
    expect(num).toBeLessThanOrEqual(100);
    console.log(`>>> BUTTON TEST: Verified ${num} is between 1-100 ✓`);

    // Click again — should get a new number (or same, both valid)
    await page.locator('#generate-btn').click();
    const text2 = await result.textContent();
    const num2 = parseInt(text2!, 10);
    console.log(`>>> BUTTON TEST: Second click got: ${num2}`);
    expect(num2).toBeGreaterThanOrEqual(1);
    expect(num2).toBeLessThanOrEqual(100);
  });
});

test.describe('Webhook Health', () => {
  test('webhook health endpoint returns 200', async ({ request }) => {
    const resp = await request.get('/webhook/health');
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.status).toBe('ok');
  });
});
