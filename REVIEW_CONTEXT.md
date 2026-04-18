# REVIEW_CONTEXT for abs-dashboard

Maintained by the abs-dashboard chat. Read by visual-reviewer agents at QA time.
Update when product direction, audience, or standards shift.

## Purpose

A static, mobile-first dashboard that helps a non-technical equity investor
understand Carvana's auto-ABS business insofar as it impacts Carvana the
company. Carvana is the **subject**; CarMax is the **benchmark**. Four top-nav
tabs: Recent Trends (monthly monitoring lens), Residual Economics (per-deal
forecast vs actual, with cap structure), Methodology & Findings (model spec,
transition heatmaps, hazards, worked examples), Deals (index → per-deal
drill-down).

## Audience

External, investor-facing. One reader: a non-technical equity investor who
views the site on an iPhone. Desktop (1280px) rendering must also be clean
because he occasionally opens the preview on a laptop, but mobile (390px) is
the default lens. No internal/debug copy; no jargon without a plain-English
unpack.

## What correctness means here

- **Every number is traceable.** Pool-level figures resolve to an SEC 10-D
  servicer cert; loan-level figures resolve to an ABS-EE XML in the filing
  cache. Forecasts resolve to the unified Markov model (`deal_forecasts`
  table) whose methodology is documented in the Methodology & Findings tab.
- **Chronology must use `dist_date_iso`, never `distribution_date` text.**
  Any "most recent month" selector or sort that returns a prior-year row is a
  silent-staleness bug — treat as HALT. See the sort-gotcha note in
  `CLAUDE.md`.
- **Data freshness:** the daily ingest cron runs at 14:17 UTC. A "last
  updated" timestamp older than ~36 hours on a weekday is a HALT.
- **Framing asymmetry is correct.** Narrative callouts, headline metrics,
  and summary copy should lead with Carvana. Symmetric "Carvana vs CarMax"
  framing is acceptable inside comparison tables but a HALT anywhere it
  suppresses the Carvana-centric takeaway.
- **Forecasts are forecasts.** Any projected CNL, residual profit, or
  trigger-risk number needs nearby language making clear it is model output,
  not realized fact.

## Red-flag patterns

Reviewer flags these as HALT:

- **Placeholder text** ("TODO", "Lorem ipsum", "TBD", "FIXME", "—" where a
  real number is expected, `NaN`, `undefined`, `null`, blank metric tiles).
- **Loan-level PII.** Loan IDs, obligor names, addresses, or any field that
  could re-identify a borrower. ABS-EE XML contains these upstream but none
  should ever hit a rendered page.
- **Forward-looking claims without a model disclaimer** ("Carvana will lose
  X%", "residual profit is Y"). Always frame as the model's expectation.
- **Broken links, 404s, or empty sub-tabs** on any deal page.
- **Markdown-wrapped or backticked URLs** in any copy (iOS URL detection
  drags the wrapping characters into the tap target → 404).
- **Stale "last month" data.** Any "most recent" selector or "Recent Trends"
  row dated more than ~45 days ago on a live-data deal is a HALT (date-sort
  regression).
- **Mixing of Carvana Prime and Non-Prime aggregates** without a tier label.
  Non-Prime has its own Markov and materially different hazards; blending
  them into a single "Carvana average" misleads the reader.
- **CarMax 2014-2016 deals presented with loan-level analytics.** Those 12
  deals are pre-Reg-AB-II; loan-level fields do not exist upstream and any
  non-null loan-level cell is fabricated.
- **Horizontal overflow on 390px viewport** in the top nav, headline metric
  row, or any narrative paragraph. Tables may scroll horizontally (they are
  wrapped in `.tbl`); body copy and controls must not.

## Aesthetic bar

Investor-grade polish — closer to a broker research note than a Bloomberg
terminal. Clean white cards on a light-gray background, a single accent blue
(`#1976D2`), conservative typography, generous whitespace, no decorative
chrome. Every interactive control must have a ≥44px tap target (iPhone
thumb). Charts (Plotly) should have the modebar always visible, no hover-to-
reveal. Tables on mobile should wrap in a horizontally scrollable container;
headline numbers should never overflow. Emojis: none, except in the
Methodology & Findings "Carvana takeaways" callout where a single accent is
acceptable.

## Known exceptions

Legitimate things that might look like bugs — do **not** HALT on these:

- **NULL cells in CarMax 2014-2015 pool-level tables** for `recoveries`,
  `cumulative_gross_losses`, `cumulative_liquidation_proceeds`,
  `delinquent_121_plus_balance/count`, `delinquency_trigger_actual`. The
  source certs genuinely lack these columns.
- **No loan-level tab on 12 pre-Reg-AB-II CarMax deals** (2014-1 through
  2016-4). Correct — no XML exists upstream.
- **Negative `liquidation_proceeds` or `cum_net > cum_gross` in early-cycle
  Carvana months.** Carvana's issuer formula nets liquidation expenses into
  liquidation proceeds; the relaxed invariant is
  `cum_net ≤ cum_gross + |cum_liq_proceeds|`.
- **Restatement markers on ~80 rows across ~38 deals** where servicer
  restated `cumulative_net_losses`. The dashboard shows a restatement flag
  plus a monotone envelope — this is intentional, not a parser bug.
- **CarMax 2026-2 absent from Residual Economics** even though it is
  registered. Dashboard filters render only deals with an
  `initial_pool_balance`; 2026-2 will appear on its first 10-D report.
- **Trigger Risk column showing "—"** on some deals where the Markov has
  not yet emitted an OC-breach probability. Known follow-on; not a HALT.
- **`?v=N` cache-bust query strings on CSS/JS** assets. Cloudflare purge
  token pending (user-action `ua-3eba7411`); workaround is intentional.

## User journeys

Authored at project start. Maintained as product direction shifts. The
canonical definition of "what this project does for a user." Referenced by
spec conversations, the acceptance-rehearsal QA gate, and builder onboarding.

### Journey: monthly-surprise-check
**Persona**: Non-technical equity investor checking his Carvana thesis on
his iPhone over morning coffee.
**Goal**: In under 60 seconds, learn whether Carvana's ABS deals surprised
the model (good or bad) this month.
**Steps**:
1. Open https://casinv.dev/CarvanaLoanDashBoard/ (lands on Recent Trends).
2. Read the top Carvana-framed callout — headline: are recent months
   tracking, beating, or missing the Markov expectation in aggregate?
3. Scan the per-deal rows (sorted by remaining outstanding $, biggest
   first) for surprise tags vs. current-month Markov expectation.
4. Note any Δ projected residual profit rows that moved materially.
**Outcome**: A one-sentence mental update on Carvana ABS performance this
month, with the specific deals driving any surprise.

### Journey: residual-on-a-specific-deal
**Persona**: Same investor, now curious about one deal he read about in an
earnings call.
**Goal**: Compare the initial residual forecast on a specific Carvana deal
to where it is tracking today.
**Steps**:
1. Go to Residual Economics tab.
2. Find the deal row (chronologically sorted, Carvana Prime + CarMax
   interleaved; Carvana Non-Prime separated below).
3. Read the Initial Forecast block (8 cols) next to the Current Forecast
   block (5 cols) and the Deltas/Variance block.
4. Glance at %Done and Trig Risk to contextualize the delta.
5. Optionally click through to the deal page for pool-level and loan-level
   detail.
**Outcome**: He knows whether this deal's residual is tracking, ahead, or
behind the at-issuance model, and by how much.

### Journey: carvana-vs-carmax-vintage-compare
**Persona**: Same investor, stress-testing the Carvana underwriting thesis.
**Goal**: Does Carvana's 2024 vintage look better or worse than CarMax's
2024 vintage on losses?
**Steps**:
1. Go to Residual Economics tab.
2. Toggle the issuer-filter checkboxes (Carvana Prime + CarMax Prime on;
   Non-Prime off).
3. Scroll to the 2024 section (chronologically interleaved).
4. Compare Current Forecast CNL and %Done columns across Carvana 2024-P1..
   2024-P4 vs CarMax 2024-1..2024-4.
**Outcome**: A vintage-level read on whether Carvana's underwriting is
tracking in line with, tighter than, or looser than the benchmark.

### Journey: non-prime-loss-intuition
**Persona**: Same investor, pushing on the scariest line in the model:
Carvana Non-Prime projected CNL.
**Goal**: Understand why the model projects elevated losses on Non-Prime
deals.
**Steps**:
1. Go to Methodology & Findings tab.
2. Read the model spec (section 1-2).
3. Inspect the transition heatmaps (section 4) for the representative
   Non-Prime FICO/LTV/age cells.
4. Inspect the hazard chart (section 5) — Non-Prime panel specifically.
5. Read the Carvana takeaways callout at the bottom.
**Outcome**: He can articulate in plain English the two or three drivers
(FICO, LTV, age) that make the Non-Prime hazard what it is — enough to
judge whether the model's number is plausible.

### Journey: data-quality-spot-check
**Persona**: Same investor in skeptic mode — "should I trust these
numbers?"
**Goal**: Sanity-check the underlying loan-level data for one specific
deal.
**Steps**:
1. Go to Deals tab.
2. Click into a recent Carvana deal (e.g., 2024-P3).
3. Open the Loan-level sub-tab.
4. Scan distributions (FICO, LTV, APR, age) for sensible shapes; open the
   Documents sub-tab to confirm the source 10-D and ABS-EE filings are
   linked.
**Outcome**: He is either satisfied the data is clean and real, or he
spots a shape that looks wrong and flags it.

### Journey: trigger-watch
**Persona**: Same investor, watching for tail risk.
**Goal**: Identify any deal that is close to a delinquency or cumulative-
loss trigger.
**Steps**:
1. Go to Residual Economics tab.
2. Sort the table by the Trig Risk column (descending).
3. Inspect the top row(s) with non-trivial trigger risk.
4. Click through to the deal page and open the Triggers sub-tab to read
   the actual trigger levels and current cushion.
**Outcome**: He knows whether any Carvana deal is meaningfully close to a
trigger event that would accelerate amortization or redirect residual
cashflow.
