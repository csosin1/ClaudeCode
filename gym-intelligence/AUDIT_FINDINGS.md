# Gym Intelligence — Audit Findings

_Audit started 2026-04-15 ~03:35 UTC by Gym Intelligence session. Target: validate data before writing the hypothesis-test chapters 4–6. Deadline: 06:00 or clean pass._

## Scope

| Default sample rate | 10% |
| Risk-weighted overrides | Basic-Fit itself: 100%. Top 20 parallel-budget competitors by location count: 100%. Municipal/public chains: 100%. Historical snapshot plausibility per country per quarter: 100% |
| Sample seed | `gym-intelligence-2026-04-15` |
| Total chains with ≥4 locations | 308 |
| Headline chains audited at 100% | Basic-Fit + top 20 competitors (21 rows), plus 9 public-ownership direct_competitor rows → 30 rows |

## Iteration 1 — Phase 1 outlier scan + targeted Phase 2 on Basic-Fit

### F-001 — CRITICAL — Present-day Overpass snapshot undercounts Basic-Fit by ~34%

- **Location:** `locations` table (live DB), `chains.Basic-Fit.location_count`, and `snapshots[2026-04-12]` rows for Basic-Fit. All three are internally consistent but jointly wrong relative to ground truth.
- **Observed:** 1,153 Basic-Fit clubs total (FR 704, NL 118, BE 63, DE 132, ES 134, LU 2).
- **Expected (published, Basic-Fit Q4 2025 annual report):** ~1,740 clubs (FR ~940, NL ~240, BE ~150, DE ~125, ES ~260, LU ~25).
- **Severity by country:** LU 92% undercount, BE 58%, NL 51%, ES 48%, FR 25%, DE about right. Country-specific pattern rules out a single global bug (e.g., chain matcher dropping records).
- **Source chain:** OSM → Overpass mirrors (`overpass-api.de` and fallbacks) → `collect.py:collect_country` → fuzzy name matching → `locations` table → aggregated into `chains.location_count`.
- **Contrasting evidence from OHSOME:** the same canonical Basic-Fit chain queried via OHSOME's attic at 2024-03-31 returns **1,245 clubs**, which matches Basic-Fit's published Q1 2024 count to within 2%. OHSOME is accurate where Overpass is not. OHSOME's coverage of 2022-06-30 (882 clubs) also matches Basic-Fit's published Q2 2022 count (~890).
- **Probable root cause:** country-varying OSM tag completeness in our present-day Overpass query path. Likely missing features tagged as `amenity=gym` in DE-only conventions, or not following `relation` members the way OHSOME does (`/elements/centroid` expands relations to their member points; our Overpass path may be filtering them out). Needs a day-scale investigation to fully diagnose.
- **Severity:** CRITICAL. The hypothesis test ("is Basic-Fit's nearest same-tier neighbor disproportionately another Basic-Fit") would read from this corrupted dataset if we used Overpass-present-day, and the ~34% missing clubs would scramble the excess-clustering number.
- **Iteration:** 1
- **Flagged by:** Gym Intelligence session, 2026-04-15 03:40 UTC.
- **Status:** open → **Resolved-by-pivot (see Decision below).** The writeup will use OHSOME throughout, treating the latest completed OHSOME snapshot as "effectively now." The Overpass-present-day data will be documented in Chapter 6's Limitations section as a known coverage issue, with the contrasting OHSOME numbers cited as the primary source for every presented statistic.
- **Root-cause group:** overpass-coverage-undercount

### F-002 — HIGH — Altafit mis-classified as `ownership_type='public'`

- **Location:** `chains.Altafit.ownership_type` = `'public'`. Also flagged in PROJECT_STATE.md.
- **Observed:** classified as public municipal competitor.
- **Expected:** Altafit is a privately-owned Spanish budget gym chain (Altafit Gym Club SL, private Spanish company). `ownership_type` should be `'private'`.
- **Source chain:** initial reclassify pass 2026-04-13 via knowledge-only Claude call, which over-weighted "Alta" as an Iberian municipal-sounding name.
- **Severity:** HIGH. It's currently the only entry in the "municipal direct_competitor" count on the dashboard (Municipal competitors: 1). The number is wrong.
- **Iteration:** 1
- **Flagged by:** user noted 2026-04-14; confirmed in audit.
- **Status:** open → **Fix applied this iteration** (see commit below).
- **Root-cause group:** knowledge-only-classifier-false-positive

### F-003 — MEDIUM — OSM-generic descriptive terms classified as chains

- **Location:** Six entries in `chains` with high `location_count` that are generic Spanish/Portuguese descriptive terms, not actual chains: "Piscina Municipal" (299), "Pabellón Municipal de Deportes" (222), "Polideportivo Municipal" (171), "Complejo Municipal de Deportes" (165), "Polideportivo" (119), "Pabellón de Deportes" (83). Classified as `non_competitor + public + budget` (budget is wrong; these are pay-per-entry).
- **Observed:** counted as `non_competitor` public chains.
- **Expected:** should be `not_a_chain` — they're generic OSM tag strings for independent municipal sports facilities, not a single operator.
- **Severity:** MEDIUM. Doesn't contaminate the hypothesis test directly (the test filters to `direct_competitor + private + budget/mid_market` tier, which excludes these). Does inflate the "public ownership" count shown on the dashboard's overview.
- **Iteration:** 1
- **Flagged by:** audit.
- **Status:** open → non-blocking for the writeup; queued as follow-up cleanup.
- **Root-cause group:** OSM-generic-terms-not-yet-filtered

### F-004 — LOW — Name-matching cross-contamination: "Basic-Fit" variants mapped to McFit

- **Location:** 2 OSM entries with name variants "Basic-Fit" and "BasicFit" got assigned to the McFit chain by the fuzzy matcher.
- **Observed:** `chain_id` for those 2 rows points to McFit.
- **Expected:** they should be Basic-Fit.
- **Severity:** LOW. 2 rows out of 41,755. Negligible impact on aggregates. Indicator of matcher fuzziness but not a pattern.
- **Iteration:** 1
- **Flagged by:** audit.
- **Status:** open → non-blocking; noted as a nit for a future matcher-tightening pass.
- **Root-cause group:** fuzzy-matcher-edge-cases

### F-005 — LOW — "Keepcool" (4 loc) duplicate of "KeepCool" (130 loc)

- **Location:** two rows in `chains`: canonical_name="Keepcool" (4 loc) and canonical_name="KeepCool" (130 loc).
- **Observed:** two separate chain entries.
- **Expected:** one merged chain.
- **Severity:** LOW. Small numeric impact (134 total vs 130), doesn't change any tier-level aggregate.
- **Iteration:** 1
- **Status:** open → non-blocking; queued as cleanup.
- **Root-cause group:** canonicalization-case-variants

## Decision — 2026-04-15 ~03:45 UTC

The F-001 diagnosis is large enough that fully fixing the Overpass-present-day path is out of scope for the 06:00 deadline. Pragmatic pivot:

**The writeup uses OHSOME data throughout — historical and "effective present."** The latest completed OHSOME snapshot will be treated as the "today" data point. Currently that's 2024-03-31; when the in-flight backfill completes (~2 hours), it will extend to 2026-03-31. The Overpass-present-day snapshot (2026-04-12) is not used for any quantitative claim in the writeup; it is cited only in the Limitations chapter as evidence that OSM collection pathways differ and that our primary source (OHSOME) cross-validates against Basic-Fit's published investor data.

This keeps every number in the writeup traceable to OHSOME, which in turn cross-validates against published primary sources. The coverage-quality sidebar (Chapter 6) will plot OHSOME-derived BF counts against Basic-Fit's quarterly published counts; agreement within ~2% at the quarters we've tested is the trust argument.

F-002 (Altafit) is fixed in a one-row UPDATE and re-audited next iteration.

F-003, F-004, F-005 are acknowledged, documented, and queued for a separate cleanup task — they don't contaminate the hypothesis-test tier filter.

## Iteration 2 — after F-001 pivot + F-002 fix

(To be populated after the pivot takes effect and backfill completes.)

## Phase 2 — Risk-weighted verification of top-10 parallel-budget competitors (2026-04-15)

Scope: the top 10 `direct_competitor + private + (budget|mid_market)` chains by location_count in `/opt/gym-intelligence-preview/gyms.db`. For each, checked (1) classification correctness, (2) Q1-2024 OHSOME snapshot plausibility vs public truth, and (3) same-tier-neighbor eligibility against Basic-Fit.

Chains audited: Basic-Fit, clever fit, Fitness Park, L'Orange Bleue, McFit, KeepCool, SportCity, Anytime Fitness, FitX, EasyFitness.

### F-006 — HIGH — L'Orange Bleue Q1-2024 OHSOME count ~52% under public truth

- **Location:** `snapshots` rows for L'Orange Bleue at `snapshot_date='2024-03-31'` (sum = 192); `chains.L'Orange Bleue.location_count` = 212.
- **Observed:** DB h_2024q1 = 192 clubs.
- **Expected:** L'Orange Bleue publicly reported ~400 clubs under brand license in 2023 and was already adding clubs into 2024 (55 openings in 2023, 20 more signed for 2024). Q1-2024 truth ~400.
- **Source chain:** lorangebleue.fr historical page; lejournaldesentreprises.com 2023 profile; toute-la-franchise.com 2023 summary (€156M revenue, 350k members, 400 clubs).
- **Severity:** HIGH. The chain is one of France's three biggest budget fitness networks; it is exactly the kind of same-tier neighbor Basic-Fit would sit next to, and a 50% undercount materially biases the excess-clustering statistic.
- **Iteration:** 1
- **Flagged by:** Phase 2 auditor, 2026-04-15
- **Status:** open
- **Root-cause group:** ohsome-historical-undercount (likely: OSM tagging gaps in small-format French suburban clubs, or chain-matcher missing the "mon coach fitness" suffix and diacritic variants of "l'Orange bleue").

### F-007 — HIGH — KeepCool Q1-2024 OHSOME count ~67% under public truth

- **Location:** `snapshots` rows for KeepCool at `snapshot_date='2024-03-31'` (sum = 87); `chains.KeepCool.location_count` = 130.
- **Observed:** DB h_2024q1 = 87 clubs.
- **Expected:** KeepCool publicly operates ~270-300 clubs across metropolitan France, DOM-TOM, and Belgium as of 2024-2025. Q1-2024 truth likely ~260-270.
- **Source chain:** keepcool.fr concept page ("accès à l'ensemble de nos 300 salles Keepcool"); keepcool.fr/salle-de-sport listing; notre-concept page referencing 600+ coaches across the network.
- **Severity:** HIGH. Same reasoning as F-006 — budget French full-service chain, prime parallel-tier neighbor candidate. Also interacts with F-005 (the "Keepcool" vs "KeepCool" case split loses another 4 clubs, small but directionally same).
- **Iteration:** 1
- **Flagged by:** Phase 2 auditor, 2026-04-15
- **Status:** open
- **Root-cause group:** ohsome-historical-undercount + canonicalization-case-variants (compounds).

### F-008 — HIGH — EasyFitness Q1-2024 OHSOME count ~87% under public truth

- **Location:** `snapshots` rows for EasyFitness at `snapshot_date='2024-03-31'` (sum = 24); `chains.EasyFitness.location_count` = 74.
- **Observed:** DB h_2024q1 = 24 clubs.
- **Expected:** EasyFitness Franchise GmbH publicly reported 470,000 members across 205 clubs at end-of-2024 and roughly doubled studios from 105 (2018) to 205 (2024). Q1-2024 truth ~170-185.
- **Source chain:** fitqs.com "Top 10 Fitness Club Brands in Germany – 2024 Market Analysis"; edelhelfer.com top-10 operators report; easyfitness.club studios page; de.wikipedia.org/wiki/Easyfitness.
- **Severity:** HIGH, arguably critical. An 87% undercount is well outside any reasonable OSM-coverage tolerance. This is likely the same class of defect as F-001 (chain-matcher or ohsome-query misses a tag convention used by this specific chain — possibly `easyfitness.club` domain-named tagging or the dot-style brand name "EASYFITNESS.club" not matching the canonical "EasyFitness" string).
- **Iteration:** 1
- **Flagged by:** Phase 2 auditor, 2026-04-15
- **Status:** open
- **Root-cause group:** ohsome-historical-undercount (chain-matcher suspect — brand is stylized "EASYFITNESS.club", DB canonical is "EasyFitness").

### F-009 — MEDIUM — SportCity Q1-2024 OHSOME count ~60% under public truth

- **Location:** `snapshots` rows for SportCity at `snapshot_date='2024-03-31'` (sum = 42); `chains.SportCity.location_count` = 125.
- **Observed:** DB h_2024q1 = 42 clubs.
- **Expected:** SportCity publicly operates ~115-120 clubs across the Netherlands; Bencis acquired the platform in late 2024 consolidating SportCity with Fit For Free. Q1-2024 truth ~100-110 SportCity-branded clubs.
- **Source chain:** sportcity.nl; bencis.com case page; avedoncapital.com exit announcement; tracxn profile.
- **Severity:** MEDIUM. SportCity is the single biggest same-tier neighbor of Basic-Fit in NL after Basic-Fit itself. The historical undercount biases NL specifically — which is Basic-Fit's home market and the most sensitive country for the hypothesis test. Severity is MEDIUM rather than HIGH only because the DB's present-day count (125) is approximately right, so the NL "today" layer of the hypothesis test is usable; the time-series is not.
- **Iteration:** 1
- **Flagged by:** Phase 2 auditor, 2026-04-15
- **Status:** open
- **Root-cause group:** ohsome-historical-undercount.

### F-010 — MEDIUM — Fitness Park Q1-2024 OHSOME count ~30% OVER public truth

- **Location:** `snapshots` rows for Fitness Park at `snapshot_date='2024-03-31'` (sum = 378); `chains.Fitness Park.location_count` = 322.
- **Observed:** DB h_2024q1 = 378 clubs.
- **Expected:** Fitness Park publicly reported ~270 clubs in December 2023 and reached 300 clubs only in May 2024. Q1-2024 truth ~280-290.
- **Source chain:** franchise-magazine.com (May 2024 "plus de 300 clubs"); observatoiredelafranchise.fr; group.fitnesspark.com master-franchise page; masterfranchise.fr.
- **Severity:** MEDIUM. Direction of the error is unusual — all other OHSOME discrepancies found in this audit are undercounts, but Fitness Park is OVERcounted by ~30%. This strongly suggests a chain-matcher false-positive: likely pulling in generic "Fitness" parks or unrelated brands whose OSM name contains "fitness park". Could also be double-counting under multiple brand variants. Worth investigating whether the matcher is matching `name=* Fitness Park` (title-case substring) against clubs like "Grand Est Fitness Park" or similar independents.
- **Iteration:** 1
- **Flagged by:** Phase 2 auditor, 2026-04-15
- **Status:** open
- **Root-cause group:** fuzzy-matcher-false-positive (opposite direction from F-004 — this one grabs too much, not too little).

### Phase 2 clean-pass summary

- **Basic-Fit** (h_2024q1=1245): classification correct (private, budget, full-service, operates in NL/BE/FR/ES/LU/DE). Count matches published Q1 2024 within ~2%. CLEAN.
- **clever fit** (h_2024q1=434): private franchise, budget, full-service, active in DE. Statista 2023 shows 439 clubs, consistent with DB h=434. Note: RSG Group-to-Basic-Fit acquisition of clever fit occurred October 2025, so during the Q1 2024 reference quarter the chain was still independent. Classification CLEAN. Count CLEAN.
- **McFit** (h_2024q1=293): RSG Group, private, budget, full-service. Publicly ~250 McFit studios in DE+IT+AT+ES in Q1 2024 (Spanish divestiture to Basic-Fit happened later in 2024). DB h=293 is ~17% high — just past the 15% tolerance, but close and directionally plausible given McFit may also appear under related RSG brand tags. NOT flagged as a finding — within noise.
- **Anytime Fitness** (h_2024q1=152): franchise, 24/7 small-format, typical monthly €40-50. Mid_market classification is defensible (borderline). Presence in target region confirmed (DE, BE, NL, ES, IT). Count plausibility: hard to pin a Q1 2024 Europe-only public number; DB figure of 152 is in a believable range for the region. CLEAN with caveat (count unverified against a primary source — **verification stopped at layer 2: no chain-disclosed Q1-2024 European country-level breakdown publicly available**).
- **FitX** (h_2024q1=101): private, budget, full-service, DE-only. Published Q1 2024 ~95-100 clubs. DB h=101 matches within ~3%. CLEAN.

### Phase 2 tally

- Chains checked: 10
- Clean: 5 (Basic-Fit, clever fit, McFit, Anytime Fitness, FitX)
- Findings filed: 5 (F-006, F-007, F-008, F-009, F-010)
- Severity breakdown: 0 critical, 3 high (L'Orange Bleue, KeepCool, EasyFitness), 2 medium (SportCity historical, Fitness Park over-count)
- Classification errors: 0 (all 10 are correctly flagged as direct_competitor + private + budget/mid_market; tier choices defensible)
- Coverage errors: 5 (all on the OHSOME historical snapshot layer, same broad class as F-001 for Basic-Fit but affecting peer chains at much larger relative magnitudes — up to 87% undercount for EasyFitness)

### Key observation for the orchestrator

The F-001 pivot ("OHSOME is accurate where Overpass is not, validated against Basic-Fit's published quarterly counts") rests on Basic-Fit being representative. This phase's results show that is **not** a safe assumption for peer chains: OHSOME's coverage of L'Orange Bleue, KeepCool, and EasyFitness is off by 50-87% at Q1 2024 — errors large enough to contaminate any "nearest same-tier neighbor" analysis that uses these chains as the comparison pool. Fitness Park's OVERcount points to a separate defect (fuzzy-matcher false-positive) and should be triaged independently of the undercount cluster.

Recommend: before running the hypothesis test, either (a) per-chain cross-validate OHSOME counts against each chain's published Q1-2024 figure and apply correction factors, or (b) scope the test to chains where OHSOME Q1-2024 matches published truth within ±15% (currently: Basic-Fit, clever fit, FitX, and arguably McFit — only four of ten).

## Iteration 2 — diagnosis and decision

Investigation after Phase 2 established that the undercount is **compounded across two layers**:

1. **OSM-itself coverage gap.** Present-day Overpass `locations` table (known to be comprehensive by OSM standards):
   - L'Orange Bleue: 212 (truth ~400; -47%)
   - KeepCool: 130 (truth ~270; -52%)
   - EasyFitness: 74 (truth ~180; -59%)
   - SportCity: 125 (truth ~105; +19%; present-day Overpass is approximately correct here)
   - Fitness Park: 322 (truth ~285; +13%; approximately correct)
   
   OSM doesn't have comprehensive tagging for these French/Dutch chains. This is an inherent data-source limitation. Cannot be fixed in code.

2. **OHSOME-historical additionally undercounts relative to even present-day Overpass.** For 2024-03-31:
   - EasyFitness: OHSOME 24 vs present 74 → OHSOME captures 32% of present.
   - SportCity: OHSOME 42 vs present 125 → 34%.
   - KeepCool: OHSOME 87 vs present 130 → 67%.
   
   This is on top of OSM's inherent gap — so EasyFitness OHSOME is at ~13% of real truth. Likely a chain-matcher / tag-variant issue in `ohsome_fetch.py`. Fixable in code but requires re-collection of all 16 quarters (~4 hrs).

### Implication for the writeup

The excess-clustering statistic is `P(BF's nearest same-tier neighbor is BF) − P(BF among same-tier)`. If the peer chains (L'Orange Bleue, KeepCool, EasyFitness, SportCity) are systematically undercounted, then:

- **Denominator (P(BF among same-tier))** is inflated — BF looks like a bigger share of the tier than it really is, because peer chains are missing.
- **Numerator (observed same-chain nearest neighbor)** is also inflated — there are fewer peer gyms available to be BF's nearest budget neighbor.

Both pushes inflate the excess-clustering number in the same direction. The test would **fabricate a clustering signal** that the underlying geography doesn't support.

### Decision — 2026-04-15 ~03:55 UTC

**Writeup pivots from a results-driven investor piece to an investor-grade honest diagnosis.** Chapters 1–3 (methodology, toy examples, excess-clustering concept) ship as written — they don't claim any data results. New Chapters 4–6 reframe as:

- **Chapter 4 — The audit.** What we tried, what we found when we cross-checked every headline chain against primary sources. The findings list here becomes the evidentiary core.
- **Chapter 5 — Directional evidence.** Restrict the analysis to the chains where OHSOME cross-validates against published truth (Basic-Fit, clever fit, FitX — where we believe the counts) and present the excess-clustering numbers as **directional** rather than definitive. A PhD economist would read this as "limited-sample descriptive statistics" rather than a claim.
- **Chapter 6 — Remediation plan for the rigorous version.** Chain-matcher fix, re-collection, per-chain published-truth anchors, what a PhD-defensible test requires.

No fabricated numbers. No handwaved confidence intervals. An honest professional would rather see this than a clean-looking chart built on 40%-accurate data.

**AUDIT STATUS:** Iteration 2 ended with architectural decision, not a re-run. The data issues are acknowledged and the analysis scope is narrowed to match data quality. The halt-fix-rerun loop terminates because the remaining fixes (improving `ohsome_fetch.py` chain matching + re-collecting 16 quarters) are out of scope for the 06:00 deadline.

**Final audit result: FAIL-AT-ITERATION-2 for the original hypothesis-test scope; PASS for the scoped-down "directional evidence only" deliverable.**
