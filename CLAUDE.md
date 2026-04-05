# Project Rules

## Droplet — Multi-Project Server

**IP:** 159.223.127.125
**Auto-deploy:** Runs every 30s, pulls from branch `claude/carvana-loan-dashboard-4QMPM`, rebuilds, and serves.

### URL Layout
| URL Path | Project | Server Directory |
|----------|---------|-----------------|
| `/` | Landing page | `/var/www/landing/` |
| `/CarvanaLoanDashBoard/` | Carvana ABS Dashboard (live) | `/opt/abs-dashboard/carvana_abs/static_site/live/` |
| `/CarvanaLoanDashBoard/preview/` | Carvana ABS Dashboard (preview) | `/opt/abs-dashboard/carvana_abs/static_site/preview/` |
| `/games/` | Games | `/var/www/games/` |

### File Isolation Rules (CRITICAL)
Each project is isolated to its own directory on the droplet. **Never write files outside your project's directory.**
- **Carvana dashboard** writes ONLY to `/opt/abs-dashboard/`
- **Games** writes ONLY to `/var/www/games/`
- **Landing page** writes ONLY to `/var/www/landing/`
- Future projects get their own `/opt/<project>/` directory

### Adding a New Project
1. Create a new directory: `/opt/<project>/` on the droplet
2. Add a new `location /<ProjectName>/` block in `deploy/update_nginx.sh`
3. Bump the version number in `deploy/NGINX_VERSION` to trigger nginx reload
4. Add a link card to `deploy/landing.html`
5. Set up its own auto-deploy script if needed (do NOT reuse Carvana's)

## Carvana Dashboard

### Preview Workflow
After pushing changes that affect the dashboard, share the preview link:
**Preview URL:** http://159.223.127.125/CarvanaLoanDashBoard/preview/ (append `?v=<random>` to bust cache)
**Live URL:** http://159.223.127.125/CarvanaLoanDashBoard/

### Deploy Flow
1. Push code to `claude/carvana-loan-dashboard-4QMPM`
2. Auto-deploy pulls within 30s
3. Regenerates dashboard → writes to `static_site/preview/`
4. To promote preview to live: create `deploy/PROMOTE` file
