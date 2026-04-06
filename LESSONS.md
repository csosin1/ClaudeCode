# Lessons Learned

## 2026-04-05 Agent Harness Setup
- **What went wrong:** Attempted SSH to configure nginx and observability on the droplet. SSH and direct HTTP are blocked from the Claude Code sandbox. Wasted time creating a standalone setup script before realizing the auto-deploy pipeline could do it.
- **Root cause:** CLAUDE.md didn't state that SSH is unavailable.
- **What to do differently:** All server-side changes go through `deploy/auto_deploy_general.sh` or `deploy/update_nginx.sh`. Never attempt SSH, scp, or create "run this on the server" scripts.

## 2026-04-05 Sandbox Network Proxy
- **What went wrong:** Tried multiple approaches to reach the droplet from the sandbox — direct HTTP, SSH, Cloudflare tunnels, Playwright MCP browser. All blocked by the envoy proxy which only allows package registries, GitHub, and Anthropic domains.
- **Root cause:** The sandbox has a network proxy with a strict domain allowlist. No workaround exists from within the sandbox.
- **What to do differently:** Never try to reach external hosts (SEC EDGAR, financial APIs, the droplet IP) from the sandbox. Code that downloads external data must run on the droplet. Live-site testing runs via GitHub Actions, not from the sandbox.

## 2026-04-05 iPhone 13 Device Profile Broke Playwright Tests
- **What went wrong:** Playwright config used `devices['iPhone 13']` for mobile testing. This sets `isMobile: true` which changes browser request headers and behavior. All mobile tests failed (8/16).
- **Root cause:** `isMobile: true` causes the browser to send mobile-specific request headers that some servers handle differently.
- **What to do differently:** Use plain viewport dimensions (`{ width: 390, height: 844 }`) instead of device emulation profiles. This tests the responsive layout without changing request behavior.

## 2026-04-05 QA Polling Burns Tokens
- **What went wrong:** Orchestrator polled GitHub Actions results via WebFetch in a loop. The WebFetch cache returned stale "in progress" results for ~6 minutes. Multiple fetch+sleep cycles burned context window for no progress.
- **Root cause:** WebFetch has a 15-minute cache, so repeated requests to the same URL return stale data.
- **What to do differently:** After pushing to main, wait at least 90 seconds before checking once. If still in progress, wait another 90 seconds. If a third check still shows in progress, add a cache-busting query parameter to the URL. Don't poll more than 3 times.

## 2026-04-06 Deploy Script Blocking: Heavy Setup Before Static Sync
- **What went wrong:** The one-time car-offers setup (apt-get, npm install, Playwright install) was placed at the TOP of auto_deploy_general.sh, BEFORE `git fetch` and static file sync. This blocked ALL deploys for 5+ minutes while system packages installed. Landing page, carvana hub, and games couldn't update.
- **Root cause:** Treated one-time setup as a prerequisite that had to run first. Didn't realize it would block the fast static sync that other projects depend on.
- **What to do differently:** Always put fast static file sync (landing page, games, hubs) FIRST in the deploy script. Heavy one-time setup and npm install go AFTER static files are deployed. Deploy must complete the fast path in 2-3 seconds regardless of what heavy setup is pending.

## 2026-04-06 Skipped QA and Rollback Tag
- **What went wrong:** Pushed to main without creating a rollback tag first. Didn't have Builder write QA tests. Didn't check GitHub Actions after deploy. User had to report the 502.
- **Root cause:** Rushed to show results, skipped the CLAUDE.md workflow (tag → deploy → QA → verify).
- **What to do differently:** ALWAYS: (1) create rollback tag before deploy, (2) Builder must write Playwright tests as part of every build, (3) check GitHub Actions QA results after every push to main, (4) never tell the user "it should work" — verify with QA first.

## 2026-04-06 Lazy-Load Heavy Dependencies in Express Servers
- **What went wrong:** server.js did `require('./lib/carvana')` at the top level, which loads playwright-extra. If npm install hasn't completed on the droplet, Node crashes on startup and PM2 loops forever. The Express server never comes up.
- **Root cause:** Eager loading of a module that depends on Playwright, which may not be installed yet during first deploy.
- **What to do differently:** Lazy-load heavy dependencies (Playwright, Puppeteer, etc.) inside the route handler that uses them, not at module load time. Return a 503 with a clear message if deps aren't ready yet.

## 2026-04-06 Node.js Not in PATH on Droplet
- **What went wrong:** Deploy script used bare `node`, `npm`, `npx` commands. On the droplet, Node.js was not installed in the default PATH. All npm install commands silently failed ("command not found") but the `.npm_installed` flag was still set. The systemd service used `/usr/bin/node` which didn't exist. Express server never started → persistent 502 for hours.
- **Root cause:** Node.js wasn't installed on the droplet at all until the deploy script installed it via nodesource. The script assumed `node` was available.
- **What to do differently:** Never assume runtime binaries are in PATH on the droplet. Always discover the binary path first (check /usr/local/bin, /usr/bin, nvm paths, `command -v`). Use absolute paths for systemd ExecStart. Only set success flags AFTER verifying the operation actually worked (e.g., check `node_modules/express` exists after npm install). Add a nodesource fallback installer.

## 2026-04-06 WebFetch QA Results Are Unreliable
- **What went wrong:** WebFetch reported QA runs as "passed" when they were actually failing. Made multiple decisions based on false positive results. User reported receiving failure emails while I was reporting success.
- **Root cause:** WebFetch has a 15-minute cache and returns stale/incorrect data. GitHub Actions pages require authentication to view full details, so WebFetch gets limited/wrong information.
- **What to do differently:** Never trust WebFetch for QA results. Use the diagnostics-to-issue-comment pipeline instead: QA workflow fetches debug.json and posts server state to GitHub issue #3, which can be read via authenticated MCP tools. This is the only reliable way to get server diagnostics from the sandbox.

## 2026-04-06 Deploy Script Self-Update Requires Two Deploys
- **What went wrong:** Updated the deploy script with Node.js discovery code, but the fix didn't take effect on the first deploy. The old script was already loaded in memory; it copies the new script to /opt/ (STEP 0) but continues running the old logic.
- **Root cause:** The self-update mechanism copies the new script for the NEXT run. The currently-executing bash process still has the old script in memory.
- **What to do differently:** After any critical deploy script fix, always push a second trivial commit to trigger a follow-up deploy that will execute the new script. The pattern is: push fix → deploys (copies new script) → push trigger → deploys (runs new script).
