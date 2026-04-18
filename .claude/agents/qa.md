## name: qa
description: QA runs automatically via GitHub Actions Playwright on every push to main. The Orchestrator reads results from the Actions run. This agent definition documents the QA process — it does not run from the sandbox.
tools: Read, Glob, Grep

QA is automated. Every push to `main` triggers `.github/workflows/qa.yml` which runs Playwright tests against the live site at http://159.223.127.125.

The sandbox cannot reach the droplet directly. All live-site testing happens on GitHub Actions infrastructure.

**Orchestrator's QA responsibilities:**
1. After pushing to main, check the GitHub Actions run for test results
2. Read pass/fail status, failure details, and screenshots (uploaded as artifacts)
3. If tests fail: provide Builder with full context (which tests failed, error messages, screenshots)
4. Builder fixes → Orchestrator re-pushes → GitHub Actions re-tests automatically
5. Max 2 fix cycles, then rollback to pre-deploy tag and report to user

**What the tests cover (in `tests/qa-smoke.spec.ts`):**
- Page loads without JS errors
- Interactive elements work (buttons, forms, links)
- Data displays real values (no NaN, blanks, placeholders)
- Mobile viewport (390px) and desktop (1280px)
- Security (dotfiles, .env, .md return 404)
- Performance (pages load under 8s)
- Webhook health endpoint

**Builder writes the tests.** Every feature includes task-specific Playwright tests as part of the build deliverable.
