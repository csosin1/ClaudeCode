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

// ===========================================================================
// Chart-hygiene extensions — motivated by the 2026-04-17 live-site
// "Hazard by LTV band" bug: chart rendered with only one of four LTV
// categories populated because an upstream unit-scaling bug collapsed the
// other three to empty, and no assertion existed to declare what the chart
// SHOULD have shown. The declarative `.charts.yaml` schema closes that gap.
// See SKILLS/visual-lint.md → "Chart hygiene" for the full write-up.
// ===========================================================================

// ---------------------------------------------------------------------------
// 10. assertChartHasTitle
// ---------------------------------------------------------------------------

/**
 * Every matching chart must have a non-empty title. Accepts either:
 *   (a) Plotly `layout.title.text` set on the chart (`gd.layout.title.text`), or
 *   (b) a visible <h2>/<h3>/<h4> header inside the chart element, or
 *   (c) a visible <h2>/<h3>/<h4> in the immediate parent container
 *       (sibling-header pattern).
 *
 * Rationale: some projects title charts via Plotly layout, others via an
 * HTML header adjacent to the chart div. Either is fine; neither is not.
 *
 * @charts Catches charts shipped without any title — impossible for a
 *         reader to know what they're looking at. See anti-pattern catalog
 *         in SKILLS/visual-lint.md.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} [selector='.js-plotly-plot']
 */
async function assertChartHasTitle(page, selector = '.js-plotly-plot') {
  const offenders = await page.evaluate((selector) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];

      // (a) Plotly layout.title.text
      let plotlyTitle = null;
      if (el.layout && el.layout.title) {
        if (typeof el.layout.title === 'string') plotlyTitle = el.layout.title;
        else if (typeof el.layout.title.text === 'string') plotlyTitle = el.layout.title.text;
      }
      if (plotlyTitle && plotlyTitle.trim().length > 0) continue;

      // (b) header inside the chart element itself
      const inside = el.querySelector('h2, h3, h4');
      if (inside && (inside.innerText || '').trim().length > 0) continue;

      // (c) header in the parent container (sibling pattern)
      let header = null;
      const parent = el.parentElement;
      if (parent) {
        const cand = parent.querySelector('h2, h3, h4');
        if (cand && (cand.innerText || '').trim().length > 0) header = cand;
      }
      if (header) continue;

      out.push({
        index: i,
        id: el.id || null,
        cls: typeof el.className === 'string' ? el.className.slice(0, 80) : null,
      });
    }
    return out;
  }, selector);

  if (offenders.length > 0) {
    const lines = offenders.map(o =>
      `  chart[${o.index}] id="${o.id || ''}" cls="${o.cls || ''}" — missing title`
    ).join('\n');
    throw new Error(
      `assertChartHasTitle: ${offenders.length} chart(s) matching "${selector}" have no Plotly title and no <h2>/<h3>/<h4> in or around the container:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 11. assertChartAxesLabeled
// ---------------------------------------------------------------------------

/**
 * Every matching chart has non-empty `layout.xaxis.title.text` and
 * `layout.yaxis.title.text` (controlled by `requireX` / `requireY`). Chart
 * types that legitimately omit an axis (pie, donut, sunburst) should be
 * filtered via the selector, or opt out via flags per call.
 *
 * @charts Catches charts where the axis exists but has no label — reader
 *         has to guess the units. See anti-pattern catalog in
 *         SKILLS/visual-lint.md.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} [selector='.js-plotly-plot']
 * @param {{requireX?: boolean, requireY?: boolean}} [opts]
 */
async function assertChartAxesLabeled(page, selector = '.js-plotly-plot', opts = {}) {
  const requireX = opts.requireX !== false;
  const requireY = opts.requireY !== false;

  const offenders = await page.evaluate(({ selector, requireX, requireY }) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      const layout = el.layout || {};
      const missing = [];

      const readAxis = (ax) => {
        const a = layout[ax];
        if (!a) return null;
        if (typeof a.title === 'string') return a.title;
        if (a.title && typeof a.title.text === 'string') return a.title.text;
        return null;
      };

      if (requireX) {
        const t = readAxis('xaxis');
        if (!t || !t.trim()) missing.push('xaxis');
      }
      if (requireY) {
        const t = readAxis('yaxis');
        if (!t || !t.trim()) missing.push('yaxis');
      }

      if (missing.length > 0) {
        out.push({
          index: i,
          id: el.id || null,
          cls: typeof el.className === 'string' ? el.className.slice(0, 80) : null,
          missing,
        });
      }
    }
    return out;
  }, { selector, requireX, requireY });

  if (offenders.length > 0) {
    const lines = offenders.map(o =>
      `  chart[${o.index}] id="${o.id || ''}" cls="${o.cls || ''}" — missing axis label: ${o.missing.join(', ')}`
    ).join('\n');
    throw new Error(
      `assertChartAxesLabeled: ${offenders.length} chart(s) matching "${selector}" missing required axis title(s):\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 12. assertChartCategoriesComplete — declarative API
// ---------------------------------------------------------------------------

/**
 * Declarative chart-completeness check. `declarations` is the parsed
 * contents of a project's `.charts.yaml` (see
 * helpers/charts-declarations.template.yaml for the schema). For each
 * declared chart the function:
 *
 *   1. locates the chart by `selector` (FAIL if not found),
 *   2. reads `gd.data` and `gd.layout` on the Plotly element,
 *   3. verifies every `expected_categories` value appears on the chart's
 *      categorical axis (x by default; y if any trace has orientation:'h'),
 *   4. verifies total distinct series count >= `expected_series_min`,
 *   5. verifies each expected category has >= `data_points_per_category_min`
 *      non-null points summed across traces,
 *   6. (optional) verifies title/axis-label presence per the chart's
 *      `require_title` / `require_x_axis_label` / `require_y_axis_label` flags.
 *
 * Direct catcher for the 2026-04-17 "Hazard by LTV band" live-site bug —
 * chart rendered with only one of four LTV bands populated because of an
 * upstream unit-scaling collision. Had the project declared the four
 * expected categories, this assertion would have failed the QA gate.
 *
 * @charts Catches silently-collapsed categorical distributions. See
 *         anti-pattern catalog entry "Chart categories silently collapsed
 *         to one due to upstream unit-scaling bug" in SKILLS/visual-lint.md.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{charts: Object<string, {selector: string, description?: string,
 *          expected_categories?: string[], expected_series_min?: number,
 *          data_points_per_category_min?: number,
 *          require_title?: boolean, require_x_axis_label?: boolean,
 *          require_y_axis_label?: boolean}>}} declarations
 */
async function assertChartCategoriesComplete(page, declarations) {
  if (!declarations || typeof declarations !== 'object' || !declarations.charts) {
    throw new Error('assertChartCategoriesComplete: declarations.charts is required (parsed .charts.yaml)');
  }

  const entries = Object.entries(declarations.charts).map(([id, spec]) => ({ id, spec }));
  if (entries.length === 0) return;

  const report = await page.evaluate((entries) => {
    const findings = [];
    for (const { id, spec } of entries) {
      const el = document.querySelector(spec.selector);
      if (!el) {
        findings.push({ id, selector: spec.selector, kind: 'not-found' });
        continue;
      }
      const data = Array.isArray(el.data) ? el.data : [];
      const layout = el.layout || {};

      // Detect horizontal orientation: any trace with orientation: 'h'.
      const isHorizontal = data.some(t => t && t.orientation === 'h');
      const categoryAxis = isHorizontal ? 'y' : 'x';
      const valueAxis = isHorizontal ? 'x' : 'y';

      // Collect category values across traces on the relevant axis.
      const renderedCategories = new Set();
      const pointsByCategory = {};
      const seriesNames = new Set();

      for (const trace of data) {
        if (!trace) continue;
        if (trace.name) seriesNames.add(String(trace.name));
        const cats = trace[categoryAxis];
        const vals = trace[valueAxis];
        if (!Array.isArray(cats)) continue;
        for (let i = 0; i < cats.length; i++) {
          const c = String(cats[i]);
          renderedCategories.add(c);
          const v = Array.isArray(vals) ? vals[i] : undefined;
          const isValidPoint = v !== null && v !== undefined && !(typeof v === 'number' && Number.isNaN(v));
          if (isValidPoint) {
            pointsByCategory[c] = (pointsByCategory[c] || 0) + 1;
          }
        }
      }

      const expected = Array.isArray(spec.expected_categories) ? spec.expected_categories : [];
      const seriesMin = typeof spec.expected_series_min === 'number' ? spec.expected_series_min : 1;
      const pointsMin = typeof spec.data_points_per_category_min === 'number' ? spec.data_points_per_category_min : 1;

      const missingCategories = expected.filter(c => !renderedCategories.has(String(c)));
      const emptyCategories = expected.filter(c =>
        renderedCategories.has(String(c)) && (pointsByCategory[String(c)] || 0) < pointsMin
      );
      const seriesCount = seriesNames.size || data.length;

      // Hygiene flags (default true, can be overridden).
      const requireTitle = spec.require_title !== false;
      const requireX = spec.require_x_axis_label !== false;
      const requireY = spec.require_y_axis_label !== false;

      const titleText = layout.title
        ? (typeof layout.title === 'string' ? layout.title : (layout.title.text || ''))
        : '';
      const xTitle = (layout.xaxis && (typeof layout.xaxis.title === 'string'
        ? layout.xaxis.title
        : (layout.xaxis.title && layout.xaxis.title.text))) || '';
      const yTitle = (layout.yaxis && (typeof layout.yaxis.title === 'string'
        ? layout.yaxis.title
        : (layout.yaxis.title && layout.yaxis.title.text))) || '';

      const problems = [];
      if (missingCategories.length > 0) problems.push(`missing categories: ${JSON.stringify(missingCategories)}`);
      if (emptyCategories.length > 0) problems.push(`empty categories (< ${pointsMin} point(s)): ${JSON.stringify(emptyCategories)}`);
      if (seriesCount < seriesMin) problems.push(`series count ${seriesCount} < expected_series_min ${seriesMin}`);
      if (requireTitle && !String(titleText).trim()) problems.push('missing chart title');
      if (requireX && !String(xTitle).trim()) problems.push('missing xaxis title');
      if (requireY && !String(yTitle).trim()) problems.push('missing yaxis title');

      if (problems.length > 0) {
        findings.push({
          id,
          selector: spec.selector,
          description: spec.description || null,
          kind: 'incomplete',
          problems,
          rendered: Array.from(renderedCategories),
          seriesCount,
        });
      }
    }
    return findings;
  }, entries);

  if (report.length > 0) {
    const lines = report.map(r => {
      if (r.kind === 'not-found') {
        return `  [${r.id}] selector "${r.selector}" — CHART NOT FOUND ON PAGE`;
      }
      return `  [${r.id}] ${r.description || ''}\n    selector: ${r.selector}\n    rendered categories: ${JSON.stringify(r.rendered)}\n    series count: ${r.seriesCount}\n    problems:\n      - ${r.problems.join('\n      - ')}`;
    }).join('\n');
    throw new Error(
      `assertChartCategoriesComplete: ${report.length} declared chart(s) failed completeness checks:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 13. assertLegendNotClipped
// ---------------------------------------------------------------------------

/**
 * Read Plotly's legend bounding rect and confirm it sits fully inside the
 * chart container's bounding rect. Fails if the legend:
 *   - has any edge outside the container, or
 *   - overlaps the plot-area (g.cartesianlayer / g.plot) by > 4px on
 *     both width and height — indicates a legend-on-top-of-bars accident.
 *
 * @charts Catches charts where the legend runs off the right edge of the
 *         card / dashboard column, or sits on top of the bars because the
 *         legend-position default collided with a narrow container. See
 *         anti-pattern catalog in SKILLS/visual-lint.md.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} [selector='.js-plotly-plot']
 */
async function assertLegendNotClipped(page, selector = '.js-plotly-plot') {
  const offenders = await page.evaluate((selector) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      const legend = el.querySelector('g.legend');
      if (!legend) continue;  // no legend to check
      const lr = legend.getBoundingClientRect();
      if (lr.width === 0 && lr.height === 0) continue;  // hidden / zero-size

      const cr = el.getBoundingClientRect();
      const EPS = 1;
      const outside = {
        left: lr.left < cr.left - EPS,
        right: lr.right > cr.right + EPS,
        top: lr.top < cr.top - EPS,
        bottom: lr.bottom > cr.bottom + EPS,
      };

      // Plot-area overlap check.
      const plotArea = el.querySelector('g.cartesianlayer') || el.querySelector('g.plot');
      let overlap = null;
      if (plotArea) {
        const pr = plotArea.getBoundingClientRect();
        const overlapW = Math.max(0, Math.min(lr.right, pr.right) - Math.max(lr.left, pr.left));
        const overlapH = Math.max(0, Math.min(lr.bottom, pr.bottom) - Math.max(lr.top, pr.top));
        if (overlapW > 4 && overlapH > 4) {
          overlap = { w: Math.round(overlapW), h: Math.round(overlapH) };
        }
      }

      const clipped = outside.left || outside.right || outside.top || outside.bottom;
      if (clipped || overlap) {
        out.push({
          index: i,
          id: el.id || null,
          cls: typeof el.className === 'string' ? el.className.slice(0, 80) : null,
          legendRect: { l: Math.round(lr.left), t: Math.round(lr.top), r: Math.round(lr.right), b: Math.round(lr.bottom) },
          containerRect: { l: Math.round(cr.left), t: Math.round(cr.top), r: Math.round(cr.right), b: Math.round(cr.bottom) },
          outside,
          overlap,
        });
      }
    }
    return out;
  }, selector);

  if (offenders.length > 0) {
    const lines = offenders.map(o => {
      const edges = Object.entries(o.outside).filter(([, v]) => v).map(([k]) => k);
      const parts = [];
      if (edges.length) parts.push(`legend clipped on edge(s): ${edges.join(', ')}`);
      if (o.overlap) parts.push(`legend overlaps plot-area (${o.overlap.w}x${o.overlap.h}px)`);
      return `  chart[${o.index}] id="${o.id || ''}" cls="${o.cls || ''}" — ${parts.join('; ')}\n    legend=${JSON.stringify(o.legendRect)} container=${JSON.stringify(o.containerRect)}`;
    }).join('\n');
    throw new Error(
      `assertLegendNotClipped: ${offenders.length} chart(s) with clipped / overlapping legend:\n${lines}`
    );
  }
}

// ---------------------------------------------------------------------------
// 14. assertNoChartOverflow
// ---------------------------------------------------------------------------

/**
 * For each matching chart, verify its rendered SVG (or canvas) does not
 * extend past its parent container on any edge. Overflow typically means
 * clipped axis labels or clipped data at the extremes — the chart looks
 * fine on desktop but chops at 390px mobile.
 *
 * @charts Catches charts that overflow their card / grid cell on narrow
 *         viewports. See anti-pattern catalog in SKILLS/visual-lint.md.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} [selector='.js-plotly-plot']
 */
async function assertNoChartOverflow(page, selector = '.js-plotly-plot') {
  const offenders = await page.evaluate((selector) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const out = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      const parent = el.parentElement;
      if (!parent) continue;

      const svg = el.querySelector('svg.main-svg') || el.querySelector('svg') || el.querySelector('canvas');
      if (!svg) continue;

      const sr = svg.getBoundingClientRect();
      const pr = parent.getBoundingClientRect();
      const EPS = 1;

      const edges = {
        left: sr.left < pr.left - EPS ? Math.round(pr.left - sr.left) : 0,
        right: sr.right > pr.right + EPS ? Math.round(sr.right - pr.right) : 0,
        top: sr.top < pr.top - EPS ? Math.round(pr.top - sr.top) : 0,
        bottom: sr.bottom > pr.bottom + EPS ? Math.round(sr.bottom - pr.bottom) : 0,
      };
      const overflowed = Object.entries(edges).filter(([, px]) => px > 0);
      if (overflowed.length > 0) {
        out.push({
          index: i,
          id: el.id || null,
          cls: typeof el.className === 'string' ? el.className.slice(0, 80) : null,
          edges: Object.fromEntries(overflowed),
        });
      }
    }
    return out;
  }, selector);

  if (offenders.length > 0) {
    const lines = offenders.map(o => {
      const pairs = Object.entries(o.edges).map(([k, v]) => `${k}=+${v}px`).join(', ');
      return `  chart[${o.index}] id="${o.id || ''}" cls="${o.cls || ''}" — overflowed parent: ${pairs}`;
    }).join('\n');
    throw new Error(
      `assertNoChartOverflow: ${offenders.length} chart(s) matching "${selector}" extend past their parent container:\n${lines}`
    );
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
  // Chart hygiene (2026-04-17 follow-on to f23153f)
  assertChartHasTitle,
  assertChartAxesLabeled,
  assertChartCategoriesComplete,
  assertLegendNotClipped,
  assertNoChartOverflow,
};
