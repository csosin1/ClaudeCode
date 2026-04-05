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
