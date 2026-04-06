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

test.describe('Dice Roller App', () => {
  test('page loads with correct heading', async ({ page }) => {
    const response = await page.goto('/games/dice-roller/');
    expect(response?.status()).toBe(200);
    await expect(page.locator('h1')).toContainText('Dice Roller');
  });

  test('clicking roll produces a number 1-6 and updates history', async ({ page }) => {
    await page.goto('/games/dice-roller/');

    // Result and history should be empty before clicking
    const result = page.locator('#result');
    await expect(result).toHaveText('');

    // First roll
    await page.locator('#roll-btn').click();
    const text1 = await result.textContent();
    console.log(`>>> DICE ROLLER: First roll got: ${text1}`);
    expect(text1).toBeTruthy();
    const num1 = parseInt(text1!, 10);
    expect(num1).toBeGreaterThanOrEqual(1);
    expect(num1).toBeLessThanOrEqual(6);
    console.log(`>>> DICE ROLLER: Verified ${num1} is between 1-6`);

    // Second roll
    await page.locator('#roll-btn').click();
    const text2 = await result.textContent();
    console.log(`>>> DICE ROLLER: Second roll got: ${text2}`);
    const num2 = parseInt(text2!, 10);
    expect(num2).toBeGreaterThanOrEqual(1);
    expect(num2).toBeLessThanOrEqual(6);
    console.log(`>>> DICE ROLLER: Verified ${num2} is between 1-6`);

    // History should have at least 2 entries
    const historyItems = page.locator('#history .history-item');
    const count = await historyItems.count();
    console.log(`>>> DICE ROLLER: History has ${count} entries after 2 rolls`);
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test('no JS errors on page', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/games/dice-roller/');
    await page.locator('#roll-btn').click();
    expect(errors, 'Dice Roller should have no JS errors').toHaveLength(0);
  });
});

test.describe('Carvana Hub', () => {
  test('hub page loads with project cards', async ({ page }) => {
    const response = await page.goto('/carvana/');
    expect(response?.status()).toBe(200);
    await expect(page.locator('h1')).toContainText('Carvana');
    // Should have 3 cards: ABS Dashboard, Preview, Car Offers
    const cards = page.locator('a.card');
    expect(await cards.count()).toBe(3);
  });

  test('back link points to home', async ({ page }) => {
    await page.goto('/carvana/');
    const backLink = page.locator('a.back');
    await expect(backLink).toHaveAttribute('href', '/');
  });
});

test.describe('Car Offer Tool', () => {
  test('page loads (setup or main)', async ({ page }) => {
    const response = await page.goto('/car-offers/');
    expect(response?.status()).toBe(200);
    // Should see either the setup page or the main offer tool
    const heading = page.locator('h1');
    const text = await heading.textContent();
    expect(text === 'Server Setup' || text === 'Car Offer Tool').toBeTruthy();
  });

  test('no JS errors on car-offers page', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/car-offers/');
    expect(errors, 'Car Offer Tool should have no JS errors').toHaveLength(0);
  });
});

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

test.describe('Car Offers Dashboard', () => {
  test('dashboard loads', async ({ page }) => {
    await page.goto('/car-offers/dashboard');
    await expect(page.locator('h1')).toContainText('Car Offers Dashboard');
  });

  test('status API returns JSON', async ({ request }) => {
    const resp = await request.get('/car-offers/api/status');
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.service).toBeTruthy();
    expect(data.proxy).toBeTruthy();
  });
});

test.describe('Server Health', () => {
  test('debug.json reports healthy server state', async ({ request }) => {
    const resp = await request.get('/debug.json');
    expect(resp.status(), 'debug.json should be served').toBe(200);
    const body = await resp.json();
    console.log('>>> SERVER HEALTH:', JSON.stringify(body, null, 2));
    expect(body.car_offers_status).toBe('active');
    expect(body.port_3100).toBe(true);
    expect(body.gym_intelligence_status).toBe('active');
    expect(body.port_8502).toBe(true);
  });

  test('car-offers responds (not 502)', async ({ request }) => {
    const resp = await request.get('/car-offers/');
    expect(resp.status(), '/car-offers/ should not be 502').not.toBe(502);
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
