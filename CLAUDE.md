# Project Rules

## General Rules

### Verify Your Work
- ALWAYS check your work before showing results to the user. Never say "check the preview" without having verified it yourself first.
- If you cannot access a URL or service, say so immediately — don't wait or retry silently.
- After pushing code changes, verify the deploy succeeded and the output is correct before sharing a link. Don't say "it should work now" unless you've actually verified it works.
- Run syntax checks, tests, and validation before declaring a task done.
- If a deploy is taking a long time, explain why and give a realistic estimate.
- If auto-deploy status isn't reporting back, diagnose the push mechanism — don't just keep waiting.

### Automate Everything
- Never ask the user to do manual steps (load files, run commands, check URLs, etc.) — do it yourself.
- If a build/deploy/test step exists, run it automatically.
- If you need data to verify, write a script to check it rather than asking the user to look.

### Sharing Links
- When sharing URLs with the user, always use plain clickable links — never wrap them in markdown bold (`**`), backticks, or other formatting that breaks clickability.

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

### File Isolation (CRITICAL)
Each project is isolated to its own directory. **Never write files outside your project's directory.** New projects get their own dedicated directory (e.g., `/opt/<project>/`).

## Droplet — Multi-Project Server

**IP:** 159.223.127.125

### URL Layout
| URL Path | Project | Server Directory |
|----------|---------|-----------------|
| `/` | Landing page | `/var/www/landing/` |
| `/games/` | Games | `/var/www/games/` |

### Auto-Deploy (General)
- **Watches:** `main` branch
- **Repo clone:** `/opt/site-deploy/`
- **Timer:** `general-deploy.timer`
- **Log:** `/var/log/general-deploy.log`
- **What it does:**
  - Syncs `games/` directory → `/var/www/games/` (rsync, mirrors repo exactly)
  - Copies `deploy/landing.html` → `/var/www/landing/index.html`
  - Checks `deploy/NGINX_VERSION` and runs `deploy/update_nginx.sh` if changed

### Deploying Static Files (Games, Simple Pages)
Any chat can deploy static files by pushing to `main`:
1. Push your HTML to `games/<your-game>/index.html` on the `main` branch
2. The general auto-deploy pulls within 30s and syncs to `/var/www/games/`
3. Your page is live at `http://159.223.127.125/games/<your-game>/`
4. No SSH access needed. No manual steps.

**Step-by-step commands (from any branch):**
```bash
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
# Wait ~30 seconds, then verify:
#    http://159.223.127.125/games/<your-game>/
```

**Important:** You MUST push to `main`, not your feature branch. The auto-deploy only watches `main` for static files.

### Adding a New Project
1. Create a new directory: `/opt/<project>/` on the droplet
2. Add a new `location /<ProjectName>/` block in `deploy/update_nginx.sh`
3. Bump the version number in `deploy/NGINX_VERSION` to trigger nginx reload
4. Add a link card to `deploy/landing.html`
5. Set up its own auto-deploy script if needed

### Server Architecture
- When sharing the droplet across projects, use separate nginx routes, databases, and environment configs.
