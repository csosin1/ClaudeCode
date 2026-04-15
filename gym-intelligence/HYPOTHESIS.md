# Basic-Fit Cluster Strategy — Hypothesis Test Plan

_Drafted 2026-04-15 by Gym Intelligence session (slug: gym-intelligence). Awaiting user review._

## The hypothesis (user, 2026-04-14)

Consumers in low-end gyms choose on **good-enough × price × proximity** — proximity matters most. Basic-Fit exploits this by building catchments and saturating them with enough density that parallel budget competitors can't profitably enter. Amenity-rich (pool/tennis), niche (Pilates, cycling), and premium (Equinox-style) competitors operate on different axes and remain viable alongside Basic-Fit.

## What this plan tests

Three sub-hypotheses, each a discrete analysis with its own success criterion:

### H1. Basic-Fit builds catchments (density grows where they've committed)

**Claim:** Basic-Fit's location density in a geography rises monotonically from market entry onwards; mature markets have tighter inter-gym spacing than new ones.

**Computation:**
- For each Basic-Fit gym, compute distance to its nearest other Basic-Fit gym (nearest-neighbour).
- Bucket by country and by "years Basic-Fit has been present in this city" (proxy: earliest snapshot_date with Basic-Fit in that admin boundary).
- Plot median nearest-neighbour distance vs years-present, per country.

**Success criterion:** Median nearest-neighbour distance in NL (mature, ~25 yrs) < BE (mature, ~15 yrs) < FR (growth phase) < DE (new, <5 yrs). Directional, not precise — if NL has tighter clustering than DE, the claim holds.

**Data needed:** lat/lon per Basic-Fit gym per snapshot_date. **Already have** (live DB `locations` + `snapshots` tables + quarterly backfill in flight).

---

### H2. Density deters new parallel-budget competitors (unassailability)

**Claim:** Where Basic-Fit has already saturated a catchment, new budget chains (McFit, clever fit, Fitness Park, Magic Form, FitX, etc.) are less likely to open; where Basic-Fit is thin, competitors enter freely.

**Computation:**
- Divide each country into 5km hex grid cells.
- For each cell, compute *Basic-Fit density in 2022* (gyms / population) using the earliest post-backfill snapshot.
- For each cell, compute *net parallel-budget competitor openings 2022 → 2026* (count in 2026 minus count in 2022, filtered to `competitive_classification='direct_competitor' AND ownership_type='private' AND price_tier IN ('budget','mid_market')`).
- Split cells into deciles by Basic-Fit density.
- Compare mean net competitor openings across deciles.

**Success criterion:** Monotonic (or near-monotonic) negative relationship — top density decile sees significantly fewer net openings than bottom density decile. A p<0.05 trend test is a win; a clean eyeball trend is acceptable given N=~1,000 cells.

**Data needed:**
- Historical quarterly gym locations ← **in flight** (16-quarter OHSOME backfill).
- Per-cell population ← **need Eurostat/NUTS population grid** (free, ~100MB download, joined by lat/lon-to-cell). Flagged in PROJECT_STATE.md as an enrichment.

---

### H3. Amenity-rich / niche / premium competitors are unaffected by Basic-Fit density

**Claim:** Same density analysis as H2 but segmented by competitor type — the negative relationship should hold ONLY for parallel-budget competitors. Pools, tennis clubs, Pilates studios, CrossFit boxes, and premium clubs should show no relationship (or even positive, if Basic-Fit creates customer traffic).

**Computation:**
- Same hex grid + density decile setup as H2.
- For each competitor sub-segment, compute net openings 2022→2026:
  - **parallel-budget** (our current `direct_competitor` / budget+mid)
  - **amenity-rich** (has pool / tennis / sauna per OSM tags OR chain website — needs enrichment)
  - **niche** (Pilates, CrossFit, cycling, martial arts — heuristic: chain names + OSM sport tags)
  - **premium** (our `non_competitor` with price_tier='premium')
  - **municipal** (ownership_type='public')
- Plot net-openings vs Basic-Fit density decile, one line per segment.

**Success criterion:** Parallel-budget line slopes down (confirms H2). Other segments show flat or positive slopes. If all segments slope down, the strategy isn't selective — H3 rejected, and that's a stronger finding than H3 being confirmed because it'd mean Basic-Fit deters everything, which has different strategic implications.

**Data needed:**
- Everything from H2.
- **Amenity flags per chain** — currently have `competitive_classification`, `price_tier`, `ownership_type`. Need to add `amenity_pool BOOL`, `amenity_racquet BOOL`, `niche_type TEXT` (pilates/crossfit/cycling/martial_arts/none). Can be done with one Claude pass over our 99 competitors (~$0.30) + OSM tag scan for the long tail.

## What's blocking each

| Analysis | Blocker | Effort to resolve |
|---|---|---|
| H1 | None (after backfill completes) | 0 — just run it |
| H2 | Eurostat population grid ingestion | ~2 hrs: download grid, spatial-join per gym lat/lon to cell, store cell_id on `locations` |
| H3 | Amenity/niche classification pass | ~1 hr: Claude pass + schema column `amenity_flags` |

## Recommended order

**1. Ship H1 first.** Needs nothing beyond the 16-quarter backfill. Produces a clean chart the user can look at and say "yep, that matches my mental model" or "no, it doesn't." Fast validation before committing to H2/H3 plumbing.

**2. If H1 confirms:** build H2. Population grid is the biggest single-step work but well-scoped.

**3. H3 only if H2 confirms.** If H2 fails (no density-vs-competitor-openings relationship), the whole cluster-strategy thesis needs rethinking and segmenting by amenity type is premature.

## Non-goals for this spec

- Attribution of causality. All three tests are correlation-level; proving Basic-Fit's density *caused* competitors to avoid an area would need an RCT or instrumental-variable natural experiment, neither of which we can set up.
- Counterfactuals. We can't say "what if Basic-Fit hadn't entered NL." We can only show patterns consistent or inconsistent with the hypothesis.
- Forecasting. This is an audit of the last 4 years, not a projection of the next 4.

## Estimated total effort (all three analyses)

Build: ~6–8 hrs across 2 Builder dispatches. Data enrichments: ~3 hrs. Analysis + dashboard surfacing: ~4 hrs. Call it a two-day project if user approves H1 first and results warrant continuing.
