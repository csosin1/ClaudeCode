# Visual Lint — three-layer visual QA

## When to use

Any task that ships or modifies UI: HTML templates, CSS, JS that affects rendering, a new dashboard, a restyled tab, a swapped chart library. If the user would see a pixel change, visual-lint runs.

Does **not** apply to: pure data-layer changes (ETL, schema, cron that produces JSON), backend-only services, docs, non-UI scripts. Those have their own QA layers.

## The three-layer architecture

```
  ┌──────────────────────────────────────────────────────────┐
  │  B-plus  — deterministic DOM/CSS + axe-core rules        │
  │           fast, free, catches ~80% of visual bugs        │
  │           helpers/visual-lint.js + visual-lint-axe.js    │
  └──────────────────────────────────────────────────────────┘
                              │
                    diff passes → screenshots
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  A-llm  — dual visual-reviewer agents (briefed +          │
  │           unbriefed), both with identical REVIEW_CONTEXT  │
  │           catches novel bugs + aesthetic issues           │
  │           .claude/agents/visual-reviewer.md               │
  │           helpers/visual-review-orchestrator.sh           │
  └──────────────────────────────────────────────────────────┘
                              │
              A-llm findings with deterministic_candidate:true
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  Feedback loop — promote recurring A-llm findings into    │
  │                  new B-plus rules. Over time B-plus       │
  │                  thickens, A-llm cost stays flat.         │
  └──────────────────────────────────────────────────────────┘
```

**Why both layers.** Deterministic rules are free and instant but blind to novel bug classes. LLM review catches anything a human would notice but costs tokens and can hallucinate. Running both — and promoting the LLM's pattern-recognition into deterministic rules over time — compounds: the system gets cheaper and sharper month over month.

## B-plus deterministic layer

Named exports in `helpers/visual-lint.js`. Import into `tests/<project>.spec.ts` and call inside test bodies.

| Function | Catches |
|---|---|
| `assertNoRawHtmlEntities(page)` | Un-escaped entities (`&mdash;`, `&amp;`) leaking into rendered text — e.g. Plotly text fields where the template passed HTML instead of plain text. Motivated by 2026-04-17 Methodology incident. |
| `assertNoEmptyCharts(page, {selector, minDataPoints})` | Charts that render a container but have zero data points. Reads `gd.data` directly on Plotly elements; falls back to counting SVG primitives + text for generic charts. Motivated by the LTV-bucketing unit-mismatch incident. |
| `assertNoScrollTraps(page, {maxScrollableHeight, tableSelector})` | `overflow: auto\|scroll` + small `max-height` around a taller child → scroll-trap. Motivated by the Methodology footer trap. |
| `assertNoContentPlaceholders(page)` | Literal `NaN`, `undefined`, `null`, `{{template}}`, `[object Object]`, `TODO`, `FIXME`, `Lorem ipsum` in rendered text. |
| `assertAllImagesLoaded(page)` | Broken `<img>` src (complete=false or naturalHeight=0). |
| `assertNoConsoleErrors(page, [action])` | Any `pageerror` or `console.error` during the test window. Use the `attachConsoleErrorCollector` form if you need to span async work. |
| `assertNoNetworkFailures(page, [action])` | Any ≥400 response on non-analytics subresources. |
| `assertCriticalElementsInViewport(page, selectors[])` | Elements pushed below the fold by layout shift (`rect.bottom > viewport.height`). |
| `assertContrast(page, minRatio)` | Thin delegate to axe-core's `color-contrast` rule. |

**axe-core integration** lives in `helpers/visual-lint-axe.js`:

```js
const { runAxe } = require('/opt/site-deploy/helpers/visual-lint-axe.js');
await runAxe(page, { excluded: ['region'] });  // excluded rules don't run
```

`runAxe` pulls the full axe-core rule set — ~90 rules covering WCAG 2.1 AA, ARIA correctness, landmark structure, form labelling, image alternatives, link semantics, and keyboard/focus order. See https://dequeuniversity.com/rules/axe/ for the full list. It's the canonical implementation of WCAG contrast math; don't roll your own.

## Chart hygiene

The initial B-plus rules cover the "renders properly" pillar well (empty-chart detection via Plotly `gd.data`, axe-core a11y, entity/placeholder scans). Chart QA has two more pillars the generic rules can't reach on their own:

- **Accurate data** — is what the chart shows actually what the data says? Partially covered by `assertNoEmptyCharts`, but it can't know a chart SHOULD have four LTV bands vs two vs seven. That requires the project to declare its expectations.
- **Displayed usefully** — title present? axes labeled? legend not clipped? SVG not overflowing the card at 390px? All generic, all chartable as deterministic rules.

The chart-hygiene extensions close both gaps. Added 2026-04-17 as a follow-on to the initial visual QA system (commit `f23153f`), motivated by the live-site "Hazard by LTV band" bug where three of four bands rendered empty due to an upstream unit-scaling collision, caught only when the user sent a screenshot.

### The five chart-hygiene assertions

| Function | Catches |
|---|---|
| `assertChartHasTitle(page, selector)` | Chart shipped without a title — reader can't tell what it shows. Accepts Plotly `layout.title.text`, an `<h2>/<h3>/<h4>` inside the chart element, or a sibling header in the parent container. |
| `assertChartAxesLabeled(page, selector, {requireX, requireY})` | Axis present but label missing. Default requires both; pass `{requireX: false}` for horizontal bars where the y-axis is the category, etc. |
| `assertChartCategoriesComplete(page, declarations)` | The declarative API — see below. Direct catcher for silently-collapsed categorical distributions. |
| `assertLegendNotClipped(page, selector)` | Legend runs off the container's right/bottom edge, or overlaps the plot area (legend-on-bars accident). |
| `assertNoChartOverflow(page, selector)` | Chart's SVG extends past its parent container — clipped labels / chopped extremes, usually on 390px mobile. |

### The `.charts.yaml` declarative schema

A generic "chart is not empty" check is blind to the shape a chart should have. The `.charts.yaml` file lets the project declare, per chart, what reality should look like. Schema lives at `helpers/charts-declarations.template.yaml`:

```yaml
charts:
  "5b_hazard_by_ltv":
    selector: "#chart-5b .js-plotly-plot"
    description: "Monthly default hazard (bps) by LTV band, by issuer tier"
    expected_categories: ["<80%", "80-99%", "100-119%", "120%+"]
    expected_series_min: 2
    data_points_per_category_min: 1
    require_title: true
    require_x_axis_label: true
    require_y_axis_label: true
```

`assertChartCategoriesComplete` reads `gd.data` and `gd.layout`, then for each declared chart verifies: every `expected_categories` value is present on the categorical axis; every expected category has at least `data_points_per_category_min` non-null points summed across traces; total distinct series count is at least `expected_series_min`; and (optionally) the title / axis labels per the hygiene flags. Any failure throws with a listing of which chart, which categories went missing, and what was rendered instead.

### How to author a good `.charts.yaml` entry

Worked example — the 2026-04-17 Hazard-by-LTV bug:

1. **Pick a stable id** — `5b_hazard_by_ltv`, not `chart-3`. This id shows up in QA logs; you want it meaningful.
2. **Selector must be specific** — `#chart-5b .js-plotly-plot` beats `.js-plotly-plot:nth-of-type(12)`. Ids survive reorders; positional selectors don't.
3. **`expected_categories` is the load-bearing field** — exactly the labels the reader should see on the axis. If the chart is `["<80%", "80-99%", "100-119%", "120%+"]`, declare all four. A chart collapsing to just `["<80%"]` fails the assertion with a clear "missing categories: [\"80-99%\", \"100-119%\", \"120%+\"]" message.
4. **`expected_series_min: 2`** — for a multi-line chart, declaring the minimum catches the case where all but one tier silently drop out.
5. **`data_points_per_category_min: 1`** — the stricter guardrail. An expected category that exists on the axis but has zero data points (the exact Hazard-by-LTV bug) fails here.

Adopt incrementally: start by declaring the two or three most investor-visible charts. The declaration is cheap — three to eight lines per chart — and catches a bug class that otherwise only surfaces via screenshots.

## A-llm semantic layer

Two subagents per page × viewport, dispatched in parallel by `helpers/visual-review-orchestrator.sh`:

- **unbriefed** — gets `REVIEW_CONTEXT.md` + screenshot. Looks for anything that seems wrong with fresh eyes.
- **briefed** — gets the above PLUS a writing agent's change-specific brief. Verifies the claimed change took effect and scans for collateral damage.

Both emit the same findings schema (see `.claude/agents/visual-reviewer.md` for the strict spec):

```json
{
  "findings": [
    {
      "category": "contrast | layout | content | loading | consistency | aesthetic | semantic | other",
      "severity": "HALT | WARN | INFO",
      "description": "…",
      "page": "/methodology",
      "viewport": "390",
      "deterministic_candidate": true,
      "suggested_rule": "…one-line sketch…"
    }
  ],
  "overall_verdict": "PASS | PASS_WITH_NOTES | FAIL",
  "reviewed_with_brief": true
}
```

**Severity guide.**

- **HALT** — would embarrass at the Accept gate. Fails the QA gate.
- **WARN** — worth fixing; doesn't block ship.
- **INFO** — nit; suppressed entirely for utility-grade projects.

The orchestrator appends every finding to `/var/log/<project>-visual-review.jsonl` (append-only history) and exits 1 if any HALT is present.

## Project context (REVIEW_CONTEXT.md)

Per-project file owned by the project chat. Five fields calibrate the reviewer:

1. **Purpose** — what the project is, who uses it.
2. **Audience** — external / investor / internal / public showcase.
3. **What correctness means here** — project-specific: numbers traceable to source, disclaimer requirements, freshness windows.
4. **Red-flag patterns** — hard-HALT list. "No loan-level PII." "No forward-looking claims without disclaimer."
5. **Aesthetic bar** — investor-grade polish vs utility-grade vs playful. Without this, the reviewer applies the wrong standard and you get either useless nitpicks or missed polish issues.
6. **Known exceptions** — things that look like bugs but are intentional. E.g. "NULL cells in CarMax 2014-2015 data are source-faithful." Prevents false-positive HALTs.

The template lives at `helpers/review-context.template.md`. New project chat copies it to `/opt/<project>/REVIEW_CONTEXT.md` and fills in.

**Calibration is load-bearing.** A utility research tool doesn't need investor polish; an investor page can't ship with a research-notebook aesthetic. Getting this wrong wastes tokens on noise or misses real issues.

## Feedback loop

A-llm findings with `deterministic_candidate: true` are signals. Each includes a `suggested_rule` — the reviewer's one-line sketch of how a DOM/CSS assertion could catch this class.

**Weekly review cadence** (tracked in daily reflection; see `SKILLS/daily-reflection.md`):

1. Dump the week's findings: `jq 'select(.findings[]? | .deterministic_candidate==true)' /var/log/*-visual-review.jsonl`
2. Group by `suggested_rule` similarity.
3. Promote on two criteria:
   - **Recurrence**: the same rule appeared in ≥2 independent findings → add to `visual-lint.js` and backfill an anti-pattern catalog entry.
   - **High severity**: a single HALT with a clean deterministic shape → promote immediately.
4. Aesthetic one-offs stay in A-llm's domain; those are the class of thing that resists rule-ification by nature.

Every new rule lands with (a) its JS function, (b) an entry in the anti-pattern catalog below, (c) a LESSONS.md pointer if the rule was prompted by a production incident.

## Adoption for a project

Concrete steps for a new project chat adopting visual-lint:

1. **Install axe-core as a devDep**:
   ```
   npm install --save-dev @axe-core/playwright
   ```
   (Infra does NOT install this globally. Projects pin their own version.)

2. **Write `REVIEW_CONTEXT.md`**:
   ```
   cp /opt/site-deploy/helpers/review-context.template.md /opt/<project>/REVIEW_CONTEXT.md
   $EDITOR /opt/<project>/REVIEW_CONTEXT.md
   ```
   Fill in all five sections. One-line entries are fine; leaving a section blank defeats calibration.

3. **Add visual-lint calls to the spec**. Minimum starter set:
   ```ts
   import {
     assertNoRawHtmlEntities,
     assertNoContentPlaceholders,
     assertNoConsoleErrors,
     assertAllImagesLoaded,
   } from '/opt/site-deploy/helpers/visual-lint.js';
   import { runAxe } from '/opt/site-deploy/helpers/visual-lint-axe.js';

   test('visual lint - dashboard', async ({ page }) => {
     const consoleCheck = attachConsoleErrorCollector(page);
     await page.goto('/dashboard');
     await assertAllImagesLoaded(page);
     await assertNoRawHtmlEntities(page);
     await assertNoContentPlaceholders(page);
     await runAxe(page, { excluded: ['region'] });
     await consoleCheck();
   });
   ```

4. **Create `.charts.yaml` with declarations for every production chart**:
   ```
   cp /opt/site-deploy/helpers/charts-declarations.template.yaml /opt/<project>/.charts.yaml
   $EDITOR /opt/<project>/.charts.yaml
   ```
   Declare every user-facing chart: selector, expected_categories, expected_series_min, data_points_per_category_min. This is the load-bearing piece of the "accurate data" pillar — the generic `assertNoEmptyCharts` check cannot know the shape a chart should have. Then in the spec:
   ```ts
   import yaml from 'js-yaml';
   import fs from 'fs';
   import { assertChartCategoriesComplete, assertChartHasTitle,
            assertChartAxesLabeled, assertLegendNotClipped,
            assertNoChartOverflow } from '/opt/site-deploy/helpers/visual-lint.js';

   const declarations = yaml.load(fs.readFileSync('/opt/<project>/.charts.yaml', 'utf8'));
   await assertChartCategoriesComplete(page, declarations);
   await assertChartHasTitle(page);
   await assertChartAxesLabeled(page);
   await assertLegendNotClipped(page);
   await assertNoChartOverflow(page);
   ```

5. **Wire the A-llm orchestrator into `qa.yml`** (after the deterministic tests pass):
   ```yaml
   - name: Visual review (A-llm layer)
     run: |
       bash /opt/site-deploy/helpers/visual-review-orchestrator.sh \
         <project> /opt/<project>/REVIEW_CONTEXT.md \
         /opt/<project>/.perf.yaml
   ```

6. **Worked example — carvana-abs-2**:
   - `REVIEW_CONTEXT.md` declares "investor-grade polish; no loan-level PII ever; numbers must trace to SEC 10-K filings."
   - Spec calls all six starter functions + `assertNoEmptyCharts` + `assertNoScrollTraps` (both motivated by the Methodology incident).
   - qa.yml runs the orchestrator against `.perf.yaml` (already declares the relevant pages × viewports).
   - First run finds three HALTs: raw entities, collapsed heatmap, scroll trap — exactly the Methodology bugs.

## Anti-pattern catalog

Growing section. Each entry: symptom → detection → fix pattern → LESSONS link.

### 1. HTML entities in Plotly text fields

- **Symptom**: chart titles/subtitles render literal `&mdash;`, `&hellip;`, `&amp;` instead of the intended glyph.
- **Detection**: `assertNoRawHtmlEntities(page)` — walks text nodes outside `<code>/<pre>/<script>/<style>/<noscript>` and regex-scans for `&[a-z]+;` or numeric entities.
- **Fix**: pass plain text (or the actual unicode glyph) to Plotly's `text`/`title` fields. Plotly accepts a narrow HTML subset but many fields expect plain text and will render entities literally. Decode at the template boundary, not inside Plotly.
- **LESSONS**: 2026-04-17 abs-dashboard Methodology incident.

### 2. Unit-mismatched bucketing producing collapsed distributions

- **Symptom**: heatmap/histogram renders but all values fall into a single bucket — the chart is one solid cell.
- **Detection**: `assertNoEmptyCharts(page, {minDataPoints: N})` with an N that reflects the chart's expected shape; for heatmaps set `minDataPoints: rows * cols` and the helper will fail when the data collapses.
- **Fix**: align bucket edge units with the source column. LTV in the source was fraction (0.75) but bucket edges were percent (75–85). A single unit-test that asserts `max(data) <= max(bucket_edges)` on the producer side prevents this permanently.
- **LESSONS**: 2026-04-17 abs-dashboard Methodology incident.

### 3. `overflow: auto` + `max-height` on table wrappers → scroll trap

- **Symptom**: as the user scrolls down, page scroll stops; scrolling inside the wrapped table advances the table's own scroll until the user gets stuck.
- **Detection**: `assertNoScrollTraps(page)` — finds any scrollable ancestor with client-height below threshold (default 30vh) wrapping a taller child.
- **Fix**: remove `overflow: auto` + `max-height` from the wrapper; let the table render at its natural height, or replace with pagination / virtualized scrolling. If scroll-capture is truly desired, make it explicit with `overscroll-behavior: contain` and a visible scroll affordance.
- **LESSONS**: 2026-04-17 abs-dashboard Methodology incident.

### 4. Chart categories silently collapsed to one due to upstream unit-scaling bug

- **Symptom**: categorical chart renders with the correct x-axis tick labels (e.g. `<80%`, `80-99%`, `100-119%`, `120%+`) but only the first band has data; the other three are visually empty. The chart looks "fine" in isolation — no empty-container signal, no console error, no zero-sized element — because Plotly still draws the axis ticks even when the underlying `trace.x`/`trace.y` for those categories collapsed during upstream aggregation. Generic "chart not empty" checks pass because there IS data for one band.
- **Detection**: `assertChartCategoriesComplete(page, declarations)` against a `.charts.yaml` entry that declares all four expected categories and `data_points_per_category_min: 1`. The assertion fails with `empty categories: ["80-99%", "100-119%", "120%+"]` pointing directly at the regression. The generic `assertNoEmptyCharts` alone cannot catch this — it has no way to know the chart should have four bands rather than one.
- **Fix pattern**: audit upstream data-unit assumptions at the producer seam. The 2026-04-17 root cause was LTV stored as a fraction (0.82) in one pipeline stage and as a percent (82) in the bucketing function; the edge values `(80, 100, 120)` filtered all 99%+ of rows into a single bucket. Unit-test the producer with a property check: for every bucket in `bucket_edges`, at least one row from a representative sample should land in it. Combine with the declarative chart-side assertion so a regression at either layer fails QA.
- **LESSONS**: 2026-04-17 live-site Hazard-by-LTV incident (caught via user screenshot, not QA). The motivating case for commit `f23153f`'s chart-hygiene follow-on.

## Cost expectations

Per review pass (one project, ~5 pages, 2 viewports, briefed + unbriefed):

- ~10 Claude-Sonnet calls, each ~6k tokens input (screenshot + REVIEW_CONTEXT + brief) + ~400 tokens output.
- Per-pass cost: roughly $0.20–$0.40.
- Ships per month per project with UI changes: typically 10–20.
- **Monthly per project: ~$4–$8 in tokens.**

Cost scales with UI-touching ship count, not total ship count. Data-only releases are free. The deterministic B-plus layer runs on every push regardless; its cost is CI minutes only.

## What this system does NOT catch

Honest limits:

- **Domain-specific aesthetic judgment** that requires product context the reviewer doesn't have. A subtle branding inconsistency only the product owner would notice.
- **Non-visual bugs** — data correctness is `SKILLS/data-audit-qa.md`'s job; performance is perceived-latency's; functional correctness is Playwright spec.
- **Novel bug classes we haven't anticipated** — partially covered by the unbriefed reviewer's "anything broken?" pass, but a truly unprecedented failure mode (say, a font that renders differently on Arabic locales) may slip through.
- **Progressive degradation over weeks** — e.g. a chart that gets 2% more cluttered each ship. Individual-review gates miss long-term drift. Plan: a monthly "compare last vs four-weeks-ago screenshots" pass.

## Integration with other QA layers

```
  functional Playwright     → "clicking X updates Y"
  perceived-latency         → "first paint < 2.5s"
  data-audit                → "numbers trace to sources"
  visual-lint (this SKILL)  → "page looks right"
```

Visual-lint runs after functional and perf in `qa.yml` — no point reviewing a page that didn't load. A failure at any layer blocks promote; the QA summary lists which layer flagged.

## Related skills

- `SKILLS/parallel-execution.md` — the dispatch primitives the orchestrator uses.
- `SKILLS/non-blocking-prompt-intake.md` — a visual review is itself parallelizable; never block the main thread on it.
- `SKILLS/daily-reflection.md` — where the weekly B-plus promotion review lives.
- `SKILLS/data-audit-qa.md` — sibling QA layer for numbers.
- `SKILLS/perceived-latency.md` — sibling QA layer for load timing.
- `SKILLS/code-hygiene.md` — the reviewer rule that enforces visual-lint adoption on UI diffs.
