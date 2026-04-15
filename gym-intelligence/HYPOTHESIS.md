# Basic-Fit Cluster Strategy — Hypothesis Test Plan (v2)

_Drafted 2026-04-15 by Gym Intelligence session. Revised after user feedback flagged that raw density metrics are muddled by population + transit heterogeneity. Awaiting user "go" on the Voronoi approach below._

## The hypothesis (user, as of 2026-04-15)

> Consumers in low-end gyms choose on **good-enough × price × proximity** — proximity matters most. Basic-Fit exploits this by building catchments and saturating them with enough density that *parallel-tier* competitors can't profitably enter. Amenity-rich (pool/tennis), niche (Pilates, cycling), and premium operators compete on different axes and remain viable alongside Basic-Fit.
>
> **Sharper form:** in a uniform-population / uniform-transport world, gym spacing *within a tier* should be roughly constant — once a budget gym covers the population within its reach, no second budget gym opens nearby. Real-world population density and transit muddle raw-distance measurements, so the test has to normalize for both.

## The sharpened testable claim

**Per-tier catchment populations are tightly distributed in mature markets and loose in new ones.**

Formalised: for each gym *g* of tier *t*, compute C(g,t) = population closer to *g* than to any other tier-*t* gym. The hypothesis predicts:

- The distribution of C values *within a tier within a country* is tight (low coefficient of variation) in mature markets.
- The distribution is loose in new markets where chains are still jostling for position.
- Different tiers have different C means but each tier's distribution is internally tight.
- Over time, as Basic-Fit saturates new markets (e.g., DE 2022→2026), that country's budget-tier C-distribution tightens.

## The v2 test — Voronoi weighted by population

### Why this shape
Voronoi-closest-gym is the simplest possible consumer-choice proxy: "you go to the gym closer to you than any other." Weight by population grid to get C(g,t) in people, not km². This folds population density in automatically — dense urban Voronoi cells are small but populous; sparse rural cells are large but sparsely populated; the per-gym "people served" metric normalizes out both.

Transit gets a crude but honest handling: in areas with better transit, people actually travel further, so real catchments are wider than Voronoi-nearest predicts. That shows up as noise in the distribution, not bias — the test looks at *shape* of the distribution, not absolute values.

### Concrete pipeline
Per country × snapshot_date × tier:
1. Filter `snapshots` to the relevant tier (budget, amenity-rich, niche, premium, public).
2. Pull lat/lon for those chains from `locations` (joined via `chain_id`).
3. Compute Voronoi cells using `scipy.spatial.Voronoi` on the gym points (or faster: use a spatial KD-tree and nearest-neighbour lookup on the population grid directly — avoids polygon construction for millions of grid cells).
4. Load the Eurostat GEOSTAT 1km² population grid for the country.
5. For each grid cell, find the nearest gym of the tier → sum that cell's population into that gym's C.
6. Output: distribution of C values per gym in the tier. Compute mean, median, CV (coefficient of variation = stddev / mean), Gini.

### Success criteria
- **Primary:** in mature markets (NL Basic-Fit territory since ~2004), the budget-tier C-distribution has CV < 0.4 (i.e., most gyms serve a similar number of people within a factor of ~2× of the median).
- **Contrast:** in new markets (DE Basic-Fit presence since ~2019), budget-tier CV > 0.6.
- **Tier separation:** budget-tier mean C should differ from niche/premium-tier mean C by > 2× (they're sized for different market widths).
- **Temporal:** DE budget-tier CV tightens monotonically 2022→2026 (saturation in progress).

Each is a clean eyeball chart. No p-values needed for a thesis-exploration pass.

## Data requirements

**Already have:**
- Gym lat/lon per chain per snapshot_date (after overnight backfill completes).
- Tier attribution (`competitive_classification`, `price_tier`, `ownership_type`).

**Need to add:**
- **Eurostat GEOSTAT 1km² population grid.** Free download, ~300MB for EU-27, one-time. URL: `https://ec.europa.eu/eurostat/web/gisco/geodata/population-distribution/geostat`. Cache on droplet under `/opt/gym-intelligence/data/eurostat_grid_1k_2021.gpkg` (~350MB) or the smaller per-country CSV extracts (~40MB each for our 6 countries; worth per-country to avoid full-EU download).
- **Python deps:** `geopandas`, `shapely`, `scipy.spatial` (Voronoi/KDTree), `matplotlib` or similar for the output chart. Add to `requirements.txt`.

**Nice-to-have (v3 upgrade, not required for v2):**
- OpenRouteService isochrones instead of Voronoi. 15-min walk/cycle/drive polygons give real transit-adjusted catchments. Free tier 500/day fits our ~100 competitor-tier gyms; for 30k all-gym coverage we'd need to self-host OSRM or batch it over days. Worth doing only if v2 shows a directional pattern and we want to confirm/quantify it.
- Amenity/niche-type flags on chains (pool/tennis/Pilates/CrossFit) for finer tier splits. Claude pass on the 99 known competitors (~$0.30) + OSM tag mining for the long tail.

## What the first deliverable looks like

One chart per country × tier × most-recent-snapshot — six countries × four tiers = 24 small-multiples on a grid. Each panel: histogram of C values with mean/median/CV annotated. Then one trend chart per country showing budget-tier CV over the 16 snapshot_dates. If the thesis is visible, NL's panel shows a narrow peak, DE shows a broad one, and DE's CV trends downward over time.

**Ship this first. Decide on v3 (isochrones + amenity splits) only after looking at v2.**

## What this doesn't resolve

- **Selection vs causation.** Basic-Fit chose where to enter. A tight per-tier CV in NL could reflect their saturation strategy OR it could reflect a long-settled market equilibrium where *any* operator would have landed in similar places. Distinguishing these needs a natural experiment (e.g., a regulation that forced random entry ordering) and is out of scope.
- **Price-tier fuzz.** We classified price to three bands (budget <€25, mid €25–50, premium >€50). Basic-Fit and clever fit are both "budget" but with real price and amenity differences. Coarse tiering may wash out fine-grained competition dynamics.
- **Rural/urban transit.** Voronoi-nearest in rural NL (cars, highways) is a different consumer choice than Voronoi-nearest in downtown Amsterdam (bike-5-min). v2 treats both the same. v3 with isochrones fixes this.

## Estimated effort

v2 build: ~3-4 hrs (ingest Eurostat grid, implement Voronoi+KDTree pipeline, render chart). Run: <5 min on the backfilled DB. Review: user looks at the chart and decides whether to commit to v3.

Total to v2 deliverable: ~half day after backfill completes.
