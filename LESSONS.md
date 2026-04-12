# Lessons Learned

## 2026-04-12 SEC servicer-cert PDFs were rendering empty — image-based EDGAR filings
- **What went wrong:** After fixing the routing, tapping a servicer-certificate PDF showed what looked like a bare exhibit reference ("EX-99.1 2 crvna….htm EX-99.1") and no report data. The PDFs themselves were ~16KB — all "content" but no content.
- **Root cause:** Carvana's servicer certs on EDGAR are image-based filings: each page is a JPG (`crvna<deal>servicerrepo001.jpg`, `002.jpg`, …) referenced by relative URL inside the HTML, with a 1pt white hidden OCR text layer overlaid for accessibility. `generate_pdfs.py` fed the cached HTML straight to weasyprint, which had no way to resolve the JPG relative paths (we never downloaded them). Result: PDFs contained only the invisible OCR text plus the `<DOCUMENT>`/`<TYPE>` header — looked like an exhibit reference page.
- **What to do differently:**
  - For image-based filings, don't try to re-render to PDF. Either (a) download the JPG assets alongside the HTML and rewrite relative paths before rendering, or (b) link directly to the SEC EDGAR URL, which already serves the JPGs in place.
  - We chose (b) — simpler, always current, no cache/PDF pipeline to maintain. Builders creating "download the filing" UX should default to linking to sec.gov unless there's a specific reason to re-host.
  - When the HTML has tiny `font-size:1pt;color:white` text blocks, that's the OCR layer — the real content is the `<IMG>` siblings. Treat that as a signal to link out, not render locally.

## 2026-04-12 SEC filing links on live were 404'ing silently
- **What went wrong:** SEC filing PDF links on the live Carvana ABS dashboard returned the dashboard page instead of the PDF. User noticed because tapping them didn't open the document.
- **Root cause:** `promote_to_live()` in `carvana_abs/generate_preview.py` only copied `index.html` from preview/ to live/. The `docs/` tree (where generate_pdfs.py writes PDFs) was never synced. nginx `try_files $uri $uri/ /CarvanaLoanDashBoard/index.html` masked the failure — every missing PDF silently served the dashboard page with HTTP 200, so no monitoring caught it.
- **What to do differently:**
  - When promote is a "copy the preview" step, copy the whole preview directory (or an explicit rsync of every asset subdir), not just a curated list of files. Asset subdirs like docs/, images/, data/ are easy to forget.
  - Any nginx `try_files ... /index.html` fallback masks 404s on sibling assets. For URLs that are expected to be files (PDFs, JSON, CSV), tests must assert the response `content-type`, not just HTTP 200.

## 2026-04-05 Agent Harness Setup
- **What went wrong:** Attempted SSH to configure nginx and observability on the droplet. SSH and direct HTTP are blocked from the Claude Code sandbox. Wasted time creating a standalone setup script before realizing the auto-deploy pipeline could do it.
- **Root cause:** CLAUDE.md didn't state that SSH is unavailable.
- **What to do differently:** All server-side changes go through `deploy/auto_deploy_general.sh` or `deploy/update_nginx.sh`. Never attempt SSH, scp, or create "run this on the server" scripts.
