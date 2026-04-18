import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  // Project-specific spec only; the legacy qa-smoke.spec.ts is the shared
  // site landing-page smoke (owned by /opt/site-deploy) and was copied here
  // by an earlier tree-sync. Scope this config to abs-dashboard's own spec.
  testMatch: /abs-dashboard\.spec\.ts$/,
  timeout: 45000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: process.env.BASE_URL || 'https://casinv.dev',
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'mobile',
      use: {
        viewport: { width: 390, height: 844 },
      },
    },
    {
      name: 'desktop',
      use: {
        viewport: { width: 1280, height: 720 },
      },
    },
  ],
});
