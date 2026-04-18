/**
 * visual-lint-axe.js — accessibility / contrast / semantic rule scan
 *
 * Thin wrapper around @axe-core/playwright. Pulls in axe-core's rule
 * set (~90 rules as of 4.10), which covers:
 *   - color-contrast (WCAG AA + AAA variants)
 *   - ARIA correctness (~30 rules: role-allowed-attr, aria-valid-attr-value, ...)
 *   - landmark + heading structure (region, page-has-heading-one, ...)
 *   - form labeling (label, label-title-only, form-field-multiple-labels, ...)
 *   - image alternatives (image-alt, role-img-alt, ...)
 *   - link semantics (link-name, link-in-text-block, ...)
 *   - language + document rules (html-has-lang, document-title, ...)
 *   - keyboard / focus-order + tabindex rules
 *
 * Full rule docs: https://dequeuniversity.com/rules/axe/
 *
 * Project setup requirement:
 *   npm install --save-dev @axe-core/playwright
 *
 * (We do NOT install from this helpers directory. Projects install
 * their own devDependency so version pinning stays with the project.)
 *
 * Usage in a project spec:
 *
 *   import { runAxe } from '/opt/site-deploy/helpers/visual-lint-axe.js';
 *   test('a11y', async ({ page }) => {
 *     await page.goto('/');
 *     await runAxe(page, { excluded: ['region'] });  // e.g. allow missing <main>
 *   });
 */

'use strict';

/**
 * Run a full axe-core scan on the current page.
 *
 * @param {import('@playwright/test').Page} page
 * @param {object} [opts]
 * @param {string[]} [opts.allowed=[]]  — rule IDs whose violations are tolerated
 *                                        (still surfaced in return value, not thrown)
 * @param {string[]} [opts.excluded=[]] — rule IDs to NOT run at all
 * @param {boolean}  [opts.throwOnViolation=true]
 * @returns {Promise<{violations: any[], passes: number, incomplete: number}>}
 */
async function runAxe(page, opts = {}) {
  const allowed = new Set(opts.allowed || []);
  const excluded = opts.excluded || [];
  const throwOnViolation = opts.throwOnViolation !== false;

  let AxeBuilder;
  try {
    // dynamic import so projects that don't install axe-core don't blow up on require
    // (the error message when missing is actionable.)
    ({ default: AxeBuilder } = await import('@axe-core/playwright'));
  } catch (err) {
    throw new Error(
      `runAxe: @axe-core/playwright is not installed in the project. ` +
      `Run: npm install --save-dev @axe-core/playwright\n(underlying error: ${err.message})`
    );
  }

  let builder = new AxeBuilder({ page });
  if (excluded.length > 0) {
    builder = builder.disableRules(excluded);
  }

  const results = await builder.analyze();
  const blocking = results.violations.filter(v => !allowed.has(v.id));

  if (throwOnViolation && blocking.length > 0) {
    const lines = blocking.map(v => {
      const nodeList = v.nodes.slice(0, 3).map(n => {
        const target = Array.isArray(n.target) ? n.target.join(' ') : String(n.target);
        return `      ${target}`;
      }).join('\n');
      const extra = v.nodes.length > 3 ? `\n      ... (+${v.nodes.length - 3} more)` : '';
      return `  [${v.impact || '?'}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n${nodeList}${extra}`;
    }).join('\n');
    throw new Error(
      `runAxe: ${blocking.length} axe-core violation(s):\n${lines}`
    );
  }

  return {
    violations: results.violations,
    passes: results.passes.length,
    incomplete: results.incomplete.length,
  };
}

module.exports = { runAxe };
