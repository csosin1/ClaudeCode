# Project Rules

## Global Rules (apply to all projects)

### Verify Your Work
- ALWAYS check your work before showing results to the user. Never say "check the preview" without having verified it yourself first.
- If you cannot access a URL or service, say so immediately — don't wait or retry silently for 20 minutes.
- After pushing code changes, verify the deploy succeeded and the output is correct before sharing a link.
- Run syntax checks, tests, and validation before declaring a task done.

### Automate Everything
- Never ask the user to do manual steps (load files, run commands, check URLs, etc.) — do it yourself.
- If a build/deploy/test step exists, run it automatically.
- If you need data to verify, write a script to check it rather than asking the user to look.

### Sharing Links
- When sharing URLs with the user, always use plain clickable links — never wrap them in markdown bold (`**`), backticks, or other formatting that breaks clickability.
- Correct: http://159.223.127.125/games/sky-barons/
- Wrong: **http://159.223.127.125/games/sky-barons/**

### Be Direct About Limitations
- If you can't access something due to network/auth restrictions, state it clearly on the first attempt — don't keep retrying.
- If a deploy is taking a long time, explain why and give a realistic estimate.
- Don't say "it should work now" unless you've actually verified it works.

### Code Quality
- Don't add features beyond what was asked.
- Fix root causes, not symptoms. When a value is wrong, trace it back to the data source.
- Add sanity checks on parsed data — validate ranges, cross-reference between tables, flag outliers.
- When building data pipelines, make the backend solid so the frontend only needs display changes.

### Git Workflow
- Commit and push all changes before stopping (enforced by stop hook).
- Use descriptive commit messages explaining why, not just what.
- Never force-push or amend published commits without explicit permission.
- Don't create PRs unless explicitly asked.

## Droplet — Multi-Project Server

**IP:** 159.223.127.125

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

### How Auto-Deploy Works

There are **two independent auto-deploy systems** on the droplet, each running every 30 seconds:

#### 1. General Deploy (main branch → static files)
- **Watches:** `main` branch
- **Repo clone:** `/opt/site-deploy/`
- **Timer:** `general-deploy.timer`
- **Log:** `/var/log/general-deploy.log`
- **What it does:**
  - Syncs `games/` directory → `/var/www/games/` (rsync, mirrors repo exactly)
  - Copies `deploy/landing.html` → `/var/www/landing/index.html`
  - Checks `deploy/NGINX_VERSION` and runs `deploy/update_nginx.sh` if changed

**To deploy a game or static page:** Push files to `games/<name>/index.html` on `main`. They appear at `http://159.223.127.125/games/<name>/` within 30 seconds.

#### 2. Carvana Deploy (feature branch → dashboard)
- **Watches:** `claude/carvana-loan-dashboard-4QMPM` branch
- **Repo clone:** `/opt/abs-dashboard/`
- **Timer:** `auto-deploy.timer`
- **Log:** `/var/log/auto-deploy.log`
- **What it does:** Pulls code, runs Python pipeline (reingest, model, generate HTML), writes to `static_site/preview/`

### Adding a New Project
1. Create a new directory: `/opt/<project>/` on the droplet
2. Add a new `location /<ProjectName>/` block in `deploy/update_nginx.sh`
3. Bump the version number in `deploy/NGINX_VERSION` to trigger nginx reload
4. Add a link card to `deploy/landing.html`
5. Set up its own auto-deploy script if needed (do NOT reuse Carvana's)

### Deploying Static Files (Games, Simple Pages)
Any chat can deploy static files by pushing to `main`:
1. Push your HTML to `games/<your-game>/index.html` on the `main` branch
2. The general auto-deploy pulls within 30s and syncs to `/var/www/games/`
3. Your page is live at `http://159.223.127.125/games/<your-game>/`
4. No SSH access needed. No manual steps.

**Step-by-step commands (from any branch):**
```bash
# 1. Make sure your game HTML file is ready (single self-contained index.html)
# 2. Switch to main, pull latest, add your game, push:
git stash                              # save any uncommitted work
git checkout main
git pull origin main
mkdir -p games/<your-game>
cp <path-to-your-game.html> games/<your-game>/index.html
git add games/<your-game>/index.html
git commit -m "Deploy <your-game> to /games/<your-game>/"
git push origin main
git checkout -                         # go back to your feature branch
git stash pop                          # restore uncommitted work
# 3. Wait ~30 seconds, then verify:
#    http://159.223.127.125/games/<your-game>/
```

**Important:** You MUST push to `main`, not your feature branch. The auto-deploy only watches `main` for games.

### Server/Deploy General Rules
- When sharing a droplet across projects, use separate nginx routes, databases, and environment configs.
- After pushing changes that trigger auto-deploy, wait for confirmation before sharing preview links.
- If auto-deploy status isn't reporting back, diagnose the push mechanism — don't just keep waiting.

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
