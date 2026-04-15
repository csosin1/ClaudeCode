# Gym Intelligence — Project State

_Last updated: 2026-04-15 ~04:25 UTC by Gym Intelligence session (slug: gym-intelligence)_

## Current focus

**Cluster-strategy thesis write-up is live on preview** at `https://casinv.dev/gym-intelligence/preview/thesis` with PDF download at `/thesis.pdf`. User asked for an investor-grade write-up testing Basic-Fit's clustering claim; audit-before-writeup surfaced data-quality issues that forced an honest scope pivot: chapters 1–3 methodology + chapters 4–6 as audit diagnosis, directional-only evidence from the clean subset, and a remediation plan. Currently idle awaiting user review.

## Last decisions

- **Audit before writeup, per SKILLS/data-audit-qa.md.** Surfaced 10 findings (F-001 through F-010) in `AUDIT_FINDINGS.md`. Critical: Overpass present-day undercounts Basic-Fit ~34%; OHSOME historical matches published BF data within ~2% but undercounts peer chains (L'Orange Bleue, KeepCool, EasyFitness, SportCity, Fitness Park) by 30-87%. Running the excess-clustering test on this data would fabricate a clustering signal. **Audit verdict: FAIL-AT-ITERATION-2** on the original scope; PASS on the scoped-down honest-diagnosis deliverable.
- **Scope pivot approved in AUDIT_FINDINGS.md decision block.** Writeup narrowed from "hypothesis test results" to "honest investor-grade diagnosis + directional evidence from the clean subset + remediation plan for the rigorous version." Germany clean-subset shows +55.6 percentage points excess clustering — the one defensible directional finding in the current data.
- **Writeup shipped as markdown + live HTML + PDF.** 11,625 words, 6 chapters, MathJax-rendered equations, weasyprint PDF. Latest commits on main: bf7a6a1 (Flask routes), 1df7efc (chapters 4-6), 1565f32 (audit findings), e53eb6e (chapters 1-3).
- **Altafit ownership fixed** public → private on both live and preview DBs this iteration.
- **Overpass→OHSOME swap for historical backfill** working; ran 10/16 quarters as of this writing. Not used in the shipped writeup because the audit findings (F-006–F-010) apply to the historical data too. Results will inform the next iteration after the matcher fix.

## Open questions

- **Does the user accept the scope pivot?** The writeup is an honest "we tried to run the test and the data wouldn't let us" rather than the originally-scoped "test-confirmed-hypothesis." A PhD economist would respect the honesty; an investor who wanted a confident answer may be disappointed. Ready for either reaction.
- **Does the user want to commission the remediation work?** Chapter 6 lists ~10 hours of engineering (chain-matcher fix with brand-wikidata primary key + per-chain published-truth anchors + re-collection of 16 quarters) that would unlock the rigorous test.
- **Capacity still warn-to-urgent** (swap 94%+ earlier). Driven by sibling Claude sessions, not this project. Droplet resize is the permanent fix but wasn't triggered this session.
- **Backfill still running** (10/16 quarters, ETA ~1 hr from timestamp of this file). Will land in preview DB but not surface in the writeup without a re-collection pass after matcher fix.

## Next step

**Await user feedback on the writeup.** If they approve as-is: promote to live via `bash /opt/site-deploy/deploy/promote.sh gym-intelligence` (this only swaps code; the thesis.md + writeup directory needs to be rsynced or the promote script updated to carry non-code files). If they want the rigorous version: spec the chain-matcher fix and dispatch Builder subagents to rebuild the peer-chain coverage before re-running. If they want additional chapters (e.g., Chapter 7 on the Ripley's-K formalization now that chapter 6 described it): dispatch another Writer.

**Interim hygiene (per SKILLS/session-resilience.md, active-work 30-min cadence):** this file is current as of the pivot decision and shipped writeup. Commit + push after every meaningful change. Load-bearing state on disk: writeup/thesis.md (source of truth for the deliverable), AUDIT_FINDINGS.md (audit record), this PROJECT_STATE.md (session handoff), all on main at origin.
