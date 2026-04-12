## Current Task
Name:              SEC filing links on Carvana ABS dashboard
CLAUDE.md version: 1.0
Status:            done (pending Cloudflare cache expiry for end-user view)
Spec approved:     yes (user: "Pls fix")
Rollback tag:      (small fix)
Resume hint:       If user still reports bad content, check: (a) CF cache on /CarvanaLoanDashBoard/preview/index.html cleared, and (b) the Documents tab rows link to https://www.sec.gov/Archives/... not docs/<deal>/...

## Spec
SPEC: Fix SEC filing links on Carvana ABS dashboard
What will be built: Tapping a SEC filing on the dashboard opens the actual filing content.
Success criteria:
  - Every "Servicer Certificate" row in the Documents tab opens a working filing (JPG pages + text visible).
  - No rows land on an empty/stub PDF.
Non-goals:          Re-rendering the filings locally as PDFs; rebuilding the PDF pipeline.
File location:      carvana_abs/generate_dashboard.py, carvana_abs/generate_preview.py
Approach:
  1. Fix promote_to_live() to sync preview/docs/ → live/docs/ (done — but PDFs were empty anyway).
  2. Diagnose why the PDFs themselves had no content. Root cause: EDGAR servicer certs are image-based (JPG pages + 1pt white OCR text). weasyprint couldn't embed the JPGs, so PDFs rendered as bare exhibit references.
  3. Drop the local-PDF path entirely. Link "Servicer Certificate" rows straight to servicer_cert_url on sec.gov, which serves the JPG pages in place.

## Builder Output
- `carvana_abs/generate_preview.py` — promote_to_live() now rsyncs preview/docs/ to live/docs/ in addition to copying index.html. (Commit 88725d8.)
- `carvana_abs/generate_dashboard.py` — removed the pdf/html fallback chain; all 1,225 servicer-cert rows now link to EDGAR directly. (Commit ae9b5c5.)
- Regenerated preview, promoted to live. Verified `grep -c 'href="docs/'` returns 0 and `grep -c 'servicerrepo.htm' ... >SEC&nbsp;Filing<` returns the full set.

## Reviewer Verdict
Self-reviewed.
  - Net behaviour: every servicer-cert tap now leaves the site and lands on sec.gov — content is correct and always up-to-date.
  - The broken local PDFs are no longer linked; leaving them on disk for now (harmless; can be cleaned up in a later task).
  - generate_pdfs.py still runs in auto_deploy.sh. It writes PDFs nothing links to — wasted cycles but not incorrect. Flagging for a follow-up removal.

## QA Result
Manual verification on origin:
  - `grep 'href="docs/' live/index.html` → 0 hits.
  - 1,225 SEC EDGAR servicer-cert links in live/index.html.
  - Sample SEC URL resolves to the real filing with JPG pages visible.
Cloudflare currently caches the old dashboard HTML and the old empty PDF response on the canonical URL. No CF API creds on box, so cache will clear via TTL within ~4 hours. Cache-busted URLs return the new content immediately.

## Follow-ups (out of scope here)
- auto-deploy.timer for this branch is stopped; pushes don't auto-deploy. Promotes were done directly on the droplet in this session.
- generate_pdfs.py no longer serves any purpose. Remove it + the docs/ directories in a cleanup task.
- Consider adding a Cloudflare API token + purge step to deploy so future cache-poison fixes don't need a 4h wait.

## Blockers
[none]

## Cost
~25k tokens across diagnosis + fix + verification.
