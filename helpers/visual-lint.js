/**
 * visual-lint.js — deterministic visual QA assertions (the "B-plus" layer)
 *
 * Playwright-compatible assertion module. Projects import named functions
 * and call them inside their `tests/<project>.spec.ts` files. Every
 * assertion throws a descriptive Error on failure so Playwright surfaces
 * the offending page, element, and text in the QA log.
 *
 * This file is deliberately dependency-free apart from Playwright itself.
 * axe-core integration lives in visual-lint-axe.js so projects that don't
 * want the extra install can skip it.
 *
 * Each function documents the bug class it catches. The 2026-04-17
 * Methodology incident (abs-dashboard) motivated three rules here:
 *   - raw HTML entities leaking through Plotly text fields
 *   - charts that render but have no data points (unit-mismatched bucketing)
 *   - overflow: auto + max-height on table wrappers creating scroll traps
 * See SKILLS/visual-lint.md → "Anti-pattern catalog" for the full write-up.
 */

'use strict';

// ---------------------------------------------------------------------------
// 1. assertNoRawHtmlEntities
// ---------------------------------------------------------------------------

/**
 * Scan rendered text for un-escaped HTML entity patterns like `&mdash;`,
 * `&amp;`, `&hellip;` that leaked through a template engine or a
 * charting library (e.g. Plotly text fields that expect plain text but
 * were handed an HTML-encoded string).
 *
 * Catches the 2026-04-17 Methodology bug where "&mdash;" literal strings
 * rendered inside Plotly subtitles instead of em-dashes.
 *
 * Allowed:
 *   - numeric entities inside <noscript> (legit fallbacks)
 *   - `&nbsp;` and `&zwnj;` — common deliberate whitespace entities
 *   - entities inside <pre><code> blocks demonstrating HTML itself
 *
 * @param {import('@playwright/test').Page} page
 * @returns {Promise<void>} throws on failure
 */
async function assertNoRawHtmlEntities(page) {
  const offenders = await page.evaluate(() => {
    const ALLOWED = new Set(['&nbsp;', '&zwnj;', '&zwj;']);
    const ENTITY_RE = /&(?:[a-zA-Z][a-zA-Z0-9]{1,30}|#\d{1,6}|#x[0-9a-fA-F]{1,6});/g;
    const results = [];

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        // Skip script/style/code/noscript contexts.
        let p = node.parentElement;
        while (p) {
          const tag = p.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' ||
              tag === 'CODE' || tag === 'PRE' || tag === 'TEMPLATE') {
            return NodeFilter.FILTER_REJECT;
          }
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    let n;
    while ((n = walker.nextNode())) {
      const text = n.nodeValue || '';
      const matches = text.match(ENTITY_RE);
      if (!matches) continue;
      for (const m of matches) {
        if (ALLOWED.has(m)) continue;
        const el = n.parentElement;
        results.push({
          entity: m,
          text: text.slice(0, 160),
          tag: el ? el.tagName.toLowerCase() : '?',
          id: el && el.id ? el.id : null,
          cls: el && el.className && typeof el.className === 'string' ? el.className.slice(0, 80) : null,
        });
        if (results.length >= 25) return results;
      }
    }
    return results;
  });

  if (offenders.length > 0) {
    const lines = offenders.map(o =>
      `  ${o.entity}  in <${o.tag}${o.id ? ' id="' + o.id + '"' : ''}${o.cls ? ' class="' + o.cls + '"' : ''}>: ${JSON.stringify(o.text)}`
    ).join('\n');
    throw new Error(
      `assertNoRawHtmlEntities: found ${offenders.length} unescaped HTML entit${offenders.length === 1 ? 'y' : 'ies'} in rendered text:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 2. assertNoEmptyCharts
// ---------------------------------------------------------------------------

/**
 * Every matching chart element must render at least `minDataPoints` data
 * points. For Plotly we read `gd.data` directly; for generic charts we
 * fall back to counting visible text / cells inside the container.
 *
 * Catches the 2026-04-17 Methodology bug where LTV-bucketing collapsed
 * an entire heatmap to a single cell because the bucket edges were in
 * the wrong unit (fraction vs percent).
 *
 * @param {import('@playwright/test').Page} page
 * @param {{selector?: string, minDataPoints?: number}} opts
 */
async function assertNoEmptyCharts(page, opts = {}) {
  const selector = opts.selector || '.js-plotly-plot';
  const minDataPoints = opts.minDataPoints || 1;

  const report = await page.evaluate(({ selector, minDataPoints }) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      let count = 0;
      let mode = 'unknown';

      // Plotly: gd.data is an array of traces, each trace has x/y/z arrays.
      if (el.data && Array.isArray(el.data)) {
        mode = 'plotly';
        for (const trace of el.data) {
          for (const axis of ['x', 'y', 'z', 'values', 'labels']) {
            const v = trace[axis];
            if (Array.isArray(v)) {
              // flatten one level for 2D arrays (heatmaps)
              for (const row of v) {
                if (Array.isArray(row)) count += row.length;
                else count += 1;
              }
            }
          }
        }
      } else {
        // Fallback: count visible text nodes + svg <rect>/<circle>/<path> children.
        mode = 'dom';
        const txt = (el.innerText || '').trim();
        if (txt.length > 0) count += 1;
        count += el.querySelectorAll('rect, circle, path, td, .cell').length;
      }

      if (count < minDataPoints) {
        out.push({
          index: i,
          id: el.id || null,
          cls: typeof el.className === 'string' ? el.className.slice(0, 80) : null,
          count,
          mode,
        });
      }
    }
    return { total: nodes.length, empty: out };
  }, { selector, minDataPoints });

  if (report.empty.length > 0) {
    const lines = report.empty.map(e =>
      `  chart[${e.index}] (${e.mode}) id="${e.id || ''}" cls="${e.cls || ''}" — ${e.count} data point${e.count === 1 ? '' : 's'} (< ${minDataPoints})`
    ).join('\n');
    throw new Error(
      `assertNoEmptyCharts: ${report.empty.length} of ${report.total} chart(s) matching "${selector}" have fewer than ${minDataPoints} data points:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 3. assertNoScrollTraps
// ---------------------------------------------------------------------------

/**
 * Find elements that wrap a table (or any tall child) where:
 *   - wrapper has overflow-y: auto | scroll
 *   - wrapper's client height is much smaller than the child's scroll height
 *   - wrapper's max-height is below the threshold (default ~30vh)
 *
 * These create the "trap" shape — the user scrolls into the wrapper and
 * the page scroll becomes stuck inside a small box. This is the exact
 * CSS that produced the 2026-04-17 footer scroll-trap on Methodology.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{maxScrollableHeight?: string, tableSelector?: string}} opts
 */
async function assertNoScrollTraps(page, opts = {}) {
  const maxScrollableHeight = opts.maxScrollableHeight || '30vh';
  const tableSelector = opts.tableSelector || 'table';

  const offenders = await page.evaluate(({ maxScrollableHeight, tableSelector }) => {
    // Convert threshold to pixels.
    let thresholdPx;
    const m = String(maxScrollableHeight).match(/^([\d.]+)\s*(px|vh|vw|%)?$/);
    if (!m) {
      thresholdPx = 0.3 * window.innerHeight;
    } else {
      const n = parseFloat(m[1]);
      const unit = m[2] || 'px';
      if (unit === 'px') thresholdPx = n;
      else if (unit === 'vh') thresholdPx = (n / 100) * window.innerHeight;
      else if (unit === 'vw') thresholdPx = (n / 100) * window.innerWidth;
      else if (unit === '%') thresholdPx = (n / 100) * window.innerHeight;
      else thresholdPx = n;
    }

    const results = [];
    const tables = Array.from(document.querySelectorAll(tableSelector));
    for (const t of tables) {
      // Walk up to find a scrollable ancestor that isn't <html>/<body>.
      let w = t.parentElement;
      while (w && w !== document.body && w !== document.documentElement) {
        const cs = window.getComputedStyle(w);
        const oy = cs.overflowY;
        if (oy === 'auto' || oy === 'scroll') {
          const clientH = w.clientHeight;
          const scrollH = w.scrollHeight;
          const isTrap = clientH < thresholdPx && scrollH - clientH > 20;
          if (isTrap) {
            results.push({
              tag: w.tagName.toLowerCase(),
              id: w.id || null,
              cls: typeof w.className === 'string' ? w.className.slice(0, 80) : null,
              clientHeight: clientH,
              scrollHeight: scrollH,
              thresholdPx: Math.round(thresholdPx),
            });
          }
          break;  // only report first scrollable ancestor
        }
        w = w.parentElement;
      }
    }
    return results;
  }, { maxScrollableHeight, tableSelector });

  if (offenders.length > 0) {
    const lines = offenders.map(o =>
      `  <${o.tag}${o.id ? ' id="' + o.id + '"' : ''}${o.cls ? ' class="' + o.cls + '"' : ''}> clientH=${o.clientHeight}px scrollH=${o.scrollHeight}px threshold=${o.thresholdPx}px`
    ).join('\n');
    throw new Error(
      `assertNoScrollTraps: ${offenders.length} scroll-trap wrapper(s) found (overflow:auto|scroll with max-height < ${maxScrollableHeight} around a taller child):\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 4. assertNoContentPlaceholders
// ---------------------------------------------------------------------------

/**
 * Fail on any of the following literal strings appearing in rendered
 * text: NaN, undefined, null, {{...}}, [object Object], TODO, FIXME,
 * "Lorem ipsum". These are all signs of a broken template or a JS
 * formatting error.
 *
 * @param {import('@playwright/test').Page} page
 */
async function assertNoContentPlaceholders(page) {
  const offenders = await page.evaluate(() => {
    const patterns = [
      { name: 'NaN', re: /\bNaN\b/ },
      { name: 'undefined', re: /\bundefined\b/ },
      { name: 'null', re: /(?:^|[\s>:])null(?:$|[\s<,;.])/ },
      { name: 'unresolved-template', re: /\{\{[^{}]{0,200}\}\}/ },
      { name: 'object-object', re: /\[object Object\]/ },
      { name: 'TODO', re: /\bTODO\b/ },
      { name: 'FIXME', re: /\bFIXME\b/ },
      { name: 'lorem-ipsum', re: /Lorem ipsum/i },
    ];
    const out = [];

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        let p = node.parentElement;
        while (p) {
          const tag = p.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEMPLATE') {
            return NodeFilter.FILTER_REJECT;
          }
          p = p.parentElement;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    let n;
    while ((n = walker.nextNode())) {
      const text = n.nodeValue || '';
      if (!text.trim()) continue;
      for (const { name, re } of patterns) {
        if (re.test(text)) {
          const el = n.parentElement;
          out.push({
            pattern: name,
            text: text.slice(0, 160),
            tag: el ? el.tagName.toLowerCase() : '?',
            id: el && el.id ? el.id : null,
          });
          if (out.length >= 25) return out;
          break;
        }
      }
    }
    return out;
  });

  if (offenders.length > 0) {
    const lines = offenders.map(o =>
      `  [${o.pattern}] <${o.tag}${o.id ? ' id="' + o.id + '"' : ''}>: ${JSON.stringify(o.text)}`
    ).join('\n');
    throw new Error(
      `assertNoContentPlaceholders: ${offenders.length} placeholder / broken-template marker(s) in rendered text:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 5. assertAllImagesLoaded
// ---------------------------------------------------------------------------

/**
 * Every <img> on the page has `complete === true` and `naturalHeight > 0`.
 * Catches broken `src` paths and lazy-load regressions.
 *
 * @param {import('@playwright/test').Page} page
 */
async function assertAllImagesLoaded(page) {
  const bad = await page.evaluate(() => {
    const imgs = Array.from(document.querySelectorAll('img'));
    return imgs
      .filter(img => !(img.complete && img.naturalHeight > 0))
      .map(img => ({
        src: img.currentSrc || img.src || '(empty)',
        alt: img.alt || null,
        complete: img.complete,
        naturalHeight: img.naturalHeight,
      }));
  });

  if (bad.length > 0) {
    const lines = bad.map(b =>
      `  src=${JSON.stringify(b.src)} alt=${JSON.stringify(b.alt)} complete=${b.complete} naturalHeight=${b.naturalHeight}`
    ).join('\n');
    throw new Error(
      `assertAllImagesLoaded: ${bad.length} image(s) failed to load:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 6. assertNoConsoleErrors
// ---------------------------------------------------------------------------

/**
 * Attach collectors for `pageerror` and `console` errors. Call the
 * returned `check()` function at the end of your test — it throws if
 * anything was collected. Example:
 *
 *   const consoleCheck = attachConsoleErrorCollector(page);
 *   await page.goto(url);
 *   // ...
 *   await consoleCheck();  // throws if errors appeared
 *
 * For tests that do the whole goto/wait in one shot, the one-shot helper
 * `assertNoConsoleErrors(page, action)` accepts an async action and
 * runs the check after it returns.
 *
 * @param {import('@playwright/test').Page} page
 * @param {() => Promise<void>} [action]
 */
function attachConsoleErrorCollector(page) {
  const errors = [];
  const onPageError = err => errors.push({ kind: 'pageerror', message: err.message });
  const onConsole = msg => {
    if (msg.type() === 'error') errors.push({ kind: 'console', message: msg.text() });
  };
  page.on('pageerror', onPageError);
  page.on('console', onConsole);

  return async function check() {
    page.off('pageerror', onPageError);
    page.off('console', onConsole);
    if (errors.length > 0) {
      const lines = errors.map(e => `  [${e.kind}] ${e.message}`).join('\n');
      throw new Error(`assertNoConsoleErrors: ${errors.length} console error(s):\n${lines}`);
    }
  };
}

async function assertNoConsoleErrors(page, action) {
  const check = attachConsoleErrorCollector(page);
  if (typeof action === 'function') {
    await action();
  }
  await check();
}

// ---------------------------------------------------------------------------
// 7. assertNoNetworkFailures
// ---------------------------------------------------------------------------

/**
 * Collect all responses with status >= 400 on non-analytics subresources.
 * Same pattern as `attachConsoleErrorCollector`: returns `check()`.
 *
 * Analytics hosts (matched in ANALYTICS_HOSTS) are ignored — a blocked
 * tracker shouldn't fail the test.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ignoreHosts?: string[]}} [opts]
 */
function attachNetworkFailureCollector(page, opts = {}) {
  const ANALYTICS_HOSTS = [
    'google-analytics.com', 'googletagmanager.com', 'doubleclick.net',
    'facebook.com', 'facebook.net', 'segment.io', 'mixpanel.com',
    'hotjar.com', 'sentry.io',
    ...(opts.ignoreHosts || []),
  ];
  const failures = [];
  const onResponse = async resp => {
    try {
      const status = resp.status();
      if (status < 400) return;
      const url = resp.url();
      if (ANALYTICS_HOSTS.some(h => url.includes(h))) return;
      failures.push({ status, url });
    } catch (_) { /* response already gone */ }
  };
  page.on('response', onResponse);

  return async function check() {
    page.off('response', onResponse);
    if (failures.length > 0) {
      const lines = failures.map(f => `  ${f.status}  ${f.url}`).join('\n');
      throw new Error(`assertNoNetworkFailures: ${failures.length} 4xx/5xx response(s):\n${lines}`);
    }
  };
}

async function assertNoNetworkFailures(page, action, opts = {}) {
  const check = attachNetworkFailureCollector(page, opts);
  if (typeof action === 'function') {
    await action();
  }
  await check();
}

// ---------------------------------------------------------------------------
// 8. assertCriticalElementsInViewport
// ---------------------------------------------------------------------------

/**
 * Each selector's bottom edge must be within the viewport at page load.
 * Use for hero / CTA / first-paint elements that must not be pushed
 * below the fold by layout shifts.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string[]} selectors
 */
async function assertCriticalElementsInViewport(page, selectors = []) {
  if (!selectors.length) return;

  const report = await page.evaluate((sels) => {
    const vh = window.innerHeight;
    return sels.map(sel => {
      const el = document.querySelector(sel);
      if (!el) return { sel, present: false };
      const r = el.getBoundingClientRect();
      return {
        sel,
        present: true,
        bottom: Math.round(r.bottom),
        viewportHeight: vh,
        inViewport: r.bottom <= vh && r.top >= 0,
      };
    });
  }, selectors);

  const missing = report.filter(r => !r.present);
  const below = report.filter(r => r.present && !r.inViewport);

  if (missing.length > 0 || below.length > 0) {
    const lines = [];
    for (const m of missing) lines.push(`  NOT FOUND: ${m.sel}`);
    for (const b of below) lines.push(`  BELOW FOLD: ${b.sel} bottom=${b.bottom}px viewport=${b.viewportHeight}px`);
    throw new Error(`assertCriticalElementsInViewport:\n${lines.join('\n')}`);
  }
}

// ---------------------------------------------------------------------------
// 9. assertContrast — thin delegation to axe-core
// ---------------------------------------------------------------------------

/**
 * Thin wrapper that delegates to axe-core's `color-contrast` rule.
 * Don't reinvent WCAG math; axe-core is the canonical implementation.
 *
 * Requires the project to have installed `@axe-core/playwright`.
 *
 * @param {import('@playwright/test').Page} page
 * @param {number} [minRatio=4.5]  — WCAG AA body text
 */
async function assertContrast(page, minRatio = 4.5) {
  // eslint-disable-next-line global-require
  const { default: AxeBuilder } = await import('@axe-core/playwright');
  const results = await new AxeBuilder({ page })
    .withRules(['color-contrast'])
    .analyze();

  const violations = results.violations.filter(v => v.id === 'color-contrast');
  if (violations.length === 0) return;

  // axe reports each violation with .nodes[]; each node.any[] has data.contrastRatio.
  const below = [];
  for (const v of violations) {
    for (const node of v.nodes) {
      const data = node.any && node.any[0] && node.any[0].data;
      const ratio = data && typeof data.contrastRatio === 'number' ? data.contrastRatio : null;
      if (ratio === null || ratio < minRatio) {
        below.push({
          target: Array.isArray(node.target) ? node.target.join(' ') : String(node.target),
          ratio: ratio === null ? 'unknown' : ratio.toFixed(2),
          fg: data && data.fgColor,
          bg: data && data.bgColor,
        });
      }
    }
  }

  if (below.length > 0) {
    const lines = below.map(b => `  ratio=${b.ratio}  fg=${b.fg} bg=${b.bg}  ${b.target}`).join('\n');
    throw new Error(`assertContrast: ${below.length} element(s) below ${minRatio}:1 contrast:\n${lines}`);
  }
}

module.exports = {
  assertNoRawHtmlEntities,
  assertNoEmptyCharts,
  assertNoScrollTraps,
  assertNoContentPlaceholders,
  assertAllImagesLoaded,
  assertNoConsoleErrors,
  attachConsoleErrorCollector,
  assertNoNetworkFailures,
  attachNetworkFailureCollector,
  assertCriticalElementsInViewport,
  assertContrast,
};
