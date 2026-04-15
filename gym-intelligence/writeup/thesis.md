---
title: "Is Basic-Fit's Moat Real? Testing the Cluster Strategy on a Map"
subtitle: "Chapters 1–3: Why the Hypothesis Matters, What Clustering Looks Like, and the Simplest Test"
date_drafted: 2026-04-13
word_count_estimate: 4400
status: draft — conceptual portion only; data chapters (4–6) pending backfill
---

# Chapter 1 — Why this matters and what Basic-Fit claims

## A scene in a small Dutch city

Picture a city of roughly 120,000 people somewhere in the eastern Netherlands. It is not Amsterdam or Rotterdam; it has one high street, one university of applied sciences, a ring road, and three neighborhood clusters of apartment blocks at the edges. There is already a Basic-Fit here. In fact, there are three: one on the high street, one inside the new-build district to the north, one attached to a retail park to the south. Rent on all three was negotiated when the buildings first went up.

Now suppose a competitor — a regional budget chain, or a would-be new entrant with financing — is looking at this city on a map. What do they see, and what do they calculate?

They see that any location they pick is within a few kilometers of an existing Basic-Fit. They can count members-per-gym in the Dutch market and work out roughly how many paying members a city of 120,000 can support at the €20-something per month price point. Then they have to ask the decisive question: *of that total addressable pool, how many are already walking past a Basic-Fit on their way home from work?* If the answer is "most of them, because the three Basic-Fits already cover the three residential clusters," then the entrant's catchment is not the whole city; it is whatever sliver of the city lives closer to them than to any Basic-Fit. That sliver may not support a gym at break-even.

They do not enter. The city stays a three-Basic-Fit city.

This is the story Basic-Fit tells its shareholders. The claim is not that Basic-Fit is better than its competitors on amenities, or cheaper, or run more efficiently — though it may be all of those things. The claim is about **geometry**: that by putting gyms close enough together to cover a market's natural catchments, Basic-Fit leaves no profitable hole for a parallel-tier competitor to slip into.

This write-up asks whether that story is true.

## Basic-Fit, briefly

Basic-Fit N.V. is a Netherlands-headquartered operator of budget full-service fitness clubs, listed on Euronext Amsterdam. As of its most recent investor update it operates on the order of [CLUBS_TOTAL] clubs across six Western European countries — the Netherlands, Belgium, Luxembourg, France, Spain, and Germany — and targets a monthly membership price at or below the [PRICE_POINT] mark. The product is deliberately narrow: a large room of cardio and resistance machines, a functional area, showers, 24-hour access at many locations, and — crucially — almost nothing else. No pool, no classes beyond a virtual offering, no juice bar, no towel service. The business model is high member-count per square meter at a low price per member, and it depends on keeping fixed costs per location below a threshold that the local membership base can comfortably cover.

Two features of that business model matter for everything that follows. First, the gym is a **local** product: members rarely travel more than fifteen or twenty minutes to reach it, because at this price point the whole proposition is "cheap and convenient," and convenience is geographic. Second, the fixed costs per location are **lumpy**: a Basic-Fit club has a roughly similar footprint and build-out wherever it opens, meaning a location either clears its fixed-cost hurdle or it does not. There is little middle ground. These two features together are what give geography its teeth in this industry.

## The cluster claim

In investor materials — annual reports, capital markets days, quarterly presentations — Basic-Fit describes its growth approach in language that, paraphrased, runs roughly as follows: the company enters a country, opens enough clubs in each metropolitan area to cover the catchments a member would naturally reach, and continues opening until the market is saturated enough that a parallel-tier competitor would struggle to find a catchment the company has not already claimed. The specific word the company uses for this is **cluster**. The specific mechanism is **density as deterrence**.

The claim has two parts, and it is worth separating them. The first part is a statement about **Basic-Fit's own location choices**: that Basic-Fit places its clubs near other Basic-Fits on purpose, in configurations that saturate a catchment rather than spread one club per city. The second part is a statement about **the effect on competitors**: that once a catchment is saturated, a parallel-tier entrant cannot profitably open there, and so does not.

The first part is an empirical claim about the map today. You can see it by looking. The second part is a counterfactual — it is about the entrants who *did not* arrive — and you can only see it indirectly, by watching entry rates in dense versus sparse Basic-Fit catchments over time and comparing them.

This write-up tests both parts. Chapters 2 and 3 address the first: does the map look clustered, in a way random location choice would not produce? Chapter 4 extends that across spatial scales. Chapters 5 and 6 address the second: do competitors actually stay away from dense Basic-Fit catchments?

## Why this matters for a shareholder

If the cluster claim is true — if density really does deter parallel-tier entry — then Basic-Fit's mature markets are considerably more defensible than a naive location count suggests. A count tells you Basic-Fit operates N clubs in the Netherlands. Defensibility tells you what happens when an ambitious competitor tries to take those members. If the cluster strategy works, the answer is "very little, because the competitor cannot economically reach them." Basic-Fit's mature-market clubs then throw off pricing power and resilient cash flows, and the multiple the market pays for those cash flows should reflect the moat.

If the cluster claim is false — if Basic-Fit's location pattern is no more clustered than chance, or if dense catchments draw in competitors just as readily as sparse ones — then every new budget entrant is a genuine threat to mature-market economics, and the investor case rests on operational execution rather than structural defense. Those are two very different investments.

This is a load-bearing hypothesis. It is also, it turns out, a testable one. The data required are geographic coordinates of gyms, a tier classification for each gym, and four years of snapshots to watch the pattern move. All of that is available — imperfectly, but available — in open-source mapping data. We will test this hypothesis three ways, starting with what you can see on a map.

---

# Chapter 2 — What clustering would look like

Before running any statistics, it helps to know what we are looking for. Clustering is a word that gets used loosely; a pile of gyms in the middle of a city is not, by itself, evidence of a cluster *strategy*, because gyms and people go together and people pile up in the middle of cities too. What we want is something sharper: a specific pattern on the map that a deliberate clustering strategy would produce and that random location choice would not.

## Gyms, customers, and territories

Begin with the consumer. A member of a budget gym is choosing among options that look, from across the street, mostly alike: a large floor of cardio and resistance equipment, a locker room, a low monthly price. The brand matters less at this tier than it does in, say, luxury goods, and the amenity set is nearly fixed by the tier itself. What is left to choose on is **proximity**: which of the budget-tier gyms is closest to where the member lives or commutes?

That question has a clean geometric answer. If we draw all the budget-tier gyms as dots on a map, and we draw, for every point in the city, a line to the nearest dot, then we have partitioned the city into **territories** — one per gym. Every household inside a territory is, by distance, "captured" by that gym. Every household outside it is captured by someone else. This partition is called a **Voronoi tessellation**, after the mathematician who formalized it, and it is the single most useful picture to have in mind for the rest of this chapter.

**Figure 2.1.** A toy city with four same-tier gyms shown as colored dots, and the Voronoi tessellation drawn as dashed lines. Each gym's shaded polygon is the set of locations closer to it than to any other gym — its territory, or catchment. (Image: `fig-2-1-voronoi-toy.png`, to be rendered separately.)

The picture is a useful simplification, not the whole truth. Real catchments deform around rivers, rail lines, and one-way streets; a fifteen-minute *isochrone* — the set of points actually reachable in fifteen minutes — looks lumpier than the straight-line polygon, especially in mixed urban/rural geography. But the first-cut intuition is exactly the Voronoi picture: each gym owns the people closer to it than to any rival in its tier, and competition happens at the dashed-line boundaries.

> **Sidebar: formal definition of a Voronoi tessellation.** Given a finite set of points $P = \{p_1, \ldots, p_n\}$ in $\mathbb{R}^2$, the Voronoi cell of $p_i$ is the set
> $$V(p_i) = \{x \in \mathbb{R}^2 : d(x, p_i) \le d(x, p_j) \text{ for all } j \ne i\},$$
> where $d(\cdot,\cdot)$ is Euclidean distance. The Voronoi tessellation is the collection $\{V(p_i)\}_{i=1}^n$; it partitions the plane up to boundaries of measure zero. In this write-up we use Voronoi cells as catchment approximations; chapter 4 notes the isochrone-based refinement and why it mostly does not change the qualitative signal.

## Two regimes

With the territory picture in hand, we can sketch what two very different worlds would look like. Both worlds have the same number of gyms and the same number of chains. Only the *placement rule* differs.

**Figure 2.2.** Two toy markets, each with four Basic-Fits (yellow) and six competitors (red). In the top panel, all ten gyms are scattered uniformly at random across the map. In the bottom panel, the four Basic-Fits are deliberately placed together on one side of the map and the six competitors on the other. In the random panel, each Basic-Fit's nearest same-tier neighbor is roughly as likely to be red as yellow. In the clustered panel, each Basic-Fit's nearest same-tier neighbor is almost always another yellow dot. (Image: `fig-2-2-random-vs-clustered.png`, to be rendered separately.)

Look at the **random** panel first. With four yellows and six reds scattered uniformly, if you stand on any yellow dot and ask "what color is my nearest same-tier neighbor?", the answer depends on who happens to have landed nearby. Roughly six-tenths of the time the nearest neighbor will be red, because six out of the nine other same-tier gyms are red. This is the random-assortment baseline: the probability of matching your own color is just your share of the overall tier.

Now look at the **clustered** panel. The yellows sit close together on the left half; the reds sit close together on the right. Stand on any yellow dot and ask the same question. Your nearest same-tier neighbor is almost certainly yellow, because the nearest reds are across the map. The observed same-color match rate is close to one hundred percent, even though yellows are only four out of ten. The gap between that near-one-hundred and the random-baseline forty percent is the **fingerprint of clustering**.

That is the central testable insight of this document, and it is worth stating in one sentence before we move on:

> **In a clustered market, each Basic-Fit gym's nearest same-tier neighbor is disproportionately another Basic-Fit, beyond what the chain's overall share of the tier would predict.**

Chapter 3 formalizes that sentence into a number.

> **Sidebar: classical models of spatial competition.** The idea that firms selling close substitutes should space themselves approximately uniformly across a market — and that the size and spacing of settlements should obey regular geometric rules driven by trade-area economics — goes back at least to Christaller (1933) and the Central Place Theory tradition, and to the circular-city models of Salop (1979), in which symmetric firms arrange themselves equidistantly around a ring of consumers. The baseline prediction of those models, under uniform demand and uniform transport costs, is *uniform spacing within a tier* — which is what the absence of a clustering strategy would look like. Deviations from that baseline in one direction (tightly bunched same-chain gyms, thinly populated catchments elsewhere) are precisely what we are calling a cluster strategy. The classical literature also establishes the language we use later: tier-level competition, catchment areas, and the notion that entry decisions are made against a given placement of incumbents.

## Why proximity matters so much in gyms specifically

The whole argument depends on the premise that budget-gym customers optimize on distance more than on anything else. That premise is worth defending briefly, because the entire chain of logic from Voronoi territories to testable clustering unravels if customers do not in fact choose on proximity.

The empirical picture, drawing on consumer-survey work in the fitness industry (IHRSA, 2022; various European market reports), runs roughly as follows. Median member travel time to a gym is on the order of ten to fifteen minutes. Well over half of members say they would switch gyms rather than increase their travel time by five or ten minutes. Drop-off rates — the share of new members who quit within a few months — correlate strongly with distance: members whose gym is more than a twenty-minute one-way trip quit at noticeably higher rates than those within ten minutes. The directional story is clear and mostly uncontroversial in the industry: gym usage is a habit, habits live on the path between home and work, and any friction in the form of extra travel kills the habit.

Compare this to two nearby product categories. Groceries look similar: consumers travel a similar short distance for routine shopping, and supermarkets famously compete on catchment geography. Luxury goods look very different: a buyer of a high-end handbag will happily travel across a city, or fly to a different city, for the right store. Budget gyms are squarely in the grocery-like regime. It follows that at the budget tier, where the product is commoditized and the price spread is narrow, **distance does almost all of the choosing**. Two gyms at the same tier two kilometers apart are not really in direct competition for the same customer; two gyms at the same tier three hundred meters apart are fighting for nearly the same pool.

This is the reason the geometric test of Chapter 3 has any power. If budget members chose on brand, clustering would be invisible: a Basic-Fit next door to another Basic-Fit would simply split a loyal base. Because they choose on distance, clustering is both observable (the pattern is a blunt feature of the map) and economically meaningful (the pattern is what determines whether a rival can profitably open).

---

# Chapter 3 — The simple test: excess clustering

## The intuition

Here is the whole idea in plain language. Suppose Basic-Fit operates six of the ten budget-tier gyms in some country. If Basic-Fit had placed those six gyms by dropping pins uniformly at random on the map, then whenever you stand on a Basic-Fit and look around for the nearest other budget-tier gym, that neighbor should be another Basic-Fit about six out of nine times — because six of the nine remaining same-tier gyms are Basic-Fits. Call this the **random-assortment baseline**: the probability of a same-chain nearest neighbor is just the chain's share of the tier.

Now suppose that when you actually look at the map, the nearest same-tier neighbor of a Basic-Fit is another Basic-Fit eight times out of nine — eighty-nine percent — rather than sixty-seven. The gap between the observed eighty-nine and the baseline sixty-seven — twenty-two percentage points — is **excess clustering**. It is the share of Basic-Fit gyms whose placement cannot be explained by random draws from the tier. It is, in other words, the fingerprint left on the map by a deliberate clustering strategy.

Nothing about this test requires advanced statistics. It requires counting.

## A worked example: the country of Oranjia

Let us do the arithmetic on a fictional country with ten budget-tier gyms. Call it Oranjia. Six are Basic-Fit (yellow, BF1 through BF6). Four are a competitor (red, C1 through C4). The chain share of Basic-Fit in Oranjia's budget tier is therefore $6/10 = 60\%$.

**Figure 3.1.** The country of Oranjia. Ten budget-tier gyms plotted on a stylized national map: six Basic-Fits (yellow) clustered in two metropolitan areas, four competitors (red) spread across the remaining geography. Each gym has a short arrow pointing to its nearest same-tier neighbor. (Image: `fig-3-1-oranjia-toy.png`, to be rendered separately.)

For each Basic-Fit gym, we identify its nearest same-tier neighbor — the closest *other* budget-tier gym of any chain — and record whether that neighbor is another Basic-Fit or a competitor.

| Gym  | Chain      | Nearest same-tier neighbor | Neighbor chain | Same chain? |
|------|------------|----------------------------|----------------|-------------|
| BF1  | Basic-Fit  | BF2                        | Basic-Fit      | yes         |
| BF2  | Basic-Fit  | BF1                        | Basic-Fit      | yes         |
| BF3  | Basic-Fit  | BF4                        | Basic-Fit      | yes         |
| BF4  | Basic-Fit  | BF3                        | Basic-Fit      | yes         |
| BF5  | Basic-Fit  | BF6                        | Basic-Fit      | yes         |
| BF6  | Basic-Fit  | C2                         | Competitor     | no          |

Observed same-chain match rate across the six Basic-Fits: $5/6 \approx 83.3\%$.

Random-assortment baseline: the probability that a randomly chosen "other" budget-tier gym is a Basic-Fit. From a single Basic-Fit's perspective, five of the remaining nine same-tier gyms are also Basic-Fits, so the baseline is $5/9 \approx 55.6\%$. (A simpler and nearly identical approximation uses the overall chain share of sixty percent; for the populations we work with in the real data, the difference between these two baselines is negligible and we use the overall-share version for simplicity.)

Excess clustering: $83.3\% - 55.6\% \approx 27.7$ percentage points.

That single number — roughly twenty-eight percentage points of excess clustering in Oranjia's budget tier — is the headline finding the rest of this document will generalize, country by country and quarter by quarter. A large positive number means Basic-Fits are placed next to other Basic-Fits far more often than random assortment predicts. A number close to zero means placement is indistinguishable from random. A negative number — Basic-Fits systematically further from other Basic-Fits than chance would predict — would indicate the opposite of clustering, a kind of anti-cluster or dispersal pattern, which is what a pure white-space strategy would look like.

> **Sidebar: formal definition of excess clustering.** Let $S$ be the set of same-tier gyms in some country at some snapshot, let $B \subseteq S$ be the subset belonging to the chain under test (here, Basic-Fit), and let $\text{NN}(g)$ denote the nearest same-tier neighbor of gym $g$ among $S \setminus \{g\}$. Define
> $$\hat{p}_{\text{obs}} = \frac{1}{|B|} \sum_{g \in B} \mathbf{1}\{\text{NN}(g) \in B\}, \qquad \hat{p}_{\text{exp}} = \frac{|B|}{|S|}.$$
> The **excess clustering** statistic is $\Delta = \hat{p}_{\text{obs}} - \hat{p}_{\text{exp}}$, reported in percentage points. A more careful baseline uses $(|B|-1)/(|S|-1)$ rather than $|B|/|S|$, reflecting that the focal gym is drawn without replacement from the tier; for $|S|$ in the dozens or larger the two forms agree to within a percentage point. This statistic is equivalent to the value of the **mark-connection function** $p_{BB}(r)$ evaluated at the nearest-neighbor distance, where marks are chain identities; we return to mark-connection functions and Ripley's cross-$K$ in Chapter 4, which generalize the same question to all distance scales rather than only the nearest.

## Why this test survives imperfect data

The geographic data we use comes from OpenStreetMap (OSM), a volunteer-contributed global map. OSM is excellent, and for gyms in Western Europe it is likely the best systematic source that exists outside of each chain's own books. It is also, unavoidably, **incomplete and time-varying in its completeness**: the share of real-world gyms actually present in OSM was lower in 2022 than it is in 2026, because the map keeps getting filled in. A naive analysis — "there were N budget gyms in Germany in 2022 and N' in 2026" — would partly measure real entry and partly measure OSM catching up.

The excess clustering statistic is almost entirely immune to this. The reason is that it is a **within-tier, within-snapshot ratio**. Both the numerator (observed same-chain match rate) and the denominator (chain's share of the tier) are computed on the same set of gyms at the same moment in time. If OSM coverage improves uniformly from seventy percent to ninety percent across both Basic-Fit and its competitors in the same country between 2022 and 2026, the additional gyms fill in both the yellow and the red dots proportionally, and the ratio is unchanged. Coverage drift would only bias the statistic if it were **differential by chain** — if OSM were, for some reason, systematically better at capturing Basic-Fits than at capturing competitors. This is possible in principle, and chapter 6's validation sidebar explicitly checks the OSM Basic-Fit count against Basic-Fit's investor-reported count quarter by quarter, but there is no obvious mechanism that would produce a large bias, because the underlying OSM tagging conventions (the `leisure=fitness_centre` tag and its relatives) are chain-agnostic.

## Where this test falls short

The simple test has two honest limitations, and it is better to state them plainly than to discover them later.

First, it only looks at the **nearest** neighbor. If Basic-Fit's clustering strategy operates at the scale of a five-hundred-meter radius — picking the other side of a busy boulevard, say — the nearest-neighbor test will catch it. But if the strategy operates at the scale of a three-kilometer radius — saturating a neighborhood with two or three clubs spaced across it — the nearest-neighbor test may miss part of the signal, because any one Basic-Fit's *single* nearest same-tier neighbor will be captured but its second, third, and fourth same-tier neighbors (which under clustering should also disproportionately be Basic-Fits) are not counted. The fix is **Ripley's cross-$K$** function and the **mark-connection function** $p_{BB}(r)$, which ask the same question at every distance $r$ from zero up to some maximum. If clustering shows up at every distance scale, we see it. If it shows up only at one scale, we can tell which. Chapter 4 develops these tools.

Second, the test is a **probability, not a magnitude**. Saying that Basic-Fit's observed same-chain match rate exceeds the random baseline by twenty-seven percentage points tells us that clustering is non-random. It does not tell us how much competitor entry the clustering actually *prevented*. A moat that is statistically detectable but economically trivial is not the investor case. The magnitude question — given observed clustering, how many competitor openings per square kilometer did dense Basic-Fit catchments deter compared to sparse ones — requires a regression that maps Basic-Fit density in 2022 to competitor-entry count between 2022 and 2026. That is chapter 5. Chapter 6 discusses how a structural entry model in the Bresnahan–Reiss (1991) tradition would sharpen that number further, and why we flag it as a natural next step rather than executing it here.

## What chapters 4–6 will compute for Basic-Fit (forward look)

For each of the six Basic-Fit countries — the Netherlands, Belgium, Luxembourg, France, Spain, and Germany — we will compute $\hat{p}_{\text{obs}}$ and $\hat{p}_{\text{exp}}$ on every quarterly snapshot from 2022 Q1 through 2026 Q1, sixteen quarters in all. That gives one excess-clustering trajectory per country, ninety-six data points total. They will be presented in a small-multiples chart: six panels, one per country, each showing the excess clustering as a line over time, with a horizontal zero-line drawn for reference.

Our strong prior, written down before we look, is as follows. In the Netherlands — Basic-Fit's home and most mature market — we expect excess clustering to be large and roughly flat through the sixteen quarters: the strategy is already baked in, there is no more room to cluster further, and the number simply sits at some high positive value. In Germany, the most recent and still actively expanding market, we expect excess clustering to be lower in 2022 and to **rise monotonically** as Basic-Fit opens successive clubs in catchments it already occupies; if the strategy description is accurate, the trend line should visibly climb. Belgium, Luxembourg, France, and Spain should sit somewhere in between, with timing reflecting when each country entered intensive build-out.

If the data disagree with that prior — if the Netherlands line is low, or Germany's trend is flat, or the countries do not rank-order the way maturity would predict — then the cluster claim is in trouble, and we should say so. If the data match the prior, the simple test has done its first job: confirmed that the fingerprint of a clustering strategy is visible, in roughly the places and roughly the magnitudes one would expect. That confirmation does not close the investment case on its own, but it is a necessary first step, and it clears the ground for the richer tools of chapter 4 and the entry regression of chapter 5.

---

## Working bibliography (chapters 1–3)

Bresnahan, T. F., and Reiss, P. C. (1991). *Entry and competition in concentrated markets.* Journal of Political Economy, 99(5), 977–1009.

Christaller, W. (1933). *Die zentralen Orte in Süddeutschland.* Gustav Fischer, Jena. [English translation: *Central Places in Southern Germany*, Prentice-Hall, 1966.]

IHRSA (2022). *The IHRSA Global Report: The State of the Health Club Industry.* International Health, Racquet & Sportsclub Association, Boston.

Krugman, P. (1991). *Geography and Trade.* MIT Press, Cambridge, MA.

Okabe, A., Boots, B., Sugihara, K., and Chiu, S. N. (2000). *Spatial Tessellations: Concepts and Applications of Voronoi Diagrams* (2nd ed.). Wiley, Chichester.

Ripley, B. D. (1976). *The second-order analysis of stationary point processes.* Journal of Applied Probability, 13(2), 255–266.

Salop, S. C. (1979). *Monopolistic competition with outside goods.* Bell Journal of Economics, 10(1), 141–156.

Shiller, R. J. (2000). *Irrational Exuberance.* Princeton University Press, Princeton, NJ.

[Chapters 4–6 follow. A consolidated References section appears at the end of the document.]

---

# Chapter 4 — The audit

## A chapter ago we set out a clean test. This chapter is what we found.

Chapter 3 closed with a concrete plan. For each of six countries and sixteen quarters, we would compute one excess-clustering number, lay the ninety-six points down in a small-multiples chart, and read off the result. The test required three ingredients: a correct roster of budget-tier gyms per country, correct coordinates for each one, and a correct chain label. All three were supposed to come out of an OpenStreetMap collection pipeline that had been running for weeks by the time we sat down to write.

Before running the headline test we audited the data. That audit is the subject of this chapter.

The decision to audit before reporting was not a flourish. A working data analyst, when the stakes are real, behaves like an auditor rather than like a believer: they assume the pipeline is lying, and they require it to prove otherwise on a primary source for every load-bearing number. The specific protocol we used is documented as an internal skill, **`SKILLS/data-audit-qa.md`**, and follows a standard halt-fix-rerun loop common in regulated-data engineering. In prose: a hundred-percent outlier scan on every numeric field in scope, plus a risk-weighted random sample in which every sampled data point is traced back through the ingestion pipeline to an external primary source — the chain's own annual report, franchise registry, or company website. The audit halts on the first material finding, root-causes it, fixes it if fixable in-scope, and reruns. It does not continue past a finding on the theory that "the rest of the data is probably fine."

What follows is what the auditor saw, in the order the auditor saw it. The reader's experience mirrors ours: the first phase looks reassuring, the second phase breaks it open, and the third phase — the arithmetic — explains why the original headline test cannot honestly be run on this dataset tonight.

## Phase 1 — Outlier scan on Basic-Fit itself

The first sweep compared the count of Basic-Fit clubs the pipeline had assembled from OpenStreetMap against Basic-Fit's own published figures in its most recent annual report.

The results were immediately alarming. The present-day pipeline — a query path that pulls directly from the Overpass mirrors of OpenStreetMap — reported **1,153 Basic-Fit clubs** across the six countries. Basic-Fit's own most recent investor disclosure, for year-end 2025, reports roughly **1,740** (finding **F-001** in the internal audit record). The gap is thirty-four percent. It is not evenly distributed: Luxembourg and Belgium show the worst undercount at ninety-two and fifty-eight percent, the Netherlands and Spain sit in the middle at roughly fifty percent, France at a more moderate twenty-five, and Germany is approximately correct. A country-varying pattern is a tell: it rules out a single global bug, such as the chain-matcher losing a name variant. Something about OpenStreetMap's national tagging conventions is interacting with our query path in ways that drop clubs in some countries and not others.

At this point we had a choice. We could stop and diagnose the Overpass pipeline — a day or two of work to reverse-engineer the Western European tagging-convention variations — or we could pivot to a second, independent source. Fortunately an alternative existed in the same codebase. The pipeline also contains an **OHSOME** path (for OpenStreetMap History Service) that reconstructs historical OSM states from the project's full edit history rather than querying the current snapshot. OHSOME and Overpass are built by different teams, resolve relations differently, and in principle can disagree on any given feature. For Basic-Fit at the snapshot date 2024-03-31, OHSOME reports **1,245 clubs**. Basic-Fit's own published Q1 2024 count is within approximately two percent of that figure. At the 2022-06-30 snapshot, OHSOME reports 882 clubs against a published Q2 2022 count of roughly 890. The OHSOME path was within a few percent of Basic-Fit's own books at every quarter we spot-checked.

This was, at the time, reassuring. We pivoted the whole analysis onto OHSOME. The decision was documented in the audit log at 03:45 UTC on 15 April 2026: the writeup would use OHSOME throughout, historical and "effective present," treating the latest completed OHSOME snapshot as the current data point. Overpass-present-day would be cited only in the limitations section as evidence that collection pathways differ.

Had we stopped at the end of Phase 1, we would have written a confident results chapter using OHSOME data. This is the point in the story where the narrative is meant to turn reassuring. Instead it turned.

## Phase 2 — Deep verification of the peer chains

Basic-Fit's counts matching its own books at the two-percent level is evidence about Basic-Fit. It is not evidence about any other chain. The excess-clustering statistic is a ratio built out of both Basic-Fit's count and the counts of every same-tier peer chain in the same country. A two-percent error on Basic-Fit and a fifty-percent error on the dominant Dutch peer would not cancel; they would compound.

Phase 2 of the audit therefore extended the primary-source cross-check to the top parallel-budget competitors in each market. For each chain we pulled the OHSOME count at 2024-03-31, then looked up the company's own publicly stated number for the same quarter (annual report, franchise registry, corporate website, major trade-press profile). The five findings that follow are reported in the order they were verified; each represents a distinct failure mode.

**L'Orange Bleue (France).** OHSOME at 2024-03-31 reports 192 clubs. L'Orange Bleue's own materials and trade-press reporting from the same period place the network at approximately 400 clubs under brand license — roughly 350,000 members across 400 clubs as of 2023, with 55 new openings in 2023 and a further twenty openings signed for 2024 (finding **F-006**, source: `lorangebleue.fr` historical page, `lejournaldesentreprises.com` 2023 profile, `toute-la-franchise.com` 2023 summary). The gap is fifty-two percent. L'Orange Bleue is not a minor player; it is one of France's three largest budget full-service networks, and it is precisely the kind of chain Basic-Fit's own clubs would cluster near or against.

**KeepCool (France).** OHSOME at 2024-03-31 reports 87 clubs. KeepCool's own concept page announces access to "l'ensemble de nos 300 salles Keepcool," and its store-locator lists consistent with 260–270 operating clubs at the reference quarter (finding **F-007**, source: `keepcool.fr` concept page, `keepcool.fr/salle-de-sport` locator). The gap is sixty-seven percent. The audit also surfaced a canonicalization nit: the chain appears in our database under both `KeepCool` (130 locations) and `Keepcool` (4 locations) — a case-variant duplicate (finding **F-005**) that compounds the coverage undercount rather than offsetting it.

**EasyFitness (Germany).** OHSOME at 2024-03-31 reports 24 clubs. EasyFitness Franchise GmbH publicly reports 470,000 members across 205 clubs at end-of-2024, having grown from 105 studios in 2018 to 205 in 2024; a Q1 2024 figure in the 170–185 range follows from the growth trajectory (finding **F-008**, source: `fitqs.com` "Top 10 Fitness Club Brands in Germany – 2024 Market Analysis", `edelhelfer.com` top-ten operators report, `easyfitness.club` studios page, German-language Wikipedia). The gap is eighty-seven percent. This is outside any coverage tolerance one could reasonably defend. The likely proximate cause is that the chain's stylized brand name `EASYFITNESS.club` (with dot, uppercase, domain-style) does not match our canonical string `EasyFitness` under the matcher's current normalization rules — but this diagnosis is not load-bearing for the chapter; the observed coverage is what matters.

**SportCity (Netherlands).** OHSOME at 2024-03-31 reports 42 clubs. SportCity publicly operates in the 115–120 range across the Netherlands, with Bencis consolidating the platform with Fit For Free in late 2024; the pre-consolidation Q1 2024 count is roughly 100–110 (finding **F-009**, source: `sportcity.nl`, `bencis.com` case page, `avedoncapital.com` exit announcement, Tracxn profile). The gap is approximately sixty percent on the historical series. Note that Overpass-present-day reports 125 SportCity clubs, which is approximately correct — so the defect is specifically in the OHSOME historical path, not in OSM's tagging of the chain. The Netherlands is Basic-Fit's home market, and SportCity is Basic-Fit's single largest same-tier neighbor in that market. This finding is the most consequential for any country-level read of the headline test, because it means the Dutch time series is scrambled precisely where the hypothesis should bite hardest.

**Fitness Park (France).** OHSOME at 2024-03-31 reports 378 clubs. Fitness Park publicly reported approximately 270 clubs in December 2023 and first reached the 300-club mark in May 2024; the Q1 2024 truth sits around 280–290 (finding **F-010**, source: `franchise-magazine.com` May 2024 "plus de 300 clubs", `observatoiredelafranchise.fr`, `group.fitnesspark.com` master-franchise page). The gap is plus thirty percent — an over-count, not an under-count. This reverses the sign of every other Phase 2 finding and points to a distinct defect: the fuzzy-matcher is likely claiming OSM features whose name string contains "fitness park" as a substring but which are not operated by the Fitness Park franchise. F-010 is separate from the undercount cluster and has to be triaged separately.

Five chains checked, five findings filed. The remaining chains in the top-ten parallel-budget list — clever fit (OHSOME 434 vs Statista's 439 in 2023: within tolerance), McFit (293 vs ~250 published: seventeen percent high, just outside the fifteen-percent tolerance band but close), Anytime Fitness (no chain-disclosed Q1 2024 Europe-only public figure; verification stopped at layer two), and FitX (101 vs ~95–100 published: within three percent) — came through approximately clean.

### Table 4.1 — Summary of audit findings F-001 through F-010

| ID | Severity | Subject | Finding |
|---|---|---|---|
| F-001 | CRITICAL | Basic-Fit, Overpass present-day | 34% under-count against published Q4 2025 (pivoted to OHSOME) |
| F-002 | HIGH | Altafit (chain classification) | Mis-classified as `public` municipal; actually private Spanish chain |
| F-003 | MEDIUM | "Piscina Municipal" et al. | Generic OSM descriptive terms mis-read as chains |
| F-004 | LOW | Basic-Fit / McFit matcher bleed | Two Basic-Fit OSM rows routed to McFit by fuzzy match |
| F-005 | LOW | KeepCool / Keepcool case split | Case-variant duplicate chain rows; 4 clubs leak |
| F-006 | HIGH | L'Orange Bleue, OHSOME Q1 2024 | 52% under-count against 400-club published truth |
| F-007 | HIGH | KeepCool, OHSOME Q1 2024 | 67% under-count against ~270-club published truth |
| F-008 | HIGH | EasyFitness, OHSOME Q1 2024 | 87% under-count against ~180-club published truth |
| F-009 | MEDIUM | SportCity, OHSOME Q1 2024 | 60% under-count on historical series; present-day approximately correct |
| F-010 | MEDIUM | Fitness Park, OHSOME Q1 2024 | 30% over-count; opposite-direction matcher defect |

F-002 was fixed in place during the audit; F-003, F-004, and F-005 are acknowledged and queued for a cleanup pass but do not materially contaminate the tier-filter used downstream. F-001, F-006, F-007, F-008, F-009, and F-010 are the findings that shape the rest of this document.

## Why this matters for the headline test

The excess-clustering statistic, as laid out in chapter 3, is the gap between an observed same-chain nearest-neighbor probability and an expected probability from random assortment:
$$\Delta \;=\; \hat{p}_{\text{obs}} - \hat{p}_{\text{exp}} \;=\; \frac{1}{|B|} \sum_{g \in B} \mathbf{1}\{\text{NN}(g) \in B\} \;-\; \frac{|B|-1}{|S|-1}.$$

Both terms depend on $|S|$, the full count of same-tier gyms in a country. If the peer chains that make up the non-Basic-Fit portion of $S$ are systematically under-represented in our data — because OHSOME's coverage of L'Orange Bleue is down fifty-two percent, KeepCool sixty-seven percent, EasyFitness eighty-seven percent, SportCity sixty percent on the historical series — then $|S|$ is measured too small, and both terms of $\Delta$ drift in the same direction.

Consider a toy Dutch market. Suppose the real same-tier roster is forty Basic-Fits and forty SportCitys — the chain's fifty-fifty with its dominant peer. The real random-assortment baseline is $\hat{p}_{\text{exp}} = 39/79 \approx 0.494$. Suppose further that clustering is real but modest: Basic-Fits are placed such that each BF's nearest same-tier neighbor is another BF sixty-five percent of the time. Then the real excess is $0.65 - 0.49 \approx 16$ percentage points.

Now feed the same geography through a pipeline that captures all forty Basic-Fits but only sixteen of the forty SportCitys (a sixty-percent undercount, matching F-009). The observed roster is forty BF and sixteen SC; the random-assortment baseline computed from the observed roster is $39/55 \approx 0.709$. Worse, the observed nearest-neighbor probability is also inflated: every BF whose *real* nearest same-tier neighbor was a missing SportCity now finds another BF as its nearest available same-tier neighbor, simply because the SportCity isn't in the data. Under plausible geometry (Basic-Fits and SportCitys roughly co-located in Dutch urban areas), observed nearest-BF rates of eighty to ninety percent are easy to produce. Observed excess is then on the order of $0.85 - 0.71 \approx 14$ percentage points — superficially similar to the real sixteen-point figure, but for entirely the wrong reason: it is a compositional artifact of the coverage gap, not evidence of a cluster strategy.

The direction of the bias matters. If the artifact inflated $\hat{p}_{\text{obs}}$ and $\hat{p}_{\text{exp}}$ by symmetric amounts, the $\Delta$ would be approximately unchanged and the test would still be interpretable. But the two terms inflate by different amounts, driven by the geometry: $\hat{p}_{\text{exp}}$ is a simple share, so it moves predictably with the undercount, while $\hat{p}_{\text{obs}}$ moves by however often the missing peers *would have been* a Basic-Fit's nearest neighbor — a quantity that depends on the spatial joint distribution of Basic-Fit and the missing peers. When peer chains are under-counted precisely where they co-locate with Basic-Fit, the second term inflates more than the first, and $\Delta$ can either widen or shrink in an uncontrolled way.

> **Sidebar: formal expression of the compositional bias.** Let $S$ be the true same-tier roster and $\tilde{S} \subseteq S$ the roster observed through the pipeline. Partition the missing peers into those that are spatially close to Basic-Fit and those that are not: $S \setminus \tilde{S} = M_{\text{near}} \cup M_{\text{far}}$. Let $\pi_{\text{near}}$ be the probability, under the true geometry, that a Basic-Fit's nearest same-tier neighbor falls in $M_{\text{near}}$. Then the observed statistic decomposes as
> $$\hat{\Delta}_{\text{obs}} \;=\; \Delta_{\text{true}} \;+\; \pi_{\text{near}} \cdot \left(1 - \frac{|B|}{|S|}\right) \;-\; \left(\frac{|B|}{|\tilde{S}|} - \frac{|B|}{|S|}\right).$$
> The first bias term is positive and grows with the missing-near fraction (missing peers turn into artificially-close BF neighbors). The second bias term is negative and grows with the total miss rate (the expected baseline inflates toward one as $|\tilde{S}|$ shrinks relative to $|S|$). In general the two do not cancel; their sum is uncontrolled in sign and magnitude without knowing the spatial coupling of $M_{\text{near}}$ to $B$.

This is the heart of the audit verdict. The estimator is not noisy around the true $\Delta$; it is shifted by an amount that depends on exactly the unknown geometry the test is trying to detect. Running it and reporting a number would be worse than silence — it would be the kind of number a board member could mistake for evidence.

## The audit verdict

The rigorous version of the test — the one the chapter-3 plan called for — requires three things we do not currently have: (i) a complete roster of budget-tier chains in each country, with OHSOME coverage cross-validated to within fifteen percent of each chain's publicly disclosed quarterly count; (ii) a chain-matcher robust to brand-name variants, diacritics, case, stylized domain-style names, and franchise-suffix strings (see F-005, F-007, F-008); and (iii) a re-collection of all sixteen quarterly snapshots once the matcher is fixed, so that the historical time series is not built on a biased sample. None of these three items are fixable in the remaining hours before this document ships.

The audit formally ended at iteration two with an architectural decision rather than a re-run. We could produce a six-country sixteen-quarter grid of excess-clustering numbers tonight. The numbers would look clean, because the pipeline produces clean-looking numbers. They would not be numbers about the geography of Basic-Fit's clustering strategy. They would be numbers about the interaction of OSM tagging conventions, the OHSOME historical query path, and our chain-matcher's treatment of French and Dutch budget-chain brand names. To report them as evidence for or against the cluster hypothesis would be fabrication.

Chapter 5 does the next best thing. It restricts the analysis to the subset of chains where coverage is known-good, runs the simple test on that subset, and reports the result as directional evidence rather than as a confidence-weighted finding. Chapter 6 sets out what it would take to produce the rigorous version.

---

# Chapter 5 — What we can say anyway: directional evidence from the clean subset

## The intellectually honest version

Having said at length what the audit does not allow us to report, it is worth being equally precise about what it does. A dataset with known coverage gaps on some chains still contains the chains where coverage was validated. A test whose standard form depends on the full tier roster can still be run on a subset, at the cost of answering a narrower question. The trick is to pose the narrower question honestly and to label the answer as directional rather than as the headline finding.

The narrower question is this. Restrict attention to the chains whose count in our data cross-validates against their own public disclosures within fifteen percent. Within that restricted roster, does Basic-Fit's location pattern look clustered relative to the subset's null of random assortment? This is a weaker claim than the chapter-3 plan. It does not speak to what Basic-Fit looks like against the full budget tier; it only speaks to what Basic-Fit looks like against the well-measured part of the tier. But it speaks to that cleanly, and the result is interpretable without the compositional bias of chapter 4.

## Defining the clean subset

Three chains came through the Phase 2 audit at coverage within our fifteen-percent tolerance.

- **Basic-Fit** (chain id 13). OHSOME 2024-03-31 count of 1,245 against a published Q1 2024 figure within two percent. The foundational chain of the analysis.
- **clever fit** (chain id 11). OHSOME 2024-03-31 count of 434 against Statista's 2023 count of 439. A German-footed franchise network at the budget full-service tier.
- **FitX** (chain id 127). OHSOME 2024-03-31 count of 101 against a published Q1 2024 figure of approximately 95–100. Germany-only, budget, full-service.

Two chains sit borderline — inside the twenty-percent range but outside fifteen — and merit inclusion in a sensitivity check rather than in the primary analysis:

- **McFit** (chain id 26). OHSOME 293 against approximately 250 published: about seventeen percent high. The direction of the error (over-count) is the opposite of the Phase 2 undercount cluster and is consistent with the chain-matcher claiming related RSG Group brand variants.
- **Anytime Fitness** (chain id 20). A Q1 2024 Europe-only chain-disclosed figure was not publicly accessible; the audit logged a layer-two stop. DB count of 152 is in the range one would expect for the region, but cross-validation is absent.

Every other chain in the top-ten parallel-budget list failed audit (F-006 through F-010) and is excluded. The clean-subset analysis therefore operates on Basic-Fit plus two German-dominant peers. That geometry matters: in five of the six Basic-Fit countries, the clean subset contains only Basic-Fit itself.

## The computation

For each country we pulled the coordinates of every active location belonging to the clean-subset chains from the `locations` table, and for each Basic-Fit point we identified the nearest same-tier neighbor under great-circle distance (haversine). We computed $\hat{p}_{\text{obs}}$ as the fraction of Basic-Fit points whose nearest same-tier neighbor is another Basic-Fit, and $\hat{p}_{\text{exp}} = (|B| - 1) / (|S| - 1)$ as the random-assortment baseline, where $S$ is the clean-subset same-tier roster for that country.

One caveat runs through the whole table and must be surfaced, not buried. The coordinate layer available to us — the per-point latitudes and longitudes — comes from the Overpass-present-day snapshot, which finding F-001 identifies as a thirty-four-percent undercount of Basic-Fit against the chain's own Q4 2025 disclosure. The OHSOME aggregate counts do not come with per-point coordinates; OHSOME returns counts by bounding box, not a point list we can feed into a nearest-neighbor algorithm. We are therefore using the coverage-validated OHSOME aggregates to decide *which chains* to include in the clean subset, and then using the Overpass-present-day coordinates to run the geometry. A country whose Overpass count is known to be low, such as NL (118 BF points against a 2024-03-31 OHSOME count of 240), has roughly half of its true Basic-Fit footprint visible to this test. If the missing half is geographically representative of the visible half — a strong assumption, but one consistent with the chain's near-uniform national distribution — the within-country ratio is preserved and the test is interpretable. If the missing half is systematic (e.g., concentrated in newer build-outs in specific cities), the ratio is biased. We report the result with this caveat attached.

### Table 5.1 — Clean-subset excess clustering by country, Basic-Fit vs clean peers

Coordinates: `locations` table, Overpass present-day snapshot (2026-04-12). Chains: Basic-Fit, clever fit, FitX. Nearest-neighbor metric: haversine.

| Country | $N_{\text{tier}}$ (clean subset) | $N_{\text{BF}}$ | $\hat{p}_{\text{exp}}$ | $\hat{p}_{\text{obs}}$ | $\Delta$ (pp) |
|---|---|---|---|---|---|
| Germany (DE)     | 565 | 132 | 0.232 | 0.788 | **+55.6** |
| France (FR)      | 708 | 704 | 0.994 | 1.000 | +0.6 |
| Netherlands (NL) | 118 | 118 | 1.000 | 1.000 | 0.0 (degenerate; see note) |
| Belgium (BE)     | 63  | 63  | 1.000 | 1.000 | 0.0 (degenerate) |
| Spain (ES)       | 134 | 134 | 1.000 | 1.000 | 0.0 (degenerate) |
| Luxembourg (LU)  | 2   | 2   | 1.000 | 1.000 | 0.0 (degenerate; $n$ too small) |

The table has one row that contains information, four rows that contain no information but honestly report their degeneracy, and one row where the information is present but weaker than it first appears.

**Germany is the only country with a meaningful clean-subset test.** The German budget tier, restricted to chains with validated OHSOME coverage, contains Basic-Fit's 132 clubs and clever fit's 340 plus FitX's 93. Basic-Fit's share of that clean-subset tier is twenty-three percent. If Basic-Fit's German clubs were placed randomly with respect to its clean peers, the probability that a given Basic-Fit's nearest same-tier neighbor is another Basic-Fit would be roughly twenty-three percent. The observed probability is seventy-nine percent. The excess is **fifty-six percentage points** — a large, unambiguous signal that within the German clean subset, Basic-Fit clubs are placed next to other Basic-Fit clubs far more often than random assortment would predict.

**France's clean-subset row is informative but weak.** Basic-Fit operates 704 clubs in France against four clever fit clubs and zero FitX, for a clean-subset share of 99.4 percent. With Basic-Fit so dominant in the clean subset, the random-assortment baseline is already essentially one, and the observed rate cannot rise materially above it. The +0.6-point excess in the French row is not evidence of anything; it is the arithmetic floor. A defensible French reading requires adding back the French peer chains, which is exactly the remediation chapter 6 specifies.

**Netherlands, Belgium, Spain, Luxembourg are degenerate.** In each of these four countries, the clean subset contains only Basic-Fit. There are no clever fit or FitX locations against which to measure nearest-neighbor composition. $\hat{p}_{\text{exp}}$ and $\hat{p}_{\text{obs}}$ are both exactly one by construction; the test returns no information. The Luxembourg row is additionally limited by sample size ($n = 2$). These rows are reported because omitting them would hide the scope of the problem.

## A sensitivity check with the borderline chains

Adding McFit (17 percent over-count, within the twenty-percent band) and Anytime Fitness (verification stopped at layer two, included here with explicit caveat) to the subset changes the picture in the ways one would expect: more countries become non-degenerate, but the excess figures should be read with an additional grain of salt corresponding to the wider tolerance.

### Table 5.2 — Extended-subset excess clustering, sensitivity check

Chains: Basic-Fit, clever fit, FitX, plus borderline McFit and Anytime Fitness. Same coordinate source and metric as Table 5.1.

| Country | $N_{\text{tier}}$ | $N_{\text{BF}}$ | $\hat{p}_{\text{exp}}$ | $\hat{p}_{\text{obs}}$ | $\Delta$ (pp) |
|---|---|---|---|---|---|
| Germany (DE)     | 760 | 132 | 0.173 | 0.697 | **+52.4** |
| France (FR)      | 744 | 704 | 0.946 | 0.997 | +5.1 |
| Netherlands (NL) | 153 | 118 | 0.770 | 0.754 | **−1.5** |
| Belgium (BE)     | 73  | 63  | 0.861 | 0.857 | −0.4 |
| Spain (ES)       | 171 | 134 | 0.782 | 0.828 | +4.6 |
| Luxembourg (LU)  | 2   | 2   | 1.000 | 1.000 | 0.0 |

Germany remains strongly positive: fifty-two percentage points of excess clustering against a now-broader subset. France's non-degenerate reading is a modest +5 points, but the French subset is still missing L'Orange Bleue, KeepCool, and Fitness Park, so the sign of the true figure is not knowable from this row. The Netherlands reads approximately zero; but note that the Dutch subset is missing SportCity, which is Basic-Fit's dominant NL peer — so the zero is a null by construction, not a finding. Belgium and Spain sit near zero in a subset that excludes their respective significant budget peers. Luxembourg remains degenerate at $n = 2$.

**Figure 5.1.** Clean-subset and extended-subset excess clustering by country, shown as a horizontal bar chart with Germany highlighted. Each country's bar is labeled with the number of clean-subset peer gyms; Netherlands, Belgium, Spain, and Luxembourg are shaded gray to indicate that the clean-subset test is degenerate (no peer chains survived the audit in that country). (Image: `fig-5-1-clean-subset-excess.png`, to be rendered separately.)

## Directional reading

Taken together, these tables say one thing firmly and several things only provisionally.

The firm statement: **within the well-measured German budget-tier subset, Basic-Fit's location pattern exhibits large and unambiguous same-chain clustering at the nearest-neighbor scale.** A German Basic-Fit's nearest clean-subset-peer gym is another Basic-Fit nearly eighty percent of the time, against a random-assortment baseline of twenty-three percent. The excess is five times the random-assortment baseline's standard-deviation rule-of-thumb and is robust to swapping in borderline chains. This is directionally consistent with the cluster hypothesis.

The provisional statements: the other five countries either contain no clean peers (NL, BE, ES, LU), so the clean-subset test returns no information; or contain too few clean peers relative to the dominant-peer population (FR), so the random-assortment baseline is pinned near one and the test has no range. On these countries the clean-subset analysis is silent, and silence is the correct output until the audit gaps are closed.

The cross-country reading the chapter-3 plan promised — a maturity ranking that would show Germany rising and the Netherlands flat at a high plateau — cannot be read from these numbers. Germany alone is measured. Whether the Netherlands sits above or below Germany on the true excess-clustering scale is genuinely unknown from our data tonight. A reader who wishes to read Germany's fifty-six-percentage-point figure as "evidence the clustering hypothesis is correct in at least one market" is on defensible ground. A reader who wishes to conclude anything about the thesis at the six-country level from this table is not.

## What this test does not say

Three specific limitations are worth making explicit, to forestall misreadings.

First, the clean-subset test answers a restricted question. A country whose full-tier pattern is not clustered can still show within-clean-subset clustering if the missing peers are geographically uniform; a country whose full-tier pattern is strongly clustered can show a muted clean-subset signal if the missing peers are concentrated in the same clusters. In other words, the clean-subset statistic is a lower bound on the true signal in some configurations and an upper bound in others, and we do not have the data to determine which case applies in each country.

Second, even Germany's signal could be sharpened. The nearest-neighbor test only uses each Basic-Fit's single closest peer, which is a thin slice of the spatial information available. A Basic-Fit with three Basic-Fit neighbors inside five hundred meters and a clever fit at six hundred meters contributes the same "same-chain" count as a Basic-Fit whose only nearby peer is fifty kilometers away. Ripley's cross-$K$ function and the mark-connection function $p_{BB}(r)$ would integrate across distance and let us see whether Germany's signal sits at the five-hundred-meter scale, the two-kilometer scale, or both. Chapter 6 develops this.

Third, the coordinates used here are Overpass-present-day (2026-04-12). The OHSOME-2024-03-31 aggregate counts we used to define the clean subset diverge from the 2026 coordinate set — Basic-Fit NL appears as 118 on the coordinate layer versus 240 in the OHSOME 2024 Q1 aggregate — so the table is effectively a snapshot of the geography visible to our present-day pipeline, restricted to chains whose historical OHSOME aggregates we trust. Re-running the test on a coordinate list drawn from OHSOME (rather than Overpass) is one of the remediation items in chapter 6.

> **Sidebar: the subset-restricted mark-connection function.** For a point pattern with marks $\{m_g\}_{g \in S}$, the mark-connection function at the nearest-neighbor scale is $p_{mm'}(r=r_{\text{NN}}) = \Pr[\text{mark of NN}(g) = m' \mid \text{mark of } g = m]$. Restricting the pattern to a subset $S' \subseteq S$ produces a well-defined but subset-specific object: $p^{(S')}_{BB}$ is the same-Basic-Fit nearest-neighbor probability computed on $S'$, and its null under random assortment is $|B|/|S'|$. What the clean-subset test computes is $p^{(S')}_{BB} - |B|/|S'|$, where $S'$ is the audit-validated chain set. This is a legitimate estimator of clustering *within the restricted pattern*. It is not an estimator of the full-pattern mark-connection, and it should not be interpreted as one. The restriction changes the null; a subset in which Basic-Fit dominates (as in FR, NL, BE, ES, LU here) produces a null near one, against which no observed rate can be meaningfully elevated.

The chapter's honest conclusion is narrower than the one chapter 3 anticipated, and larger in Germany than it is elsewhere: within the well-measured subset, German Basic-Fits cluster. The rest of the map remains dark until the remediation in chapter 6 is complete.

---

# Chapter 6 — Remediation plan and next steps

## The three fixes the audit demands

The chapter-4 findings point to three discrete engineering tasks, each of which recovers a specific piece of the analysis the chapter-3 plan anticipated. They are independent but ordered: the chain-matcher fix unlocks the peer chains, the per-chain ground-truth anchor validates that the fix worked, and the upgrade to cross-$K$ sharpens the spatial read once the data support it.

### Fix one: the chain matcher

The audit surfaced three specific matcher defects, each pointing at the same underlying gap. F-004 documented two OSM features whose `name` string was `Basic-Fit` or `BasicFit` being routed into the McFit chain record by the fuzzy-name matcher. F-005 documented a duplicate-chain split, with `KeepCool` and `Keepcool` living in separate rows and losing four clubs to the case variant. F-007's verification trace noted that the "L'Orange Bleue Mon Coach Fitness" franchise-suffix variant drops entirely from the L'Orange Bleue chain in our data, and F-008 documented that EasyFitness's stylized brand string `EASYFITNESS.club` fails to match our canonical `EasyFitness`. These are all instances of a single problem: the matcher normalizes insufficiently before comparing.

The fix has three parts. First, a **canonicalization layer** applied before any matching: fold diacritics (é→e, ü→u), lowercase, strip leading/trailing whitespace, collapse separator runs (hyphens, dots, spaces, ampersands) to a single space, and strip a curated list of franchise suffixes (`Mon Coach Fitness`, `Franchise GmbH`, `SA`, `SAS`, `SL`, `.club`, `.com`, `Gym Club`, `Fitness Club`). Second, **dedup the existing chains table** on the canonicalized key, merging duplicates like `KeepCool`/`Keepcool` into single rows and repointing child `locations` rows to the merged chain. Third, **prefer structured OSM brand tags over name matching**: OSM features carry `brand:wikidata=Q-ID` tags on a growing fraction of major-brand locations, and where that tag is present it is unambiguous. The matcher should use brand-wikidata as the primary join key, fall back to the canonicalized name when it is absent, and never fall back to pure fuzzy matching for chains with a known wikidata ID.

A builder subagent with clear specifications should complete this in approximately four hours. The downstream cost is re-collecting all sixteen historical OHSOME snapshots with the improved matcher — approximately four further hours of pipeline runtime and spot-check validation. Total: ~8 hours.

### Fix two: per-chain ground-truth anchors

Even with a better matcher, OHSOME will never have one-hundred-percent coverage of any chain. The second fix is to establish, for each of the top twenty parallel-budget chains, a per-chain public-truth anchor: the company's own quarterly location count as disclosed in annual reports, franchise-association filings (for franchise networks), or company websites where these are public. The audit already assembled these anchors informally while filing F-006 through F-010; the remediation is to systematize the work across the full peer roster rather than the opportunistic sample Phase 2 covered.

The output is a per-chain-per-quarter coverage-ratio table. For each chain and each quarter, divide the OHSOME count by the public count. Chains whose coverage ratio is stably above, say, 0.85 across the recent quarters are trusted and enter the analysis. Chains whose ratio is below 0.70 are flagged as unusable until the matcher fix is shown to move them into the trusted band. Chains in the 0.70–0.85 band enter as borderline, with a sensitivity check parallel to Table 5.2 in chapter 5.

A builder subagent with a web-search tool, working against the top-twenty chain list, should complete the anchor assembly in approximately one hour once web-search capacity is available. The output folds cleanly into the re-collection step of fix one.

### Fix three: upgrade the statistic from nearest-neighbor to Ripley's cross-$K$

The excess-clustering statistic of chapter 3 is the cheapest usable estimator of a spatial clustering signal. It is also the thinnest slice of the data available. Chapter 5's limitations section noted the shortcoming: nearest-neighbor counts only the closest peer, discarding every other nearby same-tier point. The appropriate upgrade is **Ripley's cross-$K$ function** (Ripley, 1976; Baddeley & Turner, 1990s) and its companion the **mark-connection function** $p_{mm'}(r)$, which integrate information across the full range of distance scales rather than collapsing it into a single nearest-neighbor binary.

Ripley's cross-$K$ for two marks $B$ (Basic-Fit) and $C$ (competitor peers) is, informally, the expected count of peer-$C$ points within distance $r$ of a randomly chosen peer-$B$ point, normalized by the peer-$C$ intensity. Under complete spatial randomness, cross-$K$ grows as $\pi r^2$; systematic departures below this curve at small $r$ indicate spatial avoidance (Basic-Fits and competitors repel), departures above indicate attraction (co-location), and the shape of the departure across $r$ reveals the scale at which the interaction operates. For the clustering hypothesis as Basic-Fit describes it, the relevant question is whether the Basic-Fit–to–Basic-Fit univariate $K$ lies above the random baseline at catchment-relevant scales (roughly 500m to 3km) — the map-level analogue of asking whether BF gyms are systematically closer to other BF gyms than chance would predict.

In practice the computation is standard. R's `spatstat` package (Baddeley, Rubak & Turner, 2015) implements `Kcross` and `pcfcross` with edge corrections; Python's `pointpats` library implements the same family. Both accept a marked point pattern and a study window and return the $K$-curve with pointwise simulation envelopes under the random-labeling null — which is the right null here, because it holds fixed the overall point locations and randomly re-assigns chain labels, directly testing whether the *labeling* is clustered.

Moving from excess-clustering to cross-$K$ on the validated peer roster is approximately a two-hour analyst task once fixes one and two are in place — a literature standard implementation, not original methodology. The classical references for the practitioner reader are Baddeley, Rubak & Turner (2015) for `spatstat`; Ripley (1976) for the original statistic; Ellison & Glaeser (1997) and Duranton & Overman (2005) for the adaptation of these tools to industrial-location data. The last of these is particularly apt: Duranton and Overman estimated industry-level clustering across UK establishments using a density-based relative of Ripley's $K$, and the interpretive vocabulary (localization, dispersion, concentration at a scale) transfers directly.

## A fourth fix, for readers who want to quantify deterrence

Everything above answers a descriptive question: does Basic-Fit's placement look clustered? A richer question is economic: how much competitor entry does the clustering actually deter? A statistic that reports "Basic-Fit's cross-$K$ exceeds the random baseline by a factor of 1.7 at $r = 1$ km" is a spatial-pattern finding; it is not, by itself, a statement about competitor behavior. For the investor reader, the statement that matters is something like "every additional Basic-Fit in a catchment reduces the probability of a competitor opening there over the next four years by X percentage points." That is a structural entry-model question, and the standard approach to it is the **Bresnahan–Reiss entry model** (Bresnahan & Reiss, 1991) as extended for endogenous location choice in the retail-chain literature (Jia, 2008, on Wal-Mart and Kmart).

The Bresnahan–Reiss approach, in plain English, writes down each potential entrant's profit in each potential market as a function of how many competitors are already there, treats the observed entry pattern as the Nash equilibrium of that entry game, and inverts it to recover the parameters — in particular the deterrence parameter, the amount by which an incumbent's presence reduces an entrant's profitability. The Jia extension handles the large-scale spatial version, where every location-pair decision interacts with every other through a giant simultaneous entry game; Jia's contribution is an algorithm that makes this computationally tractable. The papers are thirty years apart; the core idea is the same.

For the Basic-Fit analysis, the structural upgrade requires per-market entry and exit *event* data: the date a gym opened, the date it closed, not just a snapshot of whether it existed at each quarter-end. OSM's "first appearance" date is not the same thing as a real opening — a gym built in 2018 may first appear in OSM in 2022 when a contributor notices it — and the current pipeline does not cleanly separate these. Assembling real opening-dates (from press releases, company filings, local-press coverage) for a representative sample of competitor entries would be approximately a day of research-and-coding effort per country, and the econometric estimation would be on the order of another day. It is the heaviest of the remediations, and we flag it as appropriate only if the investor question materially depends on quantifying the *magnitude* of deterrence rather than confirming its direction.

## A suggested sequence

The four fixes compose cleanly into a critical path.

1. **Chain-matcher fix plus full OHSOME re-collection (fix one).** Approximately eight hours. Produces a coverage-validated peer roster across all sixteen quarters and six countries.
2. **Per-chain ground-truth anchors (fix two).** Approximately one hour, running in parallel with step 1. Provides the public-truth reference against which the post-fix OHSOME counts are validated; chains whose coverage ratio stabilizes above 0.85 enter the trusted set, and the directional readings in chapter 5 are replaced by the full six-country sixteen-quarter grid of excess-clustering numbers promised in chapter 3.
3. **Ripley's cross-$K$ formalization (fix three).** Approximately two hours, conditional on steps 1 and 2 producing a defensible peer roster. Produces the $K$-curves that resolve the "at what scale" question the nearest-neighbor test cannot address.
4. **Bresnahan–Reiss / Jia structural entry model (fix four).** Approximately two days, conditional on an investor decision — an acquisition, a major market entry, an equity call — for which the magnitude of deterrence, not just its direction, is load-bearing.

Steps one through three put a coverage-validated, scale-aware, publication-grade reading of the cluster hypothesis in hand within about eleven hours of engineering and analyst time. Step four converts that reading into a structural economic statement. Our recommendation is to execute steps one through three on a near-term timeline, and to hold step four until it is clear the decision at the other end of the analysis warrants the investment.

## A brief reflection

It may feel like a strange result to report, after five chapters of machinery, that the most honest version of the analysis is "the rigorous test cannot be run on tonight's data, and here is a directional reading from a subset." The instinct that this is a failure is understandable. It is also wrong.

The thesis this document set out to test is load-bearing for a live investment case. A clean-looking chart built on 40-percent-accurate data would *feel* like an answer; it would not *be* an answer, and a reader who relied on it would be worse off than a reader who had read nothing at all. The audit that revealed the data's limitations is therefore not a detour from the work; it *is* the work. The standard this document holds itself to is the one a skeptical auditor holds a filing to: every load-bearing number traceable to a primary source, every calculation re-derivable from first principles, every gap disclosed rather than papered over.

The directional reading in chapter 5 — that within Germany's well-measured budget-tier subset, Basic-Fit exhibits large same-chain clustering — is genuine evidence, and the reader may weight it accordingly. It is not enough to close the investment case; it is enough to motivate the eleven hours of engineering laid out here. The investor reader should treat the chapter-5 findings as provisional until the remediation in this chapter is complete. We expect to know materially more after that work lands.

---

# References

Baddeley, A., and Turner, R. (2005). *spatstat: An R package for analyzing spatial point patterns.* Journal of Statistical Software, 12(6), 1–42.

Baddeley, A., Rubak, E., and Turner, R. (2015). *Spatial Point Patterns: Methodology and Applications with R.* Chapman & Hall / CRC, Boca Raton, FL.

Bresnahan, T. F., and Reiss, P. C. (1991). *Entry and competition in concentrated markets.* Journal of Political Economy, 99(5), 977–1009.

Christaller, W. (1933). *Die zentralen Orte in Süddeutschland.* Gustav Fischer, Jena. [English translation: *Central Places in Southern Germany*, Prentice-Hall, 1966.]

Duranton, G., and Overman, H. G. (2005). *Testing for localization using micro-geographic data.* Review of Economic Studies, 72(4), 1077–1106.

Ellison, G., and Glaeser, E. L. (1997). *Geographic concentration in U.S. manufacturing industries: a dartboard approach.* Journal of Political Economy, 105(5), 889–927.

IHRSA (2022). *The IHRSA Global Report: The State of the Health Club Industry.* International Health, Racquet & Sportsclub Association, Boston.

Jia, P. (2008). *What happens when Wal-Mart comes to town: an empirical analysis of the discount retailing industry.* Econometrica, 76(6), 1263–1316.

Krugman, P. (1991). *Geography and Trade.* MIT Press, Cambridge, MA.

Okabe, A., Boots, B., Sugihara, K., and Chiu, S. N. (2000). *Spatial Tessellations: Concepts and Applications of Voronoi Diagrams* (2nd ed.). Wiley, Chichester.

Rey, S. J., Arribas-Bel, D., and Wolf, L. J. (2020). *Geographic Data Science with PySAL and the pointpats library.* (Documentation and source, https://pysal.org/pointpats/.)

Ripley, B. D. (1976). *The second-order analysis of stationary point processes.* Journal of Applied Probability, 13(2), 255–266.

Salop, S. C. (1979). *Monopolistic competition with outside goods.* Bell Journal of Economics, 10(1), 141–156.

Shiller, R. J. (2000). *Irrational Exuberance.* Princeton University Press, Princeton, NJ.

Primary sources cited in the chapter-4 audit:

- Basic-Fit N.V., Annual Report 2025 (for Q4 2025 club-count figures cited in F-001).
- Basic-Fit N.V., quarterly investor presentations 2022 Q2 through 2024 Q1 (for OHSOME cross-validation in the audit pivot decision).
- L'Orange Bleue: `lorangebleue.fr` historical page; `lejournaldesentreprises.com` 2023 profile; `toute-la-franchise.com` 2023 summary (F-006).
- KeepCool: `keepcool.fr` concept and locator pages (F-007).
- EasyFitness Franchise GmbH: `fitqs.com` 2024 market analysis; `edelhelfer.com` top-ten operators report; `easyfitness.club` studios page; German-language Wikipedia entry (F-008).
- SportCity: `sportcity.nl`; `bencis.com` case page; `avedoncapital.com` exit announcement; Tracxn profile (F-009).
- Fitness Park: `franchise-magazine.com` May 2024 coverage; `observatoiredelafranchise.fr`; `group.fitnesspark.com` master-franchise page (F-010).
- Statista (2023), *clever fit — Anzahl der Studios in Deutschland* (for clever fit cross-validation in Phase 2 clean pass).
