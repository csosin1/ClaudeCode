---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Perceived Latency QA

## When to use

Use this skill when working on perceived latency qa. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Functional correctness is table stakes; the user judges by how the page *feels*.** A dashboard that returns correct numbers but takes 6 seconds to paint is a broken product. Every QA pass asserts perceived-latency budgets alongside functional assertions — a slow page fails QA just as surely as a wrong number does.

## When To Use

- Any task that ships UI, changes page weight, touches the render path, adds charts/widgets, or modifies asset delivery.
- Every project's QA pass — this runs by default, not opt-in.
- After any dependency upgrade that could affect bundle size (fonts, charting lib, framework).
- When the user reports "feels slow," "takes forever to load," or similar qualitative complaints.

## The Three-Category QA Pattern

A single QA pass makes three categories of assertion. All three run in the same Playwright spec, all tagged, all reported together so builders can fan out fixes in parallel.

| Category | What it asserts | Example |
|---|---|---|
| **Functional** | Feature works as specified — correct data, correct flow, no errors. | "Clicking Deals tab shows ≥1 row with non-NaN APR." |
| **Perf** | Measured timings and sizes meet budget. | "LCP < 2.5s on desktop, < 4s on 4G mobile." |
| **UX** | Qualitative feel — skeletons, swap, progressive render, no FOIT. | "Above-fold content visible before fonts.ready resolves." |

Each finding carries its category tag so the orchestrator can group fixes by root cause across categories (e.g. "fix the 5MB inline JSON" closes one perf finding AND two UX findings).

## Halt-Fix-Rerun Loop

Mirrors `SKILLS/data-audit-qa.md`. One upstream defect typically produces many symptoms across all three categories — fix once, re-verify, don't catalogue duplicates.

```
while iteration < MAX_ITERATIONS (default: 10):
    run full QA pass (functional + perf + UX, parallel where possible)
    on first finding in any category:
        stop dispatching new checks
        let in-flight checks drain gracefully
        collect findings surfaced in drain
    if no findings:
        QA PASSES — record and exit
    group findings by probable root cause (across categories)
    fix highest-severity group; one builder per group
    mark symptoms in QA_FINDINGS.md as "resolved pending re-run"
    iteration += 1

if iteration == MAX_ITERATIONS:
    escalate to user — fix isn't fixing the root cause
```

## Thresholds

Core Web Vitals, per viewport + network profile. Sourced from Google's "good / needs-improvement / poor" zones (2024 standard); we require **good** to pass QA.

| Metric | Desktop (cable) | Mobile (4G slow) | Meaning |
|---|---|---|---|
| **LCP** (Largest Contentful Paint) | ≤ 2.5s | ≤ 4.0s | How fast the biggest above-fold element paints. |
| **INP** (Interaction to Next Paint) | ≤ 100ms | ≤ 200ms | How fast the page responds to user input. |
| **CLS** (Cumulative Layout Shift) | ≤ 0.1 | ≤ 0.1 | How much stuff jumps around while loading. |
| **TTFB** (Time to First Byte) | ≤ 800ms | ≤ 1.2s | How fast the server starts streaming. |
| **FCP** (First Contentful Paint) | ≤ 1.8s | ≤ 3.0s | First pixel of meaningful content. |

Zones:
- **Good** (pass): at or below the "good" threshold above.
- **Needs improvement** (warn — reported, does not fail QA): between good and 2× good.
- **Poor** (fail): worse than 2× good.

Headline check: INP ≤ 100ms is a hard fail on any viewport — "instant response" is non-negotiable for interactive elements regardless of network.

## Qualitative Checks ("Does It Feel Fast?")

These are pass/fail booleans — a site that ticks the CWV boxes but fails these still feels broken.

1. **Above-fold interactive elements respond in <100ms.** Buttons, tabs, filter chips — clicking one must show *some* acknowledgement (highlight, skeleton, spinner) within 100ms even if the full result takes longer.
2. **Below-fold slow content shows a skeleton or spinner.** Any element that takes >200ms to render must reserve its space with a placeholder. Blank area + sudden paint is worse than skeleton + smooth paint.
3. **Fonts use `font-display: swap`.** FOIT (flash of invisible text) >100ms is a hard fail. FOUT (flash of unstyled text) is acceptable and required when fonts are slow.
4. **Progressive render, not blocking-render.** The page must stream — above-fold HTML arrives and paints before the full body + JS bundle is downloaded. Inline `<script>` in `<head>` without `async`/`defer`, or giant inline JSON in the document body, are anti-patterns.
5. **No layout shift from late-arriving widgets.** Images/iframes/ads/charts must declare dimensions (width/height attrs or CSS `aspect-ratio`) so their eventual load doesn't jostle content.
6. **Click feedback is immediate.** Every clickable element has a `:active` / `aria-pressed` / visual state that fires on the same frame as the click.

## Standard Fix Playbook

Canonical fixes for the finding patterns we see repeatedly. Prefer these before inventing new approaches.

| Finding | Canonical fix |
|---|---|
| Large HTML body (>500KB) | Stream the shell first; lazy-load below-fold sections via fetch after DOMContentLoaded. Split tab content so only the active tab's HTML is in the initial doc. |
| Inline data blocks render (big `<script>` JSON in doc body) | Move to a separate endpoint; load async post-first-paint with a skeleton placeholder. Hydrate the chart/table when the JSON resolves. |
| Font flash / FOIT | `font-display: swap` on every `@font-face`. `<link rel="preload" as="font" crossorigin>` on the one or two critical weights. Drop weights you don't use. |
| No compression | nginx `gzip_static on;` and/or `brotli_static on;` on the location block. Precompress `.html`/`.js`/`.css`/`.json` at build/deploy time. |
| Missing cache headers | `Cache-Control: public, max-age=31536000, immutable` on fingerprinted static assets; `Cache-Control: no-cache` on the HTML shell so fresh deploys land immediately. |
| Layout shift from late-loading widgets | Reserve dimensions: `width`/`height` attrs on `<img>`/`<iframe>`, CSS `aspect-ratio` on chart containers, fixed `min-height` on skeleton blocks. |
| Main-thread blocking during interaction | Debounce input handlers; move heavy work to `requestIdleCallback` or `requestAnimationFrame`; consider a Web Worker for computation >50ms. |
| Waterfall of sequential requests | `<link rel="preconnect">` on every third-party origin used above fold; `<link rel="prefetch">` for next-likely-nav; parallelize fetches that don't depend on each other. |
| 347 charts rendered on first paint | Render the above-fold N charts eagerly; below-fold charts wait for `IntersectionObserver` entry. Pattern: stub each chart with its final dimensions, swap in real render on-intersect. |
| Heavy JS bundle | Code-split by route/tab; `import()` dynamically on-demand. Tree-shake unused chart types. Prefer small libs (e.g. uPlot over Chart.js for line charts). |

## Content Decomposition Hygiene

The fix playbook above handles "the page is too slow." This section handles the bigger, messier question: **when should one page be several pages instead?** The default SPA ("put everything at `/`, switch views with JS") is a trap once the dashboard grows past a few hundred KB — but splitting badly (one subdomain per view, one route per click) is also wrong. This is the decision framework for getting it right.

### The core tension

Fewer pages means fewer round-trips, one SEO surface, one analytics pageview per visit, and simpler state. More pages means smaller per-page download, URL-as-state for free, natural back/forward, and — critically — shared asset caching across views. Neither shape is universally right. A 50 KB marketing site shouldn't be split; a 6 MB multi-view dashboard shouldn't be one page. The job is matching shape to content.

### Heuristics for when to split

Walk these roughly in order. First match wins:

- **Over budget, no other fix available.** If the combined page exceeds its `.perf.yaml` budget and the playbook fixes (compression, lazy-load, skeleton-swap, code-split) don't close the gap, split. Budget is the forcing function.
- **Independently consulted content.** Reference material, distinct dashboards, tabs the user treats as separate destinations — split into routes. If a user would bookmark tab C and come back to it directly next week, tab C wants its own URL.
- **URL meaningfully identifies the view.** A specific deal, a specific report, a specific time window. That identity belongs in the path, not in JS state. `/deals/ACME-2024-03/` beats `/dashboard?deal=ACME-2024-03` beats `/dashboard#ACME-2024-03`.
- **Sequential, single-task reading.** A checkout flow, a wizard, an article — keep together. Back/forward would be destructive or confusing; the user is in one session with one goal.
- **Guided flows where state is fragile.** A multi-step form where the user has entered data in step 2 and is on step 3 — splitting to real routes means the browser's back button can destroy work. SPA-style with explicit navigation guards wins here.

The mental model: **is this content read together or consulted separately?** Together → one page with progressive disclosure. Separately → routes.

### Route split vs subdomain split

When you decide to split, the next question is path-based (`/app/economics/`, `/app/methodology/`) vs subdomain-based (`economics.app.example.com`, `methodology.app.example.com`). Path-based wins by default:

- One TLS cert, not N. Let's Encrypt renewal touches one name instead of fanning out.
- No CORS surface. Subdomains mean every cross-view fetch becomes a cross-origin request with preflight, cookie-domain rules, and `Access-Control-*` headers to manage.
- Shared browser cache. Same origin → same cache partition → shared JS/CSS/fonts actually hit.
- Simpler dev/preview/live topology. One nginx `server` block, one deploy path, one log file.

Subdomains are justified only when (a) the views are genuinely independent apps with their own release cadence, (b) tenant or security isolation demands origin-level separation, or (c) different teams own different backends and a shared origin would couple them. Absent one of those, the subdomain split is cert sprawl and CORS overhead with no load-time benefit.

Worked example: the carvana-abs dashboard (Apr-18 2026) was a 5.85 MB single-page SPA with five major views — economics, methodology, deals, cohort, portfolio. Five subdomains was rejected (cert sprawl, CORS, no load-time benefit over paths). Five paths under one origin (`/carvana-abs/economics/`, `/carvana-abs/deals/<id>/`, …) was chosen: each page 200–800 KB, shared Plotly/fonts/CSS cached once, URL carries the view identity, back button works.

### Shared-asset caching

The multi-page shape only pays off if shared assets actually cache. This requires two things:

1. **Stable asset names across pages.** If page A loads `plotly-2.27.0.min.js` and page B loads `plotly-2.27.0.min.js`, the browser serves page B's copy from cache on navigation. If build tooling hashes the bundle differently per entry point (`plotly.a3f2.js` vs `plotly.b7e9.js` for the same library), you've accidentally defeated the cache. Use stable, version-pinned names for vendored libs; reserve hash-fingerprinting for your own code that actually changes.
2. **Long-lived cache headers on versioned assets.** `Cache-Control: public, max-age=31536000, immutable` on anything whose URL encodes its version (library files, hashed bundles). The HTML shell stays `no-cache` so deploys land immediately, but the shared library weight amortizes to zero across all subsequent pages.

Together these turn "N pages × M MB each" into "1× M MB first visit + N−1× shell-only subsequent visits."

### URL semantics and state

If the view has a stable identity, put it in the URL. Two wins:

- **State becomes free.** The URL *is* the tab state. No `localStorage`, no query-param reconstruction, no `history.pushState` gymnastics. Navigation is `<a href>`.
- **Sharing, bookmarking, history all work natively.** Paste the URL in Slack, it opens the right view. Back button lands where the user expects. This is what users mean by "a website that works."

Ranking: `/app/view/<id>/` (best — real route, real history entry) > `/app/#view/<id>` (okay — same-page, history works, slightly ugly) > `/app/?view=<id>&tab=deals` (worst — opaque, easy to break). The hash form is an acceptable **Stage 1 quick win** — flip tab state to `#hash` first to fix back/forward and bookmarking in an afternoon — before doing a proper path split in Stage 2. Call out the staging explicitly so nobody thinks the hash version is the final answer.

### Progressive disclosure (the within-page cousin)

Route-splitting is *across-page*. Progressive disclosure is *within-page*: show the most important content first, reveal more on demand via tabs, accordions, "load more" buttons, `IntersectionObserver`-triggered chart renders. Both patterns reduce bytes-before-meaningful-content; they're complementary, not alternatives.

Rule of thumb: if the content is **related** (same report, same dashboard, same user task), use progressive disclosure. If the content is **independent** (different reports, different dashboards, different user tasks), use route splitting. Mixing them is normal — a split route can itself use accordions inside.

### Anticipatory prefetch

Once content is split across routes, you can hide the network cost of navigation by prefetching the next likely page during idle time: `<link rel="prefetch" href="/next-likely-view/">`. By the time the user clicks, the HTML and its critical assets are already in the cache. Click-to-paint feels instant even though real bytes moved over the wire.

When to use: analytics shows a clear "after page A, users usually go to page B" pattern. When to avoid: mobile users on metered connections — prefetched bytes they never use are wasted money, and iOS Safari's cache eviction means the prefetch may not even survive to the click anyway.

### Vocabulary glossary

- **SPA** (Single-Page App): one HTML document, all views rendered via JS routing.
- **MPA** (Multi-Page App): each view is its own HTML document, navigation is real page loads.
- **Route splitting**: breaking an SPA into multiple real URLs (either MPA-style or SPA-with-router), each serving a smaller payload.
- **Code splitting**: breaking one JS bundle into several, loaded on demand via dynamic `import()`. Orthogonal to route splitting but often paired with it.
- **Critical rendering path**: the minimum HTML+CSS+JS the browser must process before it can paint the first meaningful pixel. Smaller = faster first paint.
- **Progressive disclosure**: within one page, show important content first and reveal detail on user interaction.
- **Above/below the fold**: above = visible without scrolling on first paint; below = requires scroll. "Above the fold" content must be in the initial payload; below-fold can lazy-load.
- **Anticipatory prefetch**: speculatively fetching the next-likely-navigation target during idle time so it's cache-warm by click.
- **Shared-asset caching**: multiple pages referencing the same asset URL → browser serves subsequent requests from cache. Requires stable URLs and long `max-age`.
- **URL state**: encoding the current view in the URL path, hash, or query string so navigation, sharing, and back/forward work without JS-only state.

## Escape Hatch: Can't-Fix-Show-Loading-State

Sometimes a page genuinely can't be made sub-2.5s — a 10MB PDF download, a slow upstream API, a large ML inference. When the work genuinely is slow, **show a moving indicator that proves the page isn't frozen**.

**Acceptable progress patterns:**
- Skeleton screen (greyed-out silhouette of the eventual content).
- Indeterminate shimmer (animated gradient across the skeleton — signals activity without lying about progress).
- Determinate progress bar (only if you can report real progress — `bytes loaded / bytes total`, `step 3 of 7`).
- Animated spinner (lowest-quality option — only as a last resort; implies "something is happening" but no scope).

**Unacceptable:**
- Blank white page.
- Frozen UI with no hint that work is in flight.
- Spinner with no text after >3s of no observable progress.
- Fake progress bar that animates to 90% regardless of actual state (erodes trust when the 90%→100% hang becomes obvious).

## Perceived-Latency Patterns

Beyond fixing slowness, these patterns make a fast page feel even faster:

- **Progressive disclosure** — show the critical top-of-page content first, stream the rest. Users read/scan while the below-fold content arrives.
- **Optimistic UI** — when the user clicks "Save," flip the UI state immediately and reconcile on server response. Revert on error with a toast.
- **Anticipatory loading** — `mouseenter` / `focus` on a link kicks off `prefetch` so the click has already started by the time the user commits.
- **Idle-time preloading** — `requestIdleCallback` queues the second-most-likely-next-tab's data so it's cached when the user eventually clicks.
- **Instant-view cache** — serve a cached-but-stale version of the page via `stale-while-revalidate` so return visits paint instantly while fresh data arrives in the background.

## `.perf.yaml` Schema

Each project declares its latency budgets in `/opt/<project>/.perf.yaml`. The template lives at `/opt/site-deploy/helpers/perf-budget.template.yaml`. Per-page stanzas override the `defaults` block. Raising a budget requires a PR with a rationale line in `CHANGES.md` — budgets ratchet down, never up, except by explicit trade-off decision.

Schema (abbreviated — see template for the full commented version):

```yaml
pages:
  "/":
    lcp_desktop_max_ms: 2500
    lcp_mobile_4g_max_ms: 4000
    inp_max_ms: 100
    cls_max: 0.1
    ttfb_max_ms: 800
    above_fold_content_required: true
    below_fold_skeleton_required: true
    font_display_swap_required: true
    progressive_render: true
defaults:
  lcp_desktop_max_ms: 2500
  lcp_mobile_4g_max_ms: 4000
  inp_max_ms: 100
  cls_max: 0.1
  ttfb_max_ms: 800
```

Tab-based SPAs can use per-tab keys (`"/dashboard#deals"`). If a page isn't listed, `defaults` applies.

## Tooling

Two integration options. **Recommended: `playwright-lighthouse`** — it runs a full Lighthouse audit inside a Playwright test, so the measurement environment matches the functional test environment.

### Option A — `playwright-lighthouse` (recommended)

```ts
// tests/<project>.spec.ts
import { test, expect } from '@playwright/test';
import { playAudit } from 'playwright-lighthouse';

test('perf: home page meets budget @perf', async ({ page, browserName }, testInfo) => {
  await page.goto('/');
  await playAudit({
    page,
    thresholds: {
      performance: 90,
      'largest-contentful-paint': 2500,
      'cumulative-layout-shift': 0.1,
      'total-blocking-time': 200,
    },
    port: 9222, // set via --remote-debugging-port in playwright.config.ts
  });
});
```

### Option B — Raw Playwright + `web-vitals`

Inject the `web-vitals` npm library at the page level, collect metrics via `page.evaluate`:

```ts
test('perf: home CWV @perf', async ({ page }) => {
  await page.addInitScript({ path: 'node_modules/web-vitals/dist/web-vitals.iife.js' });
  await page.goto('/');
  const vitals = await page.evaluate(() => new Promise(resolve => {
    const out: Record<string, number> = {};
    (window as any).webVitals.onLCP((m: any) => out.lcp = m.value);
    (window as any).webVitals.onCLS((m: any) => out.cls = m.value);
    (window as any).webVitals.onINP((m: any) => out.inp = m.value);
    setTimeout(() => resolve(out), 5000);
  }));
  expect(vitals.lcp).toBeLessThan(2500);
  expect(vitals.cls).toBeLessThan(0.1);
});
```

Qualitative (UX) checks don't need Lighthouse — they're straight Playwright assertions:

```ts
test('ux: above-fold visible before fonts.ready @ux', async ({ page }) => {
  await page.goto('/');
  const paintedBeforeFonts = await page.evaluate(async () => {
    const headingVisible = !!document.querySelector('h1')?.getBoundingClientRect().height;
    await (document as any).fonts.ready;
    return headingVisible;
  });
  expect(paintedBeforeFonts).toBe(true);
});
```

## Integration With Existing QA Loop

The perceived-latency assertions live **in the same `tests/<project>.spec.ts`** as functional tests — no separate file, no separate workflow. Tags distinguish categories:

- `@functional` (or no tag, default) — feature correctness.
- `@perf` — CWV measurements against `.perf.yaml`.
- `@ux` — qualitative skeleton/swap/progressive-render checks.

`.github/workflows/qa.yml` already runs the full spec at 390px and 1280px on every preview deploy. No workflow change needed — tags let the report group findings by category.

QA loop flow:
1. Push to `main` → preview deploy.
2. `qa.yml` runs `npx playwright test tests/<project>.spec.ts`.
3. Report groups findings: functional / perf / UX.
4. Orchestrator groups *across* categories by probable root cause.
5. Builder fans out fixes — one per root-cause group.
6. Re-run on redeploy.
7. Exit when a full pass is clean across all three categories.

## Report Format

Sample QA output — findings grouped by root cause, each cause showing which findings across all three categories would resolve:

```
QA: <project> preview <commit-sha> <date>
Iterations: 2 (halt-fix-rerun)
Final pass: CLEAN across functional / perf / UX

Iteration 1 findings (3, grouped by root cause):

  RC-1 — 5.2MB inline JSON blocks render
    perf/F-001  LCP 6.1s desktop > 2500ms budget (home, 1280px)
    perf/F-002  TTFB 1.4s > 800ms budget (home, 1280px)
    ux/F-003    above-fold h1 invisible until 5.8s
    Severity: critical  Fix: move JSON to /data/home.json, fetch post-paint + skeleton

  RC-2 — no font-display declaration
    ux/F-004    FOIT 780ms on Inter-Regular
    Severity: high  Fix: font-display: swap + preload

Iteration 2: clean. QA PASSES.
```

## Anti-Patterns

- **Testing perf only in CI with fast hardware.** CI runners are faster than user devices. `playwright-lighthouse` throttles CPU + network by default — don't disable it to "make the tests pass."
- **Raising the budget instead of fixing the regression.** Budgets ratchet down. A regression means the code got slower; fix the code, not the number.
- **Measuring after caches are warm.** First-visit latency is what users experience. Tests run with `page.context().clearCookies()` + `page.goto` cold.
- **Tagging everything `@perf`.** Tag discipline matters for the report. A functional-correctness test tagged `@perf` produces noise in the perf bucket.
- **Ignoring UX findings because CWV passed.** A page can hit all CWV thresholds and still feel broken (invisible text, layout shift below fold that CWV missed because it was outside the viewport window). The three categories are non-overlapping and all required.
- **Treating perceived-latency as post-ship polish.** It's a first-class QA gate, same severity as functional bugs. Shipping a slow page is shipping a broken page.

## Related Skills

- `SKILLS/data-audit-qa.md` — canonical halt-fix-rerun loop shape; this skill mirrors it for UI.
- `SKILLS/parallel-execution.md` — fix-fanout mechanics when findings span multiple root-cause groups.
- `SKILLS/platform-stewardship.md` — why this skill belongs in `SKILLS/` and not in CLAUDE.md; how to extend the playbook when new patterns emerge.
- `SKILLS/root-cause-analysis.md` — every fix commits a real cause, not a symptom patch; applies identically here.
- `SKILLS/capacity-monitoring.md` — before fanning out Lighthouse runs in parallel (each spawns Chrome), check capacity.
