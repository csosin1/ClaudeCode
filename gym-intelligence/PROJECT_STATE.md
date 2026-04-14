# gym-intelligence — Project State

_Last updated: 2026-04-14 by gym-intelligence session_

## Current focus
**Awaiting user "ship it" on preview.** Completed a reclassification + ownership pass that produced material data improvements (competitor count more than doubled) and added a "Competitors only" toggle to the dashboard (default ON). Live is untouched until acceptance.

## Last decisions
- **Classify unknowns with knowledge-only path, not web_search.** Anthropic's `web_search_20250305` tool returned 529 Overloaded 100% of the time on this account during the run; plain inference on `claude-sonnet-4-6` worked fine and already knows most European gym chains. Retry with web_search later — it's capacity, not quota, so should clear.
- **Municipal competitors go in the direct_competitor bucket if they sell a monthly gym membership under €50.** Added `ownership_type TEXT` column (private / public / unknown) and a "Municipal competitors" counter on the overview. After the full pass: 1 municipal competitor flagged (Altafit) — likely a misclassification; all other public-ownership chains landed in non_competitor (municipal pools/pavilions that sell pay-per-entry, not memberships).
- **Dashboard shows only competitive chains by default.** Unchecking "Competitors only" returns the full 31k-chain view via `?show=all`.

## Open questions
- **Altafit is the only municipal competitor** — and it's almost certainly wrong; Altafit is a private Spanish budget chain. Worth manually correcting in DB before promoting, or re-running ownership on just the competitor set with a stricter prompt.
- **23 chains still `unknown`** after the pass — all tiny (4–18 locations) and genuinely obscure European brands (Fitomat, Bionic, Sano, Fit-in, etc.). Retrying with web_search once Anthropic's capacity clears may resolve most of them.
- **Session parallelism keeps clobbering in-flight edits.** During this task, preview files were rsynced over from source twice mid-session by auto-deploys triggered by other project chats. Workflow-wise it worked out (source was updated last) but it's fragile.

## Next step
User eyeballs  https://casinv.dev/gym-intelligence/preview/  — if accepted, run `bash /opt/site-deploy/deploy/promote.sh gym-intelligence` to promote code + rsync preview DB → live. If not accepted, iterate on preview without asking.
