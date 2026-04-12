## Current Task
Name:              Fix SEC filing links on live dashboard
CLAUDE.md version: 1.0
Status:            qa
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
Pending: live URL verification scheduled. Expected:
  - `curl -sIL https://casinv.dev/CarvanaLoanDashBoard/docs/2020-P1/2020-P1_servicer_2025-12.pdf` → 200, content-type application/pdf
  - Preview URL unchanged (was already serving PDFs correctly)

## Blockers
[none]

## Cost
Small fix: ~6k tokens estimated.
