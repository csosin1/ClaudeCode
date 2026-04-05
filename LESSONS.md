# Lessons Learned

## 2026-04-05 Agent Harness Setup
- **What went wrong:** Attempted SSH to configure nginx and observability on the droplet. SSH and direct HTTP are blocked from the Claude Code sandbox. Wasted time creating a standalone setup script before realizing the auto-deploy pipeline could do it.
- **Root cause:** CLAUDE.md didn't state that SSH is unavailable.
- **What to do differently:** All server-side changes go through `deploy/auto_deploy_general.sh` or `deploy/update_nginx.sh`. Never attempt SSH, scp, or create "run this on the server" scripts.
