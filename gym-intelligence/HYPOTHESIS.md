# Basic-Fit Cluster Strategy — Hypothesis Test Plan (v3)

_Drafted 2026-04-15 by Gym Intelligence session. Revised after user sharpened scope to industry-structure test only; white-space analysis deferred as a follow-up project._

## The hypothesis (user, as of 2026-04-15)

Consumers in low-end gyms choose on **good-enough × price × proximity** — proximity matters most. Basic-Fit exploits this by building catchments and saturating them with enough density that parallel-tier competitors can't profitably enter. Amenity-rich, niche, and premium operators compete on different axes and remain viable alongside Basic-Fit.

Refined: in a uniform-population / uniform-transport world, gym spacing *within a tier* should be roughly constant. Saturation is invisible with raw distance but visible with two cleaner signatures:

1. **Spacing tightness:** distance between each gym and its nearest same-tier gym should cluster in a "not too close, not too far" band (saturation signature).
2. **Chain clustering:** when a Basic-Fit's nearest same-tier neighbor is another Basic-Fit disproportionately often compared to random assortment, that's Basic-Fit's catchment strategy in action.

## The test — industry-structure analysis

### Quantitative form

Per country × snapshot_date × tier, compute two numbers:

1. **Spacing tightness** = coefficient of variation of the distribution of "population-weighted distance to nearest same-tier gym." Low CV = uniformly spaced = saturated. High CV = chaotic = new market.
2. **Same-chain clustering excess** for the chain under test (Basic-Fit for the headline test; repeatable for others). Formula: `observed P(nearest same-tier gym is same chain) − expected P under random assortment (= chain's share of that tier in that country)`. Expected = 0 under random assortment. Positive excess = clustering.

Both metrics are scalars per (country, quarter). Two metrics × 6 countries × 16 quarters = 192 data points, easy to chart.

### Coverage-drift immunity

- **Same-chain clustering excess** is a ratio within the same tier and same snapshot, so uniform OSM coverage growth has zero effect on it. If OSM grows from 70% → 95% coverage of budget gyms across all chains equally, both observed and expected shift the same amount and the excess is unchanged.
- **Spacing tightness CV** is partially self-normalizing (ratio of std to mean) but does shift if coverage improves *differentially* across space (e.g., urban OSM fills in faster than rural). Flag in the validation sidebar; upgrade to isochrones + Eurostat-anchored cells in v4 if the CV signal correlates too neatly with coverage drift.

### Success criteria

- **Excess Basic-Fit→Basic-Fit clustering:** >+20 percentage points in NL today. Weaker (<10) in DE today. DE's excess trends upward monotonically through 2022-2026. All three are eyeball-obvious in the small-multiples chart.
- **Spacing tightness CV:** NL budget-tier CV < 0.4 today. DE budget-tier CV > 0.6 today, declining >5 pct points over the 16 quarters. NL niche and premium tiers have looser CV than NL budget (different competitive dynamics, as predicted).
- **Tier contrast:** within NL at t=today, budget-tier excess-clustering >> premium-tier excess-clustering. (Premium gyms don't cluster by chain because they compete on amenities, not proximity.)

## Rendering

One page at `/gym-intelligence/thesis`, three sections stacked:

### Section A — the map (the visual answer)

One small-multiples grid, 6 countries. Per panel: budget-tier gyms dotted, each with a line to its nearest same-tier neighbor. Line color = blue if neighbor is same chain, red if different chain. 5-second glance tells the story: forest of blue in NL = clustering confirmed; mixed red/blue in DE = not yet. Scroll horizontally on mobile.

### Section B — the numbers (the quantitative answer)

Compact table, one row per country, columns:

| Country | BF share of budget tier | Observed P(BF→BF) | Excess clustering | CV of nearest-gym population |

Plus one trend line: excess clustering per country over 16 quarters. DE's line climbing = saturation in progress. NL's line flat and high = already saturated.

### Section C — coverage-quality sidebar (trust validation)

Small collapsible section: OSM-derived Basic-Fit count vs Basic-Fit's investor-published real count, per quarter, per country. Computed percent-coverage trajectory. This contextualizes Section A and B — lets the reader discount any suspicious tightening that correlates with pure coverage improvement.

Data source for ground-truth: Basic-Fit's quarterly investor updates (public, ~15 min of Claude-assisted scraping, ~$0.50). I'll queue this as background work alongside the analysis build.

### What lives on the page vs what doesn't

- **Lives:** the map, the table, the trend line, the coverage sidebar. CSV download button for the raw per-gym computation so user can work with it offline.
- **Doesn't:** animated quarter-by-quarter maps, interactive filter sliders, full isochrone-based catchments. Each is an upgrade for v4 if v3's directional signal warrants the refinement.

## Deferred (not in scope)

- **White-space analysis.** "Where could a new competitor profitably enter" — reverse-map of the above. Separate follow-up project. Useful if the hypothesis confirms and we want to operationalize the insight; not useful for testing the hypothesis itself.
- **Finer amenity splits.** Breaking premium into "pool-equipped," "racquet-equipped," "spa-equipped" etc. Worth doing if Section B shows interesting patterns inside the non-budget tiers.
- **Isochrone-based catchments.** OpenRouteService 15-min walk/cycle/drive polygons instead of Voronoi-nearest. Fixes the rural/urban transit concern. Worth doing if v3's directional signal is ambiguous or if a reader challenges the Voronoi approximation.

## Data we already have

- Gym lat/lon per chain per country (live DB `locations` table).
- Tier attribution (`competitive_classification`, `price_tier`, `ownership_type`).
- 16-quarter snapshot time series — **in flight right now**, backfill ~5/16 complete as of this writing, ETA ~3 hours at current pace.

## Data we need to add

- **Eurostat GEOSTAT 1km² population grid** for population-weighted distance computation. Free, ~300MB full-EU or ~40MB per country. Download + spatial-join per gym. One-time setup, ~30 min.
- **Basic-Fit investor data** (for coverage-quality sidebar). Quarterly location counts 2022–2026. Scrape from investor-relations PDFs, one Claude pass, ~$0.50.

## Effort estimate

Build: ~3–4 hrs across one Builder dispatch (analysis module + Flask endpoint + minimal mobile-first frontend on the `/thesis` route). Plus ~1 hr for the Eurostat ingestion. Plus ~30 min for Basic-Fit investor scrape. Total: ~half-day after backfill completes.

Review: user looks at Section A's map + Section B's numbers on mobile and decides whether the thesis held. If yes, queue the white-space follow-up. If no, the data we now have still produced a real finding (Basic-Fit's position isn't as unassailable as thought) and that's worth knowing too.
