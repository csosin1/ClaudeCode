# The Basic-Fit Cluster Thesis: A Research and Build Plan

_Drafted 2026-04-18 by Gym Intelligence session. Background research and build architecture for the next-session execution. Intended output is a joint academic-paper / textbook-chapter / investor-note, published as both an interactive site and a downloadable PDF._

---

## 0. Reading guide

This document is long on purpose. It exists to let a next-session Claude, the user, and anyone dropped into this project later **start building without re-scoping**. Three audiences:

- **Investor reader**: sections 1, 3, 8, 10 tell you what we're testing, why it matters, what the deliverable will look like, and where the open decisions are.
- **Analyst / PhD-economist reader**: sections 2, 5, 6 cover theory, method choices, and robustness.
- **Engineer / next-session Claude**: sections 4, 7 are the build spec — data sources, pipelines, exact commands.

Every quantitative claim we test in the analysis is surfaced in section 1 as a specific, falsifiable prediction; the rest of the document is how we get there.

---

## 1. The question, formally

### 1.1 Informal statement (user's framing, 2026-04-17)

Basic-Fit's stated strategy is to build clusters of gyms. Gym consumers choose on proximity and cost; proximity dominates because membership is a high-frequency, low-per-visit-value good. That creates a natural **catchment** per gym — the population for whom that gym is the nearest same-tier option. Basic-Fit further densifies within its catchments to deny competitors the "breathing space" they need for profitable entry. Same-geography competition still happens, but only via differentiation — different amenity mix (pool, tennis, racquet), different niche (Pilates, cycling), or different price tier (premium).

If population density and transport were uniform, this would produce a uniform honeycomb of gyms, each serving an identical population. Reality is non-uniform, so the pattern is complex but — if the strategy is working — still identifiable: within any competitive tier, gyms should be spaced such that each serves roughly the same number of people, and same-chain gyms should cluster with each other more than random placement would predict.

### 1.2 Formal statement (four falsifiable predictions)

**P1 — Tier-saturated spacing.** Within a defined competitive tier (same price band, similar amenity profile), the distribution of per-gym population-catchments should be *tight* in mature markets — coefficient of variation (CV) below some threshold, say <0.5 — and *looser* in new markets still filling in.

**P2 — Same-chain clustering excess.** For Basic-Fit specifically, the observed probability that a BF gym's nearest same-tier neighbor is another Basic-Fit should exceed the null-baseline probability (= BF's share of same-tier gyms in that geography) by a material amount (≥10 percentage points in mature markets, declining to ~0 in markets BF just entered).

**P3 — Tier-specific clustering.** P2 should hold specifically for the budget tier Basic-Fit operates in. Premium, niche (Pilates, CrossFit, cycling), and amenity-differentiated (pool/tennis) tiers should show no equivalent clustering signature because they compete on different axes.

**P4 — Temporal tightening.** In markets where Basic-Fit has been expanding (Germany, Spain), the clustering excess from P2 should monotonically increase over 2022–2026 as the strategy plays out. This is a harder prediction and will require the OHSOME time-series — which we already have, with known accuracy caveats.

### 1.3 What a confirming result looks like

- Per-tier catchment-population CV < 0.5 in Netherlands budget tier, >0.7 in Germany budget tier. CV differential significant at p<0.05 on a permutation test.
- Excess clustering (observed − null) for Basic-Fit in Netherlands of +20pp or more; similarly positive in Belgium and France; declining toward zero in Germany/Spain in early years and rising over time.
- Budget-tier excess clustering >> premium-tier and niche-tier excess clustering in the same geography.
- Germany's excess-clustering slope over 2022→2026 is positive and non-trivial (≥ +2pp/year).

### 1.4 What a disconfirming result looks like

- Per-tier CVs similar across mature and new markets → suggests uniform spacing is not a tier phenomenon but something else (transit? demographics?).
- Excess clustering is near zero even in NL → Basic-Fit's "cluster strategy" investor narrative is marketing, not operational reality.
- Premium/niche tiers show equally strong clustering as budget → clustering is a generic chain-growth pattern, not a strategic moat.
- Germany's excess clustering trend is flat or declining → no evidence of active saturation.

Any of these outcomes is still a valuable investor finding. The analysis is designed so every result teaches us something, not just the positive ones.

### 1.5 Why this matters financially

Basic-Fit trades at a premium implicitly tied to the durability of their competitive position. If P1–P4 all confirm, the moat story is empirically grounded and the premium is defensible. If P2 or P3 disconfirms, the cluster claim is rhetorical rather than structural and the moat is weaker than the market prices. Either finding moves a rational allocator's base rate on the stock.

---

## 2. Theoretical framework

### 2.1 Central Place Theory (Christaller, 1933; Lösch, 1940)

Christaller introduced the foundational model of how retail centers distribute themselves across uniform space. Under idealized assumptions (flat terrain, uniform population, uniform transport cost, firms maximizing market area while charging above marginal cost), Christaller showed that central places arrange in a **hexagonal tiling** at each tier of good-specialization. Lösch extended this to derive hierarchical nesting: higher-order goods (department stores, hospitals) are served from fewer, larger centers; lower-order goods (groceries, gyms) from many, smaller centers. Each tier has its own *threshold population* (minimum market to survive) and *range* (maximum distance a customer will travel).

For gyms, the relevant prediction is: within a tier, market-area (= catchment population) should be approximately constant because any sub-threshold spot cannot support an entrant, and any super-threshold spot would attract one. This is precisely the user's "uniform honeycomb under uniform conditions" intuition, formalized.

**Key references:**
- Christaller, W. (1933). *Die zentralen Orte in Süddeutschland*.
- Lösch, A. (1940). *Die räumliche Ordnung der Wirtschaft*.
- Dicken, P. & Lloyd, P. (1990). *Location in Space* — textbook synthesis.

### 2.2 Hotelling, Salop, and the spatial-competition lineage

Hotelling (1929, *Stability in Competition*) set up the linear-beach ice-cream-seller model. Under inelastic demand and uniform consumers along a line, two sellers converge to the center — the "principle of minimum differentiation." D'Aspremont, Gabszewicz & Thisse (1979) corrected Hotelling's mathematics and showed that under quadratic transport costs, firms *maximally* differentiate; under linear costs, equilibrium doesn't exist in pure strategies.

Salop (1979, *Monopolistic Competition with Outside Goods*) replaced the line with a circle and allowed free entry. His result is directly germane to our hypothesis: under free entry and symmetric firms, the equilibrium outcome is **firms located at equal angular intervals around the circle**, each serving the same share of consumers. This is the one-dimensional, one-tier version of the honeycomb.

The modern retail-entry literature extends these models to multiple dimensions, heterogeneous firms, and endogenous product positioning. Mazzeo (2002, *Product Choice and Oligopoly Market Structure*) studied highway motels and showed that entrants deliberately choose different service tiers when a market is already served at one tier, producing empirical separation between tiers that aligns with the user's P3 prediction.

**Key references:**
- Hotelling, H. (1929). "Stability in competition." *The Economic Journal* 39: 41–57.
- D'Aspremont, C., Gabszewicz, J. J., & Thisse, J.-F. (1979). "On Hotelling's 'Stability in Competition'." *Econometrica* 47: 1145–1150.
- Salop, S. (1979). "Monopolistic Competition with Outside Goods." *Bell Journal of Economics* 10: 141–156.
- Mazzeo, M. (2002). "Product Choice and Oligopoly Market Structure." *RAND Journal of Economics* 33(2): 221–242.

### 2.3 Entry-deterrence econometrics (Bresnahan–Reiss and descendants)

Bresnahan & Reiss (1990 *J. Econometrics*; 1991 *JPE*) introduced the empirical framework that dominates retail-entry analysis. The idea: in isolated small markets, the number of firms that enter reveals the economic rent a marginal entrant expects. Fitting a structural model to population-and-firm-count data across many markets backs out an estimate of *how much each additional competitor reduces per-firm profit* — equivalently, a measure of how much market room each competitor consumes.

For Basic-Fit, the adapted question is: **conditional on market size, does one more Basic-Fit gym displace expected parallel-competitor entries?** If yes, by how many? This is the "magnitude of deterrence" number that turns an observed clustering correlation into a claim about causation.

Extensions relevant to us:

- **Mazzeo (2002)** — product differentiation as an entry-response margin. Instead of "enter or don't," firms also choose "enter with a different service bundle." Directly applicable to the P3 tier-specificity test.
- **Seim (2006, *RAND*)** — spatial differentiation with endogenous locations. Uses a game-theoretic model where each firm picks both entry and location, which lets us separate "chose to enter close" from "chose to enter at all."
- **Jia (2008, *Econometrica*)** — applied Bresnahan-Reiss to Walmart's effect on small-store entry in rural US. Near-perfect template for "Basic-Fit comes to town, what happens to the parallel-budget tier."
- **Aguirregabiria & Vicentini (2016)** and **Aguirregabiria & Mira (2022)** — handbook chapters updating the canonical methods with modern computational approaches.

**Key references:**
- Bresnahan, T. F. & Reiss, P. C. (1991). "Entry and Competition in Concentrated Markets." *Journal of Political Economy* 99(5): 977–1009.
- Jia, P. (2008). "What Happens When Wal-Mart Comes to Town: An Empirical Analysis of the Discount Retailing Industry." *Econometrica* 76(6): 1263–1316.
- Seim, K. (2006). "An Empirical Model of Firm Entry with Endogenous Product-Type Choices." *RAND Journal of Economics* 37(3): 619–640.
- Mazzeo, M. (2002). Cited above.
- Aguirregabiria, V. & Vicentini, G. (2016). "Empirical Games of Market Entry and Spatial Competition in Retail Industries." In *Handbook on the Economics of Retailing and Distribution*.

### 2.4 Agglomeration economies (Ellison–Glaeser, Duranton–Overman)

A parallel literature measures industry-wide geographic concentration: is an industry clustered more than random? Ellison & Glaeser (1997) introduced an index that decomposes observed concentration into "plant luck" and "true agglomeration." Duranton & Overman (2005) refined it with a continuous-distance version that avoids arbitrary area binning.

For Basic-Fit, these are useful *cross-industry comparisons* — "does the gym industry cluster more than furniture retail?" — but less directly targeted at our same-chain-nearest-neighbor test. Include in the supporting literature but not as the headline method.

**Key references:**
- Ellison, G. & Glaeser, E. (1997). "Geographic Concentration in U.S. Manufacturing Industries: A Dartboard Approach." *Journal of Political Economy* 105(5): 889–927.
- Duranton, G. & Overman, H. (2005). "Testing for Localization Using Micro-Geographic Data." *Review of Economic Studies* 72(4): 1077–1106.

### 2.5 Spatial point processes — the statistical toolkit

The mathematical machinery to test P1–P4 on real data comes from spatial point process statistics. Two functions do most of the work:

- **Ripley's K function** *K*(r) (Ripley, 1976, 1977): expected number of points within distance *r* of a typical point, normalized by intensity. *K*(r) > π*r*² (the Poisson benchmark) = clustering; *K*(r) < π*r*² = dispersion. The *L*(r) = √(K(r)/π) − r transform centers the expected value at zero for visual comparison.

- **Cross-K function** *K*ᵢⱼ(r): for a marked point process with categorical marks (chain identity), the expected number of j-type points within *r* of a typical i-type point. *K*ᵢⱼ(r) > *K* of all-points = types i and j attract; < = repel. For our case, *K*_{BF,BF}(r) vs *K*_{BF,non-BF}(r) at moderate *r* tests P2 directly.

- **Mark-connection function** *p*ᵢⱼ(r): probability that two points within distance *r* of each other are of types *i* and *j*. *p*_{BF,BF}(r) > (share_BF)² = same-chain clustering.

- **Pair correlation function** *g*(r): the derivative of *K*(r), showing clustering *at* distance *r* (not cumulative up to *r*). Useful for detecting scale-specific patterns.

- **Nearest-neighbor distance distribution** *G*(r): for an observed point, what's the distribution of distance to the nearest other point? Tight distribution around a central value = regular spacing (Salop-like); exponential = Poisson; bimodal = clustered.

- **Empty space function** *F*(r): from a random point in space, what's the distance to the nearest observed point? Useful for "where could a competitor enter" — the complement of our coverage analysis.

Gold-standard implementation: R's `spatstat` family (Baddeley, Rubak & Turner, 2015). Python alternatives: `pointpats` (from PySAL), `astropy.stats` for edge-corrected K. `pointpats` is what we'll use to keep the stack Python-only.

**Key references:**
- Ripley, B. D. (1976). "The Second-Order Analysis of Stationary Point Processes." *Journal of Applied Probability* 13: 255–266.
- Baddeley, A., Rubak, E. & Turner, R. (2015). *Spatial Point Patterns: Methodology and Applications with R*. CRC Press. — the canonical reference.
- Diggle, P. J. (2013). *Statistical Analysis of Spatial and Spatio-Temporal Point Patterns*, 3rd ed.

### 2.6 Huff gravity and catchment definitions

The modern retail-siting industry uses gravity models derived from Reilly (1931) and formalized by Huff (1963). A consumer's probability of patronizing store *j* is:

$$P(j) = \frac{A_j / d_j^\alpha}{\sum_k A_k / d_k^\alpha}$$

where *A*ⱼ is a measure of the store's attractiveness, *d*ⱼ is distance, and α is the distance-decay exponent (typically 1.5–2 for low-order retail). Integrating this over population gives a probabilistic "expected patrons" catchment for each store — fuzzier than Voronoi (each person assigns probabilistically to multiple stores) but more realistic.

For v1 we'll use Voronoi nearest-neighbor assignment as a simpler proxy; v2 may upgrade to Huff if the directional signal from v1 justifies the complexity.

**Key references:**
- Reilly, W. J. (1931). *The Law of Retail Gravitation*.
- Huff, D. (1963). "A Probabilistic Analysis of Shopping Center Trade Areas." *Land Economics* 39(1): 81–90.

---

## 3. Industry context: Basic-Fit's stated strategy

From Basic-Fit's own investor communications (confirmed via their March 2024 investor presentation and recurring themes across 2022–2024 decks):

- **Target density**: one club per ~30,000 inhabitants in their core markets, implying an 11% target penetration rate.
- **Urban focus**: active expansion in cities with >30,000 inhabitants. Rural/exurban expansion is a secondary track.
- **Catchment radius**: 10–15 minute drive. This is a critical operational number — it defines what Basic-Fit considers "one market."
- **Explicit strategic framing**: clustering is positioned as the moat. From their investor deck (paraphrased): *"The cluster strategy creates a dense network of clubs in a town to increase customer convenience and avoid leaving economic room for competitors."*
- **Country timeline**: mature in Netherlands (20+ years) and Belgium; growth phase in France and Spain; early/expansion phase in Germany (since ~2019–2020) and Luxembourg.
- **Competitor posture**: Basic-Fit frames differentiated players (boutique, premium, municipal) as non-competitive in their economic tier. This is exactly the tiering our P3 prediction operationalizes.

The key operational numbers we'll validate against our empirical catchment estimates:

| Market | BF stated clubs (Q4 2025) | Target density | Implied population covered at target |
|---|---:|---|---:|
| Netherlands | ~240 | 1 per 30k | 7.2M addressable |
| Belgium | ~150 | 1 per 30k | 4.5M |
| France | ~940 | 1 per 30k (urban) | 28.2M |
| Spain | ~260 | below target (expansion) | 7.8M |
| Germany | ~125 | well below target (early) | 3.75M |
| Luxembourg | ~25 | dense for size | 0.75M |

Whether reality matches — per-country median catchment population is ~30k in NL vs a larger number in new markets — is exactly what P1 tests.

**Key references:**
- Basic-Fit N.V. Investor Presentation, March 2024. corporate.basic-fit.com/investors
- Basic-Fit N.V. Investor Presentation, September 2023.
- Basic-Fit annual reports 2021–2024.

---

## 4. Data architecture

### 4.1 Gym locations

Three candidate sources, ranked by usefulness for this study:

**(a) Google Places API — primary for present-day**

- **Why it's first**: highest coverage and accuracy (~95%+) of actually-operating businesses in Western Europe. Better than OSM for branded chains AND for independents.
- **Pricing** (Google Maps Platform, verified 2026): Nearby Search at **$17 per 1,000 requests** (Basic tier). Tiered SKUs (IDs Only → Preferred) adjust cost based on fields requested; for our purposes "Location + Basic" tier should suffice, including place_id, name, lat/lng, primary_type, business_status, and price_level. Google extends a $200/month free credit that covers the first ~11k requests.
- **Enumeration strategy**: bounding-box grid search across the 6 countries. A 1km² grid cell with a radius-1km Nearby Search request (`type=gym|health` and `type=gym` where fitness-center is not a supported type) returns up to 60 places per request (3 pages of 20). Rough budget:
  - Total area ≈ 2.3M km² across NL+BE+FR+ES+LU+DE
  - Density-aware grid (finer in cities, coarser in rural) → ~60k cells
  - Cost ≈ 60k × $0.017 ≈ **$1,020 one-time** for a full enumeration. Within the free-tier-plus-upgrade envelope.
- **Known limitations**: stale closed businesses linger 3–12 months; some categories drift (EMS-only studios tagged as gyms). Still a substantial upgrade on OSM.
- **What we'd get per gym**: place_id (stable), name, lat/lng, primary_type, business_status, price_level (1–4), rating, review count, website, phone. `business_status=OPERATIONAL` filter removes the stale-closed-business problem.

**(b) Chain store-locator scrapes — authoritative ground truth for known chains**

- For each top-20 chain by footprint in our tier, scrape their store-locator page directly. Gives **100% accuracy per chain** for chains with a machine-readable locator.
- Existing code at `gym-intelligence/scripts/coverage_scrape_v2.py` handles httpx + Playwright fallback. Regex/JSON-LD extraction catches ~25% of cases; the remainder need bespoke per-chain parsers or an LLM extractor.
- **Use case in the build**: ground-truth for validating Google Places coverage per chain per country. Not the primary data source (coverage is chain-only, missing independents), but the trust anchor.

**(c) OHSOME (OSM history) — for the temporal dimension only**

- Already have 16 quarters backfilled (2022-Q2 through 2026-Q1). Known accuracy issues (F-006 through F-010 in AUDIT_FINDINGS.md). Good directional signal for Basic-Fit specifically (matches published counts within ~2%), unreliable for peer chains.
- **Use case**: tracking temporal change (P4). Will need per-chain correction factors anchored against the Google Places present-day snapshot when we have it.

**Recommendation: build around Google Places as the primary present-day source, chain scrapes as per-chain anchors, OHSOME for temporal trends only with explicit per-chain correction.**

### 4.2 Population data

**Primary: Eurostat GEOSTAT 2021 census population grid (1 km²)**

- Free, EU-wide, ~5–10 GB download.
- Projection: ETRS89 Lambert Azimuthal Equal Area (EPSG:3035). Lat/lng conversion via `pyproj`.
- Released 2023, populated from the 2021 round of national censuses. Each cell has a total-population count plus sex/age breakdowns.
- Download: https://ec.europa.eu/eurostat/web/gisco/geodata/population-distribution/geostat
- Licensing: EU open-data, no cost, attribution required.

**Secondary / comparison: GHSL (Global Human Settlement Layer)**

- 100m resolution (finer than GEOSTAT), produced by the JRC, annual updates.
- Useful for sanity-checking GEOSTAT in specific cities and for extending analysis to Switzerland/Norway/UK if needed later.
- https://human-settlement.emergency.copernicus.eu/

**Accessibility / transit (deferred)**

For v1 we will not use isochrones — Voronoi nearest-neighbor at the 1-km² population grid level is a reasonable first pass that honors Basic-Fit's own 10–15-minute-drive framing approximately. v2 upgrade path:

- **OpenRouteService** (free, 500 isochrones/day per API key) — fine for the ~1000 largest gyms; too slow for full population-to-gym accessibility matrix.
- **Self-hosted OSRM or Valhalla** — free, runs on a throwaway VM; can generate millions of isochrones overnight. Right answer if v1 signals that transit-aware catchments would change conclusions materially.

### 4.3 Chain classification and tiering

The central judgment call is: which gyms count as "same tier" as Basic-Fit for the purposes of P2 and P3?

**Working tier definition** (to be validated):

> **Tier A — Budget full-service** (Basic-Fit's direct tier): multi-location operator with ≥€15 but ≤€45/month standard membership (18-month normalized), offering weights + cardio, no swimming pool as standard, no racquet courts, minimal class program included (not core), no premium positioning. Examples: Basic-Fit, McFit, clever fit, Fitness Park, L'Orange Bleue, KeepCool, FitX, PureGym.

> **Tier B — Mid-market full-service**: €45–80/mo, broader class program, better amenities (sauna, maybe pool), more premium locations. Examples: John Reed, SportCity, Anytime Fitness in some markets.

> **Tier C — Premium full-service**: >€80/mo, full amenity (pool + racquet + spa), aspirational positioning. Examples: David Lloyd, Holmes Place, Virgin Active, Aspria, Equinox equivalents.

> **Tier D — Specialty / niche**: single-discipline or small-footprint (Pilates-only, CrossFit box, cycling studio, women-only, 24/7-micro-gym). Competes on differentiation, not price. Examples: Club Pilates, EasyFitness can lean niche, boutique cycling brands.

> **Tier E — Public / municipal**: pay-per-entry or municipal-member pricing, primarily for pool/court access rather than gym membership. Not in our competitive universe but present in the raw data.

**Pricing construction — 18-month normalized**

User directive: treat a typical member as a gym retention of 18 months. Compute:

$$\text{18mo price} = 18 \times \text{monthly fee} + \text{joining fee} + \text{annual fee} \times 1.5$$

For chains with multiple membership tiers, use the median public tier (not the promotional entry tier). Scrape from each chain's pricing page, with manual verification for the top 30 chains. Per-country pricing (BF Netherlands vs BF France) because membership prices differ substantially.

**Classification pipeline**

1. **Input**: deduped chain-canonical-name list from Google Places (after our matcher cleanup; see §4.4).
2. **LLM pass (judgment task — this is what Claude does well)**: for each chain, given {name, sample lat/lng, stated price if scrapable, stated amenities from homepage}, assign Tier A–E with rationale and confidence.
3. **Validation**: manually verify the top 30 chains (≥30 locations) — one-time ~2 hour task. Flag disagreements; adjust prompt / ground-truth as needed.
4. **Cross-check**: compare Tier A population total to Basic-Fit's stated competitor-universe estimate from their investor deck. A large gap means tier definition is drifting.

This pipeline is the single most delicate step in the whole build. Bad tier definition corrupts every downstream test.

### 4.4 Chain matcher and canonicalization

Carry forward from prior work with improvements:

- **Canonical normalization**: lowercase, strip diacritics (`unicodedata.normalize('NFKD')`), strip common suffixes (" fitness", " gym", " club", "-fitness"), collapse whitespace, remove punctuation. Produces a match key like `"basicfit"` from all of `"Basic-Fit"`, `"basic fit"`, `"BASIC-FIT Ladies"`, `"Basic Fit Amsterdam"`.
- **Primary match key: `brand:wikidata` OSM tag** where present. Structured, unique. Falls back to the normalized name key when absent.
- **Fuzzy matching**: `rapidfuzz` token-set ratio with a threshold of ~90 for auto-merge; 70–89 for manual review.
- **De-duplicate existing DB entries**: the prior coverage audit surfaced `KeepCool / Keep Cool / Keepcool` as three separate rows that are the same chain. A one-time merge pass reduces our chain count from ~31k to some smaller number and removes the size-bin artifacts that corrupted the last run.
- **Cross-country chain recognition**: Basic-Fit clubs in NL and DE are the same chain; McFit clubs in DE and ES are the same chain. The matcher must collapse across country borders without merging distinct chains that share a common word ("Fitness Park" NL might be unrelated to "Fitness Park" France).

### 4.5 Data validation layer

After ingestion, a validation sidebar (per precedent in AUDIT_FINDINGS.md):

- Top-20-chain location counts: Google Places vs chain-locator scrape vs chain investor-deck.
- Per-country total gym count: our DB vs IHRSA/EuropeActive industry estimates (~10–15% of a country's population belongs to a gym in mature markets; that implies 4–7M gym members per major EU market).
- Population grid sanity: sum over our 6 countries should match Eurostat's published national populations within ~1%.
- Tier distribution sanity: Tier A + Tier B should account for >60% of branded-chain location count in NL/BE/FR (dominated by Basic-Fit-adjacent tiers).

Every test we run reports its results alongside this validation layer so a reader can discount conclusions where the inputs look off.

---

## 5. Methods

### 5.1 Catchment construction

**Definition (v1):** for a gym *i* of tier *t*, its catchment *C*ᵢ is the set of 1 km² population cells where *i* is the nearest tier-*t* gym under Euclidean distance, weighted by each cell's population count. *C*ᵢ in units of people.

**Practical computation:**
1. Load Google Places gym locations (filtered to tier *t*, country *c*) as points in EPSG:3035 projection (already units of meters).
2. Build a `scipy.spatial.cKDTree` on the tier-*t* points.
3. For each population grid cell's centroid, query for the nearest tier-*t* gym.
4. Sum the cell's population into that gym's catchment.

Output: a table of (gym_id, tier, country, population_served).

**Why this approach**
- Fast (KDTree is O(n log n) at setup, O(log n) per query).
- No Voronoi polygons needed (we don't need the polygon geometries, just the assignment).
- Directly mirrors the consumer-choice proxy in §2.6's gravity models at α→∞.

**Robustness variants to run in parallel:**
- Catchment under α=2 Huff gravity (each cell assigns probabilistically to nearest 3 gyms).
- Catchment capped at 15-minute-drive distance (for cells beyond 15 min of any gym, they go to a "no gym in range" bucket).
- Catchment with tier-*t* ∪ tier-*t*' union for adjacent-tier analysis.

### 5.2 Test P1 — Tier-saturated spacing

For each (country × tier) pair:

1. Compute catchment populations {*C*ᵢ} for all tier-*t* gyms in country *c*.
2. Compute distribution statistics: mean, median, CV = stddev/mean, Gini, IQR, p10/p90 ratio.
3. Compare across countries within the same tier (NL budget vs DE budget).
4. Compare across tiers within the same country (NL budget vs NL premium).

**Null for significance testing**: shuffle tier-label assignments across gyms within the country, keeping lat/lng fixed. Compute null CV. Repeat 1000× to get a null distribution. Observed CV below the 5th percentile of null = significant tight spacing.

**Expected pattern if P1 holds**: NL budget CV << NL premium CV (mature saturation); NL budget CV < DE budget CV (mature vs new market).

### 5.3 Test P2 — Basic-Fit's same-chain clustering excess

For each country *c*:

1. Filter to Tier A gyms.
2. For each Basic-Fit gym *i*, find its nearest Tier A gym *j* under great-circle distance.
3. Observed P2 statistic: Pr(*j* is Basic-Fit | *i* is Basic-Fit) = (# BF-BF nearest pairs) / (# BF gyms).
4. Null: Pr(*j* is Basic-Fit) under random assortment = (# BF gyms − 1) / (# Tier A gyms − 1), adjusting for without-replacement.
5. Excess = observed − null, expressed in percentage points.

**Also compute** (via `pointpats`):

- Full cross-K: *K*_{BF,BF}(r) for *r* ∈ [0, 10] km. The L-function transform. Confidence envelope via 999 permutations.
- Mark-connection function *p*_{BF,BF}(r) vs null.
- Nearest-neighbor distance distribution *G*(r) for BF→BF vs BF→other-Tier-A.

**Per-country breakdown**: NL, BE, FR, ES, LU, DE separately. Per-city breakdown for major metros (Amsterdam, Rotterdam, Paris, Madrid, Berlin, Munich, Brussels).

**Edge-effect correction**: apply Ripley's isotropic edge correction for gyms near country borders; otherwise, cross-K near the periphery is biased low.

### 5.4 Test P3 — Tier-specific clustering

Repeat P2 for each chain in the top-20 by footprint. Compute excess-clustering per chain:

- Budget tier (BF, McFit, clever fit, Fitness Park, L'Orange Bleue, KeepCool, FitX, EasyFitness, …) — expected to show positive excess.
- Premium tier (David Lloyd, Holmes Place, Virgin Active, …) — expected to show ~zero excess.
- Niche tier (Club Pilates, CrossFit, cycling boutiques, …) — expected to show ~zero excess.

If the budget tier as a whole shows positive excess but BF alone shows more than other budget chains, that's the strongest evidence for Basic-Fit specifically executing the cluster strategy vs other budget operators doing it accidentally.

### 5.5 Test P4 — Temporal tightening

Using the OHSOME 16-quarter backfill (with per-chain correction factors anchored on Google Places present-day):

1. For each quarter *q*, compute P2's excess-clustering statistic per country.
2. Fit a linear trend (excess_pp ~ quarter_index) per country.
3. Significance via permutation across quarter labels.

**Expected pattern**: Germany slope significantly positive (BF saturating); Netherlands slope near zero (already saturated). Spain slope positive if BF expansion is strategic, zero or negative if expansion is random.

**Known caveat** (per audit findings): OHSOME per-chain accuracy varies ±30% across the peer tier, so the temporal series has measurement error. This test is weaker than P1–P3 and should be presented with explicit uncertainty bands.

### 5.6 Bresnahan-Reiss-style entry deterrence (stretch goal)

If P1–P3 confirm and we want a magnitude-of-deterrence number, fit a reduced-form panel regression:

$$\Delta N^{\text{parallel}}_{m,2022\to2026} = \alpha + \beta \cdot N^{\text{BF}}_{m,2022} + \gamma \cdot \text{pop}_m + \epsilon_m$$

where *m* is a market unit (15-km hex cell or municipality), *N*^BF is the Basic-Fit gym count in market *m* at baseline, and Δ*N*^parallel is the net entry of parallel-budget competitors. β measures the displacement.

**Not a structural Bresnahan-Reiss estimation** — that needs more assumptions than we can cleanly defend. The reduced-form β is a descriptive "conditional on market size, Basic-Fit density correlates with suppressed competitor entries by X gyms per BF gym." Honest and interpretable.

### 5.7 Robustness checks (what the PhD reader will ask about)

- **Tier-definition sensitivity**: re-run with tier borders at ±€5/month thresholds.
- **Catchment-definition sensitivity**: v1 Voronoi vs Huff α=2 vs isochrone-capped.
- **Matcher-threshold sensitivity**: re-run with fuzzy-match threshold at 85 and 95 (not just 90).
- **Sampling sensitivity**: drop out top-20% of cities; do results still hold? Small-city vs big-city split.
- **Boundary effects**: drop gyms within 10 km of country borders; do cross-K results change?
- **Temporal robustness (P4)**: apply different per-chain correction factors from different anchor dates.
- **Alternative null models**: Poisson CSR null vs intensity-matched Thomas cluster null for the Ripley's K significance tests.

Each robustness check gets a one-line diff vs the headline result in a dedicated appendix section.

---

## 6. Implementation — the build plan

### Phase 1: Data ingestion (target: 2–3 days)

**1a. Google Places enumeration**
- Build density-aware grid cell list: start with EU NUTS-3 regions, subdivide urban areas to 500m spacing, rural areas to 5 km spacing.
- For each cell, issue a Places Nearby Search with `type=gym` and `rankby=distance`; paginate through all results.
- Dedupe by place_id.
- Write to `places.sqlite` with columns: place_id, name, lat, lng, country, primary_type, price_level, business_status, rating, user_ratings_total, website.
- Estimated cost: ~$1000–1500 all-in for complete 6-country enumeration.
- Runtime: ~6 hours with politeness pauses (20 req/s limit).
- Run on prod, not dev.

**1b. Chain matcher + canonicalization**
- Use the new canonicalization rules from §4.4.
- Output: canonical_chain_id per place_id.
- Expected: ~5,000–15,000 distinct chains (one canonical row per real chain) vs the ~31k artifacts in our current DB.

**1c. Eurostat population grid ingestion**
- Download GEOSTAT 2021 GPKG (one file, ~5 GB).
- Project to EPSG:3035 if not already.
- Filter to cells overlapping NL/BE/FR/ES/LU/DE.
- Load into `population.sqlite` with columns: cell_id, centroid_lat, centroid_lng, population_total, country.
- Size: ~3M cells across 6 countries.

**1d. OHSOME time-series integration**
- Already exists. Apply per-chain correction factor table (computed once per chain using Google-Places present-day count as denominator) to OHSOME historical counts.
- Output: time-series per (chain, country, quarter) with known uncertainty bound.

### Phase 2: Chain classification + pricing (target: 1–2 days)

**2a. LLM tier classification**
- Per chain, Claude call with {name, sample lat/lng, website URL, stated price snippet if scrapable}, returns {tier: A/B/C/D/E, confidence, rationale}.
- Budget: ~$5–10 at haiku pricing for 10,000 chains.

**2b. Pricing scrape**
- For top-50 chains: scrape each chain's pricing page per country. httpx primary, Playwright fallback.
- Normalize to 18-month price via the §4.3 formula.
- Manual verification of top-20 (2 hours of human review).

**2c. Ground-truth validation**
- Top-30 chain location counts: Google Places vs chain-locator scrape vs chain investor-deck.
- Build per-chain correction factor table for use with OHSOME.

### Phase 3: Analysis (target: 2–3 days)

Each test from §5 run as a standalone script writing to a per-test JSON output:
- `analysis/p1_tier_spacing.py` → `results/p1.json` + charts.
- `analysis/p2_bf_clustering.py` → `results/p2.json` + cross-K plots per country.
- `analysis/p3_tier_specific_clustering.py` → `results/p3.json` + per-chain table.
- `analysis/p4_temporal.py` → `results/p4.json` + trend chart per country.
- `analysis/bresnahan_reiss.py` (stretch) → `results/bresnahan.json` + coefficient table.
- `analysis/robustness.py` → `results/robustness.json` + appendix table.

All outputs get committed to the repo so the writeup step is deterministic.

### Phase 4: Writeup (target: 2–3 days)

Single source of truth: `writeup/thesis-v2.md` (separate from the v1 thesis — this is a different document for a different audience, ~40–60 pages).

Structure (draft):

I. Executive summary — 1 page, the four findings and what they mean.
II. Why this matters for a Basic-Fit shareholder — 2 pages.
III. The economic theory primer — 5 pages, written for Buffett's smart sister.
IV. Data and sources — 4 pages, with validation sidebar.
V. Methods — 6 pages, math in sidebar boxes.
VI. Results, test by test — 10 pages.
VII. Robustness — 5 pages, appendix-style.
VIII. Limitations and what would change our minds — 2 pages.
IX. Industry implications — 3 pages.
X. References — 3 pages.

Rendering: same HTML + weasyprint PDF pipeline used for thesis v1 (already in app.py at `/thesis` and `/thesis.pdf`). New routes `/thesis-v2` and `/thesis-v2.pdf` — or we version the primary route and keep v1 at `/thesis-v1`.

Interactive layer: per-country catchment explorer (Leaflet map + filters), per-chain clustering visualization, robustness-check sliders. All client-side rendered; raw data served as JSON by Flask.

### Phase 5: Peer review and iteration (target: 1–2 days)

A single Reviewer subagent pass on the combined diff + writeup, calling out:
- Any unstated assumptions.
- Any number cited without a source-of-truth link.
- Any method choice that isn't justified in §5 or supported by a robustness check.
- Rhetorical overclaims ("strong evidence that…" when the data supports "consistent with").

Fixes roll into a second pass. Final deliverable is when Reviewer returns PASS.

**Total estimated timeline: 8–13 working days of Builder + Analyst + Writer subagents, with user review gates at end of Phase 1 (data landed), end of Phase 3 (results landed, before writeup), and end of Phase 4 (writeup landed, before publish). This matches the "build this right" standard.**

---

## 7. Deliverable format

Two linked artifacts:

### 7.1 The interactive research site

Lives at `/gym-intelligence/thesis-v2` on the existing Flask app. Sections:

- **Top band**: the four findings stated in one sentence each. Tap for the chart.
- **The maps**: one per country, toggleable by tier. BF gyms highlighted. Lines to same-tier nearest neighbors colored by "same chain vs not." Default hover info: catchment population, per-chain details.
- **The numbers**: compact tables, sortable, downloadable.
- **The theory**: primer in collapsible sections. Math hidden by default, one-tap to expand.
- **The validation sidebar**: always visible. Shows coverage, known biases, direction of bias per test.
- **The robustness drawer**: toggle between "headline result" and "after robustness check X"; watch the conclusion strengthen or weaken.
- **Download**: PDF version of the same content (static snapshots of the interactive pieces).

### 7.2 The downloadable paper (PDF)

One file, ~40–60 pages, generated by weasyprint from the markdown source. Same content as the site but readable offline. Includes all references and appendices.

Both versions sourced from one markdown file — the web version renders interactive widgets, the PDF renders static chart PNGs at default state.

---

## 8. Cost and capacity planning

**Dollar cost (one-time)**
- Google Places full enumeration: ~$1,000–1,500.
- Claude API calls (classification + pricing scrape + writeup drafting): ~$20–40 (haiku for bulk classification, sonnet for writeup editing).
- **Total: $1,100–1,600 one-time.**

**Dollar cost (recurring)**
- Google Places quarterly refresh at 10% of initial enumeration cost: ~$100–150/quarter.
- Incremental Claude calls for new-chain classification: ~$2–5/quarter.
- **Total: ~$400–650/year.**

**Compute cost**
- All heavy compute on prod droplet (8 GB, 4 core). No external VMs needed unless we go to isochrone-based catchments in v2.
- Disk: Eurostat grid ~5 GB, Google Places SQLite ~500 MB, analysis artifacts ~200 MB. Total <10 GB.

**Wall-clock**
- Phase 1 ingestion: ~1 day elapsed (most of it is Google API wait time).
- Phase 2 classification: <1 hour compute.
- Phase 3 analysis: ~4 hours compute for all tests + robustness.
- Phase 4 writeup: ~2 days elapsed.
- **End-to-end build: ~1 week elapsed if run linearly, ~3–4 days if parallelized.**

---

## 9. Known risks and mitigations

- **Risk: Google Places undercounts independents or has category-drift** (EMS studios tagged as gyms). **Mitigation:** ground-truth against chain locator scrapes for the top 20 chains; discount conclusions in areas where validation shows discrepancy.
- **Risk: Tier classification is subjective, and wrong boundaries corrupt all downstream tests.** **Mitigation:** manual review of top 30 chain classifications; robustness check with ±€5 tier boundary shifts; publish the classification rationale alongside results.
- **Risk: Population grid is 2021 data; population has shifted** (Ukraine war refugee flows in DE/PL; Brexit-driven movements). **Mitigation:** use a 2023 update if Eurostat publishes one before we run; otherwise, note as a time-offset in the validation layer.
- **Risk: Basic-Fit's "cluster strategy" claim might be rhetorical rather than operational**, and the test honestly confirms nothing. **Mitigation:** this isn't really a risk — it's the whole point of doing the test. Frame the writeup to make a null result interesting (as it genuinely would be).
- **Risk: Temporal analysis (P4) is hampered by OHSOME per-chain accuracy**, and any trend we see could be measurement-drift rather than real. **Mitigation:** compute the correction factors per chain per date as a separate artifact and report the trend with bias-corrected confidence bands; flag widely if corrections are large.
- **Risk: Selection effect** — Basic-Fit chose where to enter. A positive clustering result could mean "they caused competitor exclusion" OR "they only entered places competitors would have avoided anyway." **Mitigation:** acknowledge explicitly in the limitations section; note that a natural-experiment test would require a regulation/event that forced random entry ordering, which we can't construct.

---

## 10. Questions for you (user), before Phase 1

These are the open decisions. Everything else I'll call myself per the project autonomy rules.

1. **Budget sign-off for Google Places.** Rough one-time cost $1,000–1,500, recurring ~$500/year. OK to proceed, or do you want a bounded pilot first (single country — say Netherlands — as proof-of-concept for ~$150)?

2. **Market definition for Phase 3.** I'm planning on using 15-km hex cells weighted by population as the "market" unit for the Bresnahan-Reiss-style regression in §5.6. Basic-Fit's investor deck uses 10–15-minute-drive catchments, which maps to roughly the same scale. Happy to use a different unit (municipality boundary? isochrone?). Default stays 15-km hex unless you say otherwise.

3. **Tier-definition validation.** In §4.3 I sketched Tier A/B/C/D/E. Any chain you want to call out in advance as assigned to the wrong tier in your mental model? (Examples in draft: Anytime Fitness in Tier A or B? SportCity in Tier A or B? Club Pilates in Tier D?)

4. **Scope of countries.** Current: NL, BE, FR, ES, LU, DE. Basic-Fit is about to open or has opened in Italy/Poland/Portugal. In scope or explicit v2 only?

5. **Temporal depth.** Current OHSOME backfill goes back 4 years. That's enough for P4 but not for a longer-run "how did the cluster form historically" analysis. Adding Wayback Machine scraping of chain locator pages (free, slow) could extend back to 2015ish for the largest chains. In scope or skip?

6. **Pricing depth.** For the §4.3 pricing definition I'm computing 18-month normalized price. Want to also track joining-fee trends (several chains have eliminated joining fees in the last 2 years — strategic signal in itself) and 24-month / 36-month commitment pricing as additional tiers?

7. **Output venue.** Current plan: `/gym-intelligence/thesis-v2` on the existing site + downloadable PDF. Should this also be pitched to a specific audience externally — e.g., shared with other Basic-Fit shareholders, published on an investment research platform, or kept internal? Changes the tone and what we redact.

8. **Reviewer standards.** What would be the single thing that, if missing from the final paper, would make you dismiss the work? That's the quality bar we'll hold the Reviewer pass to.

9. **Time pressure.** Is there a specific calendar date (earnings call, investment decision, etc.) by which the analysis needs to land? Affects whether we prioritize depth or speed on the stretch goals (Bresnahan-Reiss, Huff-gravity robustness, time-series, additional countries).

10. **Prior related work.** Is there anything you've already read on the gym industry specifically — IHRSA reports, Deloitte's European Health & Fitness Report, sell-side BF analyst notes — that should be cited in the background section rather than rediscovered?

---

## 11. Appendix: working reference list

### Foundational theory
- Christaller, W. (1933). *Die zentralen Orte in Süddeutschland*. Jena: Gustav Fischer.
- Lösch, A. (1940). *Die räumliche Ordnung der Wirtschaft*. Jena: Gustav Fischer.
- Hotelling, H. (1929). "Stability in competition." *Economic Journal* 39: 41–57.
- D'Aspremont, C., Gabszewicz, J. J., & Thisse, J.-F. (1979). "On Hotelling's Stability in Competition." *Econometrica* 47: 1145–1150.
- Salop, S. (1979). "Monopolistic Competition with Outside Goods." *Bell Journal of Economics* 10: 141–156.

### Entry deterrence
- Bresnahan, T. F. & Reiss, P. C. (1990). "Entry in Monopoly Markets." *Review of Economic Studies* 57: 531–553.
- Bresnahan, T. F. & Reiss, P. C. (1991). "Entry and Competition in Concentrated Markets." *Journal of Political Economy* 99(5): 977–1009.
- Mazzeo, M. J. (2002). "Product Choice and Oligopoly Market Structure." *RAND Journal of Economics* 33(2): 221–242.
- Seim, K. (2006). "An Empirical Model of Firm Entry with Endogenous Product-Type Choices." *RAND J. Econ.* 37(3): 619–640.
- Jia, P. (2008). "What Happens When Wal-Mart Comes to Town." *Econometrica* 76(6): 1263–1316.
- Aguirregabiria, V. & Vicentini, G. (2016). "Empirical Games of Market Entry and Spatial Competition in Retail Industries." *Handbook on the Economics of Retailing and Distribution*.

### Spatial statistics
- Ripley, B. D. (1976). "The Second-Order Analysis of Stationary Point Processes." *J. Appl. Prob.* 13: 255–266.
- Baddeley, A., Rubak, E., & Turner, R. (2015). *Spatial Point Patterns: Methodology and Applications with R*. CRC Press.
- Diggle, P. J. (2013). *Statistical Analysis of Spatial and Spatio-Temporal Point Patterns*, 3rd ed. CRC Press.
- Ellison, G. & Glaeser, E. (1997). "Geographic Concentration in U.S. Manufacturing Industries." *JPE* 105(5): 889–927.
- Duranton, G. & Overman, H. (2005). "Testing for Localization Using Micro-Geographic Data." *RES* 72(4): 1077–1106.

### Gravity models
- Reilly, W. J. (1931). *The Law of Retail Gravitation*.
- Huff, D. (1963). "A Probabilistic Analysis of Shopping Center Trade Areas." *Land Economics* 39(1): 81–90.

### Tools
- `pointpats` (Python, PySAL): https://pysal.org/pointpats/
- `rapidfuzz` (Python, string matching): https://github.com/rapidfuzz/RapidFuzz
- `spatstat` (R, reference implementation): https://spatstat.org/
- Eurostat GEOSTAT 2021 grid: https://ec.europa.eu/eurostat/web/gisco/geodata/population-distribution/geostat
- Google Maps Platform Places API: https://developers.google.com/maps/documentation/places

### Industry context
- Basic-Fit N.V. Investor Presentations (2022–2024). https://corporate.basic-fit.com/investors
- IHRSA / EuropeActive Health & Fitness Reports (annual).
- Deloitte *European Health & Fitness Market* (annual).

_End of research plan._
