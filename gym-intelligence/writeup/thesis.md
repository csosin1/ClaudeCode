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

[Additional references for chapters 4–6 — `spatstat` / `pointpats` documentation, Basic-Fit investor-relations filings, Eurostat GEOSTAT 1 km² population grid documentation — will be merged into this bibliography in the final pass.]
