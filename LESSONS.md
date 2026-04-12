# Lessons Learned

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
