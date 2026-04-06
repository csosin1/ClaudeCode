# Skill: Residential Proxy (Decodo/Smartproxy)

## What This Skill Does

Routes Playwright browser sessions through Decodo residential proxies, making automated browser traffic appear as real household users. Used for scraping sites with bot detection (PerimeterX, Cloudflare, etc.) and for submitting multi-step web forms without getting blocked.

## When To Use It

Any project that needs to automate interactions with sites that block datacenter IPs or detect non-human browser behavior.

## GitHub Secrets Required

These are already configured in `csosin1/ClaudeCode`:

| Secret | Value |
|--------|-------|
| `PROXY_HOST` | `gate.decodo.com` |
| `PROXY_PORT` | `10001` (ports 10001–10007 available) |
| `PROXY_USER` | `spjax0kgms` |
| `PROXY_PASS` | *(stored in GitHub Secrets — never hardcode)* |

On the droplet, these go in `/opt/<project>/.env`. Never commit credentials to git.

## Dependencies

```bash
npm install playwright playwright-extra puppeteer-extra-plugin-stealth
```

## Base Playwright Configuration — Rotating (Use for Scraping)

```javascript
const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const browser = await chromium.launch({
  headless: false, // set true for production
  proxy: {
    server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
    username: process.env.PROXY_USER,
    password: process.env.PROXY_PASS,
  }
});
```

## Base Playwright Configuration — Sticky Session (Use for Multi-Step Forms)

```javascript
// For sticky sessions, append session ID to username
// Same session ID = same IP throughout the form flow
const sessionId = Math.random().toString(36).substring(7);
const stickyUsername = `${process.env.PROXY_USER}-session-${sessionId}`;

const browser = await chromium.launch({
  headless: false,
  proxy: {
    server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
    username: stickyUsername,
    password: process.env.PROXY_PASS,
  }
});
```

## Human-Like Behavior Helpers

```javascript
// Random delay between actions
const delay = (min, max) => new Promise(r =>
  setTimeout(r, Math.floor(Math.random() * (max - min) + min))
);

// Type like a human
const fillField = async (page, selector, value) => {
  await page.click(selector);
  await delay(200, 600);
  for (const char of value) {
    await page.type(selector, char, {
      delay: Math.floor(Math.random() * 150 + 30)
    });
  }
};

// Use these between every action
await delay(800, 3000);
```

## Network Interception — Capture JSON API Responses

```javascript
// Set this up before navigating — captures pricing API calls
page.on('response', async response => {
  const url = response.url();
  if (url.includes('api.') &&
      response.headers()['content-type']?.includes('application/json')) {
    try {
      const json = await response.json();
      console.log(`[API INTERCEPT] ${url}`, JSON.stringify(json, null, 2));
      // Store json to your database here
    } catch (e) {}
  }
});
```

## Disposable Email Generation

```javascript
// Generate a throwaway email for form flows — no human needed
const getDisposableEmail = async (page) => {
  await page.goto('https://www.guerrillamail.com');
  await delay(1000, 2000);
  const email = await page.$eval('#email-widget', el => el.textContent.trim());
  return email;
};

// Check inbox for verification emails
const checkInbox = async (page, subjectContains) => {
  await page.goto('https://www.guerrillamail.com');
  await delay(2000, 4000);
  const emails = await page.$$('.mail_item');
  for (const email of emails) {
    const subject = await email.$eval('.subject', el => el.textContent);
    if (subject.includes(subjectContains)) {
      await email.click();
      return await page.$eval('.email_body', el => el.textContent);
    }
  }
  return null;
};
```

## Proxy Verification Test

```javascript
// Run this to confirm proxy is working before any project
const verifyProxy = async () => {
  const browser = await chromium.launch({
    proxy: {
      server: `http://${process.env.PROXY_HOST}:${process.env.PROXY_PORT}`,
      username: process.env.PROXY_USER,
      password: process.env.PROXY_PASS,
    }
  });
  const page = await browser.newPage();
  await page.goto('https://ip.decodo.com/json');
  const content = await page.textContent('body');
  console.log('Proxy verified:', content);
  await browser.close();
};
```

## Bandwidth Estimates

| Site | Per VIN |
|------|---------|
| AutoTrader listing page | ~2-3MB |
| CarMax offer flow end-to-end | ~5-10MB |
| Carvana offer flow | ~8-15MB |
| Driveway offer flow | ~5-10MB |
| **Per VIN across all 3 buyers** | **~20-35MB** |
| **3GB budget covers** | **~85-150 full VINs** |

## Known Site-Specific Notes

- **Carvana** — Uses PerimeterX. Stealth plugin + residential proxies handle it. Don't exceed ~20 VINs/day per IP.
- **CarMax** — Lightest bot detection of the three. Good site to test against first.
- **Driveway** — Lithia Motors. Moderate detection.
- **For all three:** Use sticky sessions during form submission, rotate between VINs.
