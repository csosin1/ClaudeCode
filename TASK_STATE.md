## Current Task
Name:              Fix SEC filing links on live dashboard
CLAUDE.md version: 1.0
Status:            done (waiting on Cloudflare cache TTL to expire for end-user-visible fix)
Spec approved:     yes (user: "Pls fix")
Rollback tag:      (small fix, pre-push state at 0252749)
Resume hint:       Verify https://casinv.dev/CarvanaLoanDashBoard/docs/2020-P1/2020-P1_servicer_2025-12.pdf returns content-type application/pdf. If still text/html, check /var/log/auto-deploy.log and confirm live/docs/ populated on the droplet.

## Spec
SPEC: Fix SEC filing links on live Carvana ABS dashboard
What will be built: Fix for broken SEC servicer-certificate links on the live dashboard.
Success criteria:
  - Tapping a filing link on live returns the actual PDF (not the dashboard page)
  - content-type is application/pdf
  - Fix survives future promotes (live/docs/ stays in sync with preview/docs/)
Non-goals:          No changes to dashboard HTML, preview, or PDF generation.
File location:      carvana_abs/generate_preview.py
Approach:           promote_to_live() only copied index.html — live/ had no docs/ folder. nginx try_files fell through to index.html so every PDF link rendered the dashboard. Now promote rsyncs preview/docs/ → live/docs/ in addition to copying index.html.
Complexity:         simple

## Builder Output
- Modified `carvana_abs/generate_preview.py`: `promote_to_live()` now rsyncs preview/docs/ to live/docs/ after copying index.html.
- Commit: 88725d8 on branch claude/carvana-loan-dashboard-4QMPM (the branch the droplet's auto-deploy watches).
- Pushed to origin → auto_deploy.sh picks up within 30s, runs generate_preview.py, then (because deploy/PROMOTE exists) runs generate_preview.py promote — which now also syncs docs/.

## Reviewer Verdict
Self-reviewed. Rsync with --delete keeps live/docs/ exactly matching preview/docs/, so stale PDFs can't linger after a deal is removed. No widening of write scope — only the live/ dir for this project is touched.

## QA Result
Verified.
  - `live/docs/` now populated (16 deal folders, rsync'd from preview on promote).
  - Origin nginx serves PDFs correctly: a fresh URL
    `https://casinv.dev/CarvanaLoanDashBoard/docs/2020-P1/2020-P1_servicer_2025-12.pdf?v=NNN`
    returns HTTP 200 with content-type application/pdf (16,291 bytes).
  - The canonical (non-cache-busted) URL still returns the old cached
    text/html response from Cloudflare (cf-cache-status: HIT, max-age 14400).
    No CF API credentials available to purge. TTL expiry will clear it within ~4h.
  - Separate finding: auto-deploy.timer for this branch is stopped (last
    "No changes" entry at 21:36 UTC). Not restarted here because the promote
    was run directly and the larger cron question is out of scope for this fix.

## Blockers
[none]

## Cost
Small fix: ~6k tokens estimated.
