# Gym Intelligence — Project State

_Last updated: 2026-04-17 post-migration by Gym Intelligence session (slug: gym-intelligence)_

## Host topology (post-migration 2026-04-17)

- **Dev droplet** (this box, 4GB/2-core): code edits, git, auto-deploy to prod via webhook. `/opt/site-deploy/gym-intelligence/` is the source repo. DB files here are NOT mirrored to prod (excluded from rsync per commit 6e1c25d).
- **Prod droplet** (`ssh prod-private`, 10.116.0.3, 8GB/4-core): runtime. `/opt/gym-intelligence/` (live, port 8502) and `/opt/gym-intelligence-preview/` (preview, port 8503). All `*.db` files live here only. Heavy compute (OHSOME backfill, Wayback scraping, Playwright, classification runs) MUST run on prod via `ssh prod-private`.
- **Deploy path:** push to `main` on dev → webhook → per-project rsync to prod via `/etc/deploy-to-prod.conf` (general-deploy.timer disabled on prod per commit fb2450c). Code arrives; DBs do not travel.
- **Rule:** never write DBs on dev (goes nowhere). Never run heavy compute on dev (starves the 4GB box). Code + docs edits on dev are fine.

## Current focus

**Idle — migration complete.** All work committed to origin, no background processes, no worktrees, no in-flight subagents. Awaiting user direction on Wayback validation retry.

## Last decisions

- **Thesis writeup shipped on preview** (chapters 1–6, 11.6k words, inline SVG chart, PDF download). Live at `/gym-intelligence/preview/thesis`. Audit findings (F-001–F-010) documented in `AUDIT_FINDINGS.md`. Scope narrowed to honest investor-grade diagnosis + directional evidence from the clean subset (Germany +55.6pp excess clustering) + remediation plan.
- **16-quarter OHSOME backfill complete** (2022-Q2 through 2026-Q1, 0 failures). Time-series artifact at `writeup/data/clean-subset-timeseries.json`. Germany BF share 18.5% → 23.8% monotonic rise. Per-gym lat/lon not stored (aggregate counts only) — flagged in chapter 6 as a remediation item.
- **Wayback validation attempted, failed, not yet retried.** First Builder picked single-gym detail pages as locator URLs (97800% deltas); API 500'd mid-run. Correct locator URLs hardcoded for 19 chains; retry ready on user go. This is the critical-path blocker: determines whether OHSOME is usable for the rigorous hypothesis test or we fall back to Google Places + present-day-only.
- **Altafit ownership corrected** public → private on both DBs (prod).
- **Live venv orphan purge shipped** (580MB → 30MB); deploy script self-cleans on future deploys.

## Open questions

- **Wayback validation: go/no-go from user.** Retry Builder with hardcoded URLs was rejected last attempt. Awaiting direction. When retried, the Wayback scraping + LLM extraction MUST run on prod (`ssh prod-private`), not dev.
- **Promote thesis to live?** Currently preview-only. User hasn't said "ship it" on the writeup.
- **Verify prod has both DBs post-migration.** Preview DB (58MB, has OHSOME backfill) is the more valuable artifact; confirm it migrated.

## Next step

After user direction: retry Wayback validation (run on prod) with corrected locator URLs → produce accuracy metrics → user decides GREEN/YELLOW/RED → either run rigorous hypothesis test on OHSOME or fall back to Google Places + present-day spacing analysis.
