# Project Rules

## Carvana Dashboard

**Auto-deploy:** Runs every 30s, pulls from branch `claude/carvana-loan-dashboard-4QMPM`, rebuilds, and serves.

### Preview Workflow
After pushing changes that affect the dashboard, share the preview link:
**Preview URL:** http://159.223.127.125/CarvanaLoanDashBoard/preview/ (append `?v=<random>` to bust cache)
**Live URL:** http://159.223.127.125/CarvanaLoanDashBoard/

### Deploy Flow
1. Push code to `claude/carvana-loan-dashboard-4QMPM`
2. Auto-deploy pulls within 30s
3. Regenerates dashboard → writes to `static_site/preview/`
4. To promote preview to live: create `deploy/PROMOTE` file
