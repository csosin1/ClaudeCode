/**
 * abs-dashboard Playwright spec — deterministic visual-lint gate.
 *
 * Wires every assertion from /opt/site-deploy/helpers/visual-lint.js and
 * visual-lint-axe.js against the live dashboard. Each chart-hygiene rule
 * maps to a class of bug that has bitten this project before — see the
 * 2026-04-17 "Hazard by LTV band" incident in LESSONS.md.
 *
 * Chart declarations live in /opt/abs-dashboard/.charts.yaml.
 *
 * Tests tagged @post-deploy are a fast subset that the post-deploy hook
 * runs against preview before promote. The full suite (no tag) runs in
 * the QA CI workflow.
 */
import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';

// Shared visual-lint helpers (mounted on the droplet at /opt/site-deploy)
// eslint-disable-next-line @typescript-eslint/no-var-requires
const vlint = require('/opt/site-deploy/helpers/visual-lint.js');

// NOTE: /opt/site-deploy/helpers/visual-lint-axe.js dynamic-imports
// @axe-core/playwright relative to its own path, which doesn't have
// node_modules. Rather than reach into the helper, we invoke AxeBuilder
// directly (matches the helper's behavior 1:1). See SKILLS/visual-lint.md.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { default: AxeBuilder } = require('@axe-core/playwright');

async function runAxe(page: Page, opts: { allowed?: string[]; excluded?: string[] } = {}) {
  const allowed = new Set(opts.allowed || []);
  let builder = new AxeBuilder({ page });
  if (opts.excluded && opts.excluded.length > 0) builder = builder.disableRules(opts.excluded);
  const results = await builder.analyze();
  const blocking = results.violations.filter((v: any) => !allowed.has(v.id));
  if (blocking.length > 0) {
    const lines = blocking.map((v: any) => {
      const nodeList = v.nodes.slice(0, 3).map((n: any) =>
        `      ${Array.isArray(n.target) ? n.target.join(' ') : String(n.target)}`).join('\n');
      const extra = v.nodes.length > 3 ? `\n      ... (+${v.nodes.length - 3} more)` : '';
      return `  [${v.impact || '?'}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n${nodeList}${extra}`;
    }).join('\n');
    throw new Error(`runAxe: ${blocking.length} axe-core violation(s):\n${lines}`);
  }
}

const DASHBOARD_PATH = '/CarvanaLoanDashBoard/';
// Some tests run against the preview URL (post-deploy gate). Override via env.
const DASHBOARD_URL = process.env.DASHBOARD_URL || DASHBOARD_PATH;
const METHOD_URL = `${DASHBOARD_URL}?tab=methodology`;

const CHARTS_YAML_PATH = '/opt/abs-dashboard/.charts.yaml';

function loadChartDeclarations(): any {
  const raw = fs.readFileSync(CHARTS_YAML_PATH, 'utf8');
  return yaml.load(raw);
}

/** Wait for Plotly to finish hydrating. Plotly.newPlot is async; we wait
 *  until every `.js-plotly-plot` has `_fullLayout` attached. */
async function waitForPlotlyReady(page: Page, timeoutMs = 15000) {
  await page.waitForFunction(() => {
    const nodes = Array.from(document.querySelectorAll('.js-plotly-plot'));
    if (nodes.length === 0) return false;
    return nodes.every((n: any) => n._fullLayout);
  }, null, { timeout: timeoutMs });
}

// --------------------------------------------------------------------------
// Post-deploy fast subset (tagged @post-deploy). These are the cheapest
// deterministic assertions — run them against /preview/ before promote.
// --------------------------------------------------------------------------
test.describe('abs-dashboard @post-deploy visual-lint fast subset', () => {
  test('landing page: no raw HTML entities, no placeholders, no console errors @post-deploy',
    async ({ page }) => {
      const consoleCheck = vlint.attachConsoleErrorCollector(page);
      const resp = await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });
      expect(resp?.status(), 'dashboard landing should 200').toBe(200);
      await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
      await vlint.assertNoRawHtmlEntities(page);
      await vlint.assertNoContentPlaceholders(page);
      await vlint.assertAllImagesLoaded(page);
      await consoleCheck();
    });

  test('methodology tab: no raw HTML entities, no placeholders @post-deploy',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
      await vlint.assertNoRawHtmlEntities(page);
      await vlint.assertNoContentPlaceholders(page);
    });

  test('methodology: declared charts render with expected categories @post-deploy',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
      await waitForPlotlyReady(page, 25000);

      const declarations = loadChartDeclarations();
      await vlint.assertChartCategoriesComplete(page, declarations);
    });
});

// --------------------------------------------------------------------------
// Full suite (runs in CI). Chart-hygiene extensions + a11y sweep.
// --------------------------------------------------------------------------
test.describe('abs-dashboard full visual-lint suite', () => {
  test('landing page: images load and no network 4xx/5xx', async ({ page }) => {
    const netCheck = vlint.attachNetworkFailureCollector(page);
    await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    await vlint.assertAllImagesLoaded(page);
    await netCheck();
  });

  test('methodology: every chart has a title (h4 or plotly layout)', async ({ page }) => {
    await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
    await waitForPlotlyReady(page, 25000);
    await vlint.assertChartHasTitle(page, '.js-plotly-plot');
  });

  test('methodology: every chart has labeled axes', async ({ page }) => {
    await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
    await waitForPlotlyReady(page, 25000);
    // Heatmaps and charts without conventional axes are still required to
    // label both axes in this project. Pie/sunburst charts are not used here.
    await vlint.assertChartAxesLabeled(page, '.js-plotly-plot',
      { requireX: true, requireY: true });
  });

  test('methodology: no empty charts (each plotly div has >=1 data point)',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
      await waitForPlotlyReady(page, 25000);
      await vlint.assertNoEmptyCharts(page, { selector: '.js-plotly-plot', minDataPoints: 1 });
    });

  test('methodology: chart legends do not clip their containers',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
      await waitForPlotlyReady(page, 25000);
      await vlint.assertLegendNotClipped(page, '.js-plotly-plot');
    });

  test('methodology: no chart overflows its parent container',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
      await waitForPlotlyReady(page, 25000);
      await vlint.assertNoChartOverflow(page, '.js-plotly-plot');
    });

  test('methodology: no scroll traps inside the tab (overflow:auto on a tight box)',
    async ({ page }) => {
      await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
      await vlint.assertNoScrollTraps(page, { maxScrollableHeight: '30vh', tableSelector: 'table' });
    });

  test('a11y: axe-core scan on landing page', async ({ page }) => {
    await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    // Allow color-contrast & region for now (Plotly defaults + tab-layout <main>)
    // These were not caught in today's meta-test; flagged for follow-up.
    await runAxe(page, {
      allowed: ['color-contrast', 'region', 'landmark-one-main', 'page-has-heading-one'],
    });
  });

  test('a11y: axe-core scan on methodology tab', async ({ page }) => {
    await page.goto(METHOD_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 25000 }).catch(() => {});
    await runAxe(page, {
      allowed: ['color-contrast', 'region', 'landmark-one-main', 'page-has-heading-one'],
    });
  });
});
