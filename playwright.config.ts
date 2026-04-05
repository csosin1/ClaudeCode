import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 15000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: process.env.BASE_URL || 'http://159.223.127.125',
    screenshot: 'on',
    trace: 'on-first-retry',
  },

  projects: [
    {
      name: 'mobile',
      use: {
        ...devices['iPhone 13'],
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
