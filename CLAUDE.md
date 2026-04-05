# Project Rules

## Philosophy

The user prompts from an iPhone. Claude does everything — writes code, deploys it, fixes problems. The user taps a link and sees the result in a mobile browser. No desktop. No terminal. No third-party apps. Every project lives on the droplet at `http://159.223.127.125/` and is reachable in one tap from the landing page.

## Be Fully Autonomous

- Do everything yourself. Never ask the user to run commands, check URLs, load files, or do anything in a terminal.
- If something fails — a deploy, a test, a build — diagnose and fix it. Don't present the error and ask what to do.
- If a fix doesn't work, try another approach. Only escalate to the user after multiple genuine attempts.
- Never say "try running X" — just run it. Never say "it should work now" — verify it does, then share the link.
- Handle git, deploys, nginx config, file permissions, all of it without user intervention.

## Verify Before Sharing

- After deploying, confirm the output is live and correct before sharing a link.
- Run syntax checks, tests, and validation before declaring a task done.
- If a deploy is slow or stuck, diagnose it — don't just wait silently.

## Mobile-First Output

- All web output must be usable on a phone screen. Use responsive design — no desktop-only layouts.
- When sharing URLs, use plain clickable links. Never wrap in bold, backticks, or formatting that breaks tap-to-open.

## Code Quality

- Don't add features beyond what was asked.
- Fix root causes, not symptoms.

## Git Workflow

- Commit and push all changes before stopping (enforced by stop hook).
- Use descriptive commit messages explaining why, not just what.
- Never force-push or amend published commits without explicit permission.
- Don't create PRs unless explicitly asked.

## How Projects Go Live

**Droplet IP:** 159.223.127.125

Every project deploys to the droplet and gets its own URL. The landing page at `/` links to all projects — it's the user's home screen for everything Claude builds.

### Project Isolation (CRITICAL)

- Each project gets its own directory, nginx route, and deploy script.
- Never write files outside your project's directory.
- Deploying one project must never break another. After changing shared config (nginx, landing page), verify existing projects still work.
- New projects get their own `/opt/<project>/` directory.

### New Project Placement

When the user asks to create a new program or project, ask where it should live in the file architecture before writing any code — unless they've already specified. Choices include `games/<name>/` for static pages, `/opt/<project>/` for backend services, or another location of their choosing.

### Putting a New Project Online

1. Create its directory on the droplet: `/opt/<project>/`
2. Add a `location /<project>/` block in `deploy/update_nginx.sh`
3. Bump `deploy/NGINX_VERSION` to trigger an nginx reload
4. Add a link card to `deploy/landing.html` so the user can find it from `/`
5. Set up its own auto-deploy script if needed

### Static File Deploys (Games, Simple Pages)

Push files to `games/<name>/index.html` on the `main` branch. The general auto-deploy syncs to `/var/www/games/` within 30 seconds. Live at `http://159.223.127.125/games/<name>/`.

You MUST push to `main` for static deploys — the auto-deploy only watches `main`.

### Auto-Deploy System

- **Watches:** `main` branch
- **Repo clone:** `/opt/site-deploy/`
- **Timer:** `general-deploy.timer`
- **Log:** `/var/log/general-deploy.log`
- **Actions:** syncs `games/` → `/var/www/games/`, copies `deploy/landing.html` → `/var/www/landing/index.html`, reloads nginx if `deploy/NGINX_VERSION` changed
