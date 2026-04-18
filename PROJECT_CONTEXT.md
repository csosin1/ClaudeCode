# PROJECT_CONTEXT — abs-dashboard

_Authored: 2026-04-17T00:00Z · Version: 1 · Mode: initial_
_Sources: chat history `/root/.claude/projects/-opt-abs-dashboard/eaea28d6-b71a-4196-892e-14fcdcc899fe.jsonl` (6,136 lines, Apr 1 – Apr 18 2026 — sampled early / middle / tail), repo artifacts (PROJECT_STATE.md, CLAUDE.md, LESSONS.md, CHANGES.md, RUNBOOK.md, AUDIT_FINDINGS.md, carvana_abs/*, carmax_abs/*, deploy/*), external research (S&P Global, Moody's Analytics, Janus Henderson, SEC Reg AB II, Auto Finance News, CAS Investment Partners published letters)_
_Next refresh due: 2026-07-16_

## The user

Clifford ("Cliff") Sosin — founder and principal of **C.A.S. Investment Partners**, a concentrated value fund he launched in 2012. Carvana is his largest position by far (~90%+ of the public portfolio). This dashboard exists because his job requires him to understand Carvana's auto-ABS business in depth, continuously, and without waiting on a sell-side analyst or an Intex / Bloomberg / Moody's Analytics subscription to frame it for him.

He is **investment-sophisticated, not engineering-sophisticated**. He prompts from iPhone, often one line at a time, sometimes mid-thought, occasionally auto-corrected. He knows what a Markov transition matrix is, what a cumulative net loss curve is, what a residual tranche is, what a trigger breach is, what a deal-weighted vs pool-weighted calibration does, and what Bayesian updating is ("we had a prior, we got more information wouldn't a more explicitly Bayesian inference be in order?"). He does not know or care what `sqlite3.OperationalError: database is locked` means — that is Claude's problem.

What he already knows — **do not re-explain**: ABS deal mechanics, tranche waterfalls, overcollateralization, excess spread, pool factor, WAL, severity / LGD, FICO / LTV / seasoning, prime vs non-prime tiers, Carvana vs CarMax as issuers, the difference between servicer cert (10-D) data and loan-tape (EX-102) data, rating-agency presale loss estimates as a benchmark, residual economics as the equity return on a securitization.

Style cues he repeats: "don't fudge any data," "bring uncertainties up to me," "no gaps, no errors," "reflect and check — from original sources any datapoints that look wrong," "the meta-goal here is for me to understand Carvana's auto-ABS business insofar as it impacts Carvana." He rewards rigor and is comfortable with model complexity as long as it is motivated by the data — see his multi-paragraph notes on conditioning the Markov transitions on seasoning, FICO, LTV, modification status, and the ratio-of-actual-to-forecast Bayesian calibration he eventually specified.

## The builder context

Solo-operator Claude Code platform; abs-dashboard is one of 5 projects that share droplet infra. **This project is materially heavier than any other on the platform** and has its own topology:

- **PROD droplet** (10.116.0.3, `ssh prod-private`, 8 GB / 4 CPU / 154 GB): where all compute runs. Source DBs (`carvana_abs/db/carvana_abs.db` ≈ 3.6 GB, `carmax_abs/db/carmax_abs.db` ≈ 29 GB), Markov training, methodology regressions, dashboard regen.
- **DEV droplet** (159.223.127.125, 4 GB shared): rollback snapshot + a thin shell for git push / ssh-out to prod. Heavy Python on dev OOMs the other tenants; a watchdog SIGTERMs wrong-host heavy processes after 120 s.
- **Live URL:** https://casinv.dev/CarvanaLoanDashBoard/ (Cloudflare in front; cache-purge pending user-action for CF token — `?v=N` workaround in place).
- **Working branch** (NOT main): `claude/carvana-loan-dashboard-4QMPM`. Auto-deploys on push via webhook → `deploy/auto_deploy.sh` / `deploy/overnight_post_markov.sh`.
- **Daily ingest cron:** 14:17 UTC, `deploy/cron_ingest.sh` pulls new EDGAR filings, reruns parser + summaries + model, promotes preview → live.
- **Weekly discovery:** `deploy/discover_new_deals.py` cron-checks EDGAR for new Carvana / CarMax trust CIKs (added after the 5-deals-missed-silently incident on 2026-04-18).

Shared Python venv `/opt/abs-venv/` (not owned by this project). Everything respects `SKILLS/long-running-jobs.md` (systemd-run for >15 min work), `SKILLS/data-audit-qa.md` (halt-fix-rerun audit loop), `SKILLS/memory-hygiene.md`, `SKILLS/capacity-monitoring.md`. Observed pattern: the head agent dispatches many parallel builder / auditor subagents per user prompt, some running multi-hour Markov retrains, a discovery scanner, and a CarMax ingest all at once.

## The world this project lives in

US auto-loan asset-backed securitizations. Carvana is the **subject**; CarMax (CAOT — CarMax Auto Owner Trust) is the **benchmark**. This asymmetry is load-bearing: the dashboard may show symmetric Carvana-vs-CarMax panels, but narrative callouts, Recent Trends framing, and Methodology takeaways lead with Carvana and use CarMax to calibrate.

**The peer universe and standard conventions:**
- **Issuers / shelves tracked here:** Carvana Auto Receivables Trust (CART) prime (`YYYY-P1..P4`) and non-prime (`YYYY-N1..N4`); CarMax Auto Owner Trust (CAOT, `YYYY-1..4`, all prime-ish). 20 Carvana + 37 CarMax ingested deals as of 2026-04-18.
- **Other peers investors benchmark to** (not yet in the dashboard): Santander Drive Auto Receivables Trust (SDART), AMCAR, Westlake — most are retrenching in 2026, issuing less and mostly investment-grade tranches only.
- **Standard metrics:** CNL (cumulative net loss), CGS (cumulative gross loss), pool factor, WAL, 60+ DQ roll rate, excess spread, weighted-average coupon (WAC), current vs at-issuance pool composition, severity / LGD.
- **Data primitives:**
  - **Servicer cert (10-D, EX-99.1)** — monthly pool-level: distribution date, collection-period data, pool balance, losses, DQ buckets, OC test results. Image-based JPG filings for some issuers (link out to EDGAR rather than re-render).
  - **Loan tape (EX-102, ABS-EE XML)** — asset-level: one row per loan per reporting period, FICO, LTV, origination date, payment history, modification flag, state, rate. 99 M rows in `loan_performance` across all tracked deals.
- **Regulator:** SEC Reg AB II (2014 rule, enforced since 2016 for new shelves) — EX-102 loan-tape disclosure is the canonical asset-level source. 2014-2015 CarMax deals pre-date Reg AB II → pool-level only, never loan-level; NULLs in those rows are source-faithful, not parser bugs.
- **2026 market backdrop:** Moody's / S&P are projecting further weakening of auto-ABS performance; non-prime especially flagged. The aggregate subprime index is concentrated in 2022-2025 vintages that underwrote at the loosest point. This matters for how we interpret Carvana's recent-vintage numbers — "higher losses than peers" is not itself alarming if the whole cohort is softening.
- **What rating agencies publish** (KBRA, S&P, Morningstar DBRS presales) — used as a reasonableness check on our own Markov-based total-loss forecasts. The user asked for this comparison explicitly: "Compare these to the KBRA or rating-agency loss forecasts."
- **What competing tools do** that we deliberately do not try to replicate: Intex-style deal-level cashflow waterfall modeling, Bloomberg-terminal TRACE-side pricing, Moody's CreditLens-style credit-rating opinions, a trading / order-entry surface of any kind.

## Success in the user's own words

- "I open the dashboard on my phone and the last tab I was on is still the one I'm on" (state preservation across reloads was an explicit ask).
- "I look at Recent Trends and I can tell at a glance, *for each deal where we have real money at work*, whether this month was better or worse than what the current model expected last month."
- "The meta-goal here is for me to understand Carvana's auto-ABS business insofar as it impacts Carvana."
- "No gaps. No errors." (Said literally, going to bed mid-build, 2026-04-16.)
- "The forecast model produces very high total loss content predictions for the prime loans. Walk me through how this model works." → then, after the deal-weighted + Bayesian calibration shipped: "I hadn't realized the loss forecast was so high. For some reason I had 2% in my head. Your forecast is fine." The felt-sense of success is: numbers that survive an intelligent-skeptic walk-through.
- "Don't fudge any data. Fix errors, bring uncertainties up to me."
- Implicit throughout: iPhone-renderable, no Plotly ("gets too slow"), server-rendered static HTML, links that actually open the thing they claim to open.

## Out-of-scope / not-concerns

- **Not a generalist ABS tool.** Not trying to cover credit cards, student loans, CLOs, RMBS, or non-auto asset classes. Auto only.
- **Not a trading platform.** No bid/ask, no pricing, no order entry, no P&L ledger.
- **Not a rating-agency substitute.** The dashboard displays our own Markov-based forecasts and compares them against rating-agency presale numbers as a sanity check — it does not issue ratings.
- **Not a cashflow waterfall simulator.** Residual economics tab uses a simplified pool-level model (coupon yield − debt cost − losses − servicing, with WAL weighting), not a full tranche-level waterfall with triggers and step-downs.
- **Not a multi-user tool.** One user, iPhone-first, desktop-acceptable. No auth layer, no multi-tenant, no sharing.
- **Not a live / real-time feed.** Daily ingest cron at 14:17 UTC. SEC EDGAR rate-limits to 10 req/s; heavier pulls are hours. Latency is acceptable because the source data (10-D filings) is itself monthly.
- **Not self-correcting on NULLs.** When CarMax 2014-2015 certs lack 5 columns, that NULL is correct. Source-faithful means do not synthesise values.
- **Private deals (non-SEC-filed)** are explicitly out of scope — user confirmed 2026-04: "the missing deals are private. So we can't do it ourselves from sec data."
- **Generalising CarMax and Carvana default models into one model** is deferred ("keep the Carvana and CarMax default models separate for now. At some point, I'll want to answer whether a loan made by kmx is higher or lower loss content than an otherwise similar loan by cvna").
- **PDF re-hosting of servicer certs** was tried and abandoned — image-based JPG filings → link out to EDGAR directly.

## Shorthand vocabulary

- **"The methodology tab"** — the `/methodology` subpage / section that explains the Markov model, calibration, and Bayesian update. When the user says "put it on the methodology tab," they mean this.
- **"The Residual Economics tab"** — the landing tab. Shows per-deal at-issuance, projected, realized equity-return economics with cap structure and "Other Terms" column. Chronological ordering by deal issuance, Carvana-led callouts.
- **"The Recent Trends tab"** — monthly-monitoring lens: for each deal with real money outstanding, was last month better/worse than the current Markov model expected? Sorted by outstanding $ descending. "The equity-holder monthly-monitoring perspective."
- **"The Methodology & Findings tab"** — regression + cohort-comparison analytics. Findings framed as "what this means for Carvana." Heatmaps over (FICO bucket × LTV bucket), hazard-by-LTV split Prime/Non-Prime.
- **"The loan tape"** — the EX-102 ABS-EE XML file attached to each 10-D. Authoritative asset-level.
- **"The cert"** — the 10-D servicer certificate. Authoritative pool-level.
- **"Source-faithful"** — do not auto-correct NULLs, do not smooth restated values, do not synthesise missing cells. If the issuer published it that way, that is what we show (with a restatement flag when appropriate).
- **"Deal-weighted Markov"** — training weights each deal equally rather than each loan equally, so 2022's overweight of loans doesn't dominate the transition matrix.
- **"Bayesian cal" / "calibration factor"** — the ratio of observed-to-forecast loss used to update a deal's prior forward. 6-month floor before calibration kicks in.
- **"Severity"** — loss given default (not QA-finding severity — context-dependent but in ABS chats it means LGD).
- **"CNL / CGS / WAC / WAL / DQ / OC / LGD"** — used without expansion.
- **"Trigger Risk"** — probability of an OC-breach / cumulative-loss-trigger breach. Column exists; Markov doesn't yet emit; shows "—" pending follow-on.
- **"Carvana Takeaways §12"** — the meta-goal framing callout that was retro-fitted to lead with Carvana, added as `§12` in the Carvana-framing pass.
- **"KMX" / "CVNA"** — the user's preferred shorthand for CarMax / Carvana (tickers).
- **"Prime" vs "Non-Prime"** — structurally distinct tiers with separate Markov models. Non-Prime is the Carvana N-shelf (e.g. 2021-N1..N4, 2023-N4).
- **"No gaps, no errors"** — end-of-day / going-to-bed standard. Means: audit cleanly before stopping; do not leave partial work untagged; roll back if verification fails.
- **"Ship preview, promote after audit"** — preview URL gets the new build; promote to live only after audit_display_ranges + data-audit-qa pass.
- **"Don't forget to do all your QA stuff"** — treated as mandatory, not aspirational.
- **"Just do my 4. The rest increase load time"** — signal that perceived-latency on mobile beats feature breadth when they trade off.
- **"The docs tab" / "SEC Filing"** — the Documents sub-tab that links directly to sec.gov/Archives/... rather than re-hosting PDFs.

## Authorship + refresh

_Authored: 2026-04-17T00:00Z · Version: 1 · Mode: initial_
_Source trail:_
- Chat history: `/root/.claude/projects/-opt-abs-dashboard/eaea28d6-b71a-4196-892e-14fcdcc899fe.jsonl` (6,136 lines; ~16 MB; mtime 2026-04-18). Sampled early (SEC-filing-links bug, initial pool-factor/excess-spread charts, April 2026), middle (data audit pass, conditional Markov conversation, Bayesian calibration discussion), tail (deal-weighted retrain, CarMax full-history ingest, overnight_post_markov concurrency incident, hazard-by-LTV + methodology heatmaps, display-layer audit framework, the PROJECT_CONTEXT directive itself).
- Repo artifacts: `PROJECT_STATE.md`, `CLAUDE.md`, `LESSONS.md`, `CHANGES.md`, `RUNBOOK.md`, `AUDIT_FINDINGS.md` (headers only), `carvana_abs/config.py`, `carmax_abs/config.py`, directory listings of both issuer packages + `deploy/`.
- External research (5 URLs):
  - https://www.spglobal.com/ratings/en/regulatory/article/-/view/type/HTML/id/3525472 (Carvana 2026-P1 presale)
  - https://www.moodysanalytics.com/solutions-overview/structured-finance/abs-solutions
  - https://www.janushenderson.com/en-us/institutional/article/looking-under-the-hood-of-us-auto-abs/
  - https://www.autofinancenews.net/allposts/capital-funding/auto-abs-performance-projected-to-weaken-in-2026/
  - https://www.sec.gov/files/rules/final/2014/33-9638.pdf (Reg AB II final rule)
  - Supporting: https://www.casinvestmentpartners.com/docs/CAS-Investment-Partners-April-2022-Letter-to-Partners.pdf (user's published thesis framing)

_Next refresh due: 2026-07-16_ (90-day cadence). Earlier refresh triggers: material change to REVIEW_CONTEXT.md, a product shift (e.g. adding non-auto asset classes or a second user), or a head-agent-flagged "substantial new context surfaced."

_Gaps noted on first authorship:_ Only one chat-history file present (the project is young as a context-researcher subject); once a second long chat accumulates, the `## Success in the user's own words` section can be further sharpened from durable patterns across sessions. The user's exact per-tab visual preferences (Carvana blue vs CarMax orange palette, no-Plotly rule) are captured but may warrant a dedicated screenshot appendix in a future refresh.
