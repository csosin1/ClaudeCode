# Gym Intelligence — Project State

_Last updated: 2026-04-16 migration-prep by Gym Intelligence session (slug: gym-intelligence)_

## Current focus

**Idle — migration-prepped.** All work committed to origin, no background processes, no worktrees, no in-flight subagents. Ready for shutdown + rsync migration.

## Last decisions

- **Thesis writeup shipped on preview** (chapters 1–6, 11.6k words, inline SVG chart, PDF download). Live at `/gym-intelligence/preview/thesis`. Audit findings (F-001–F-010) documented in `AUDIT_FINDINGS.md`. Scope narrowed to honest investor-grade diagnosis + directional evidence from the clean subset (Germany +55.6pp excess clustering) + remediation plan.
- **16-quarter OHSOME backfill complete** (2022-Q2 through 2026-Q1, 0 failures). Time-series artifact at `writeup/data/clean-subset-timeseries.json`. Germany BF share 18.5% → 23.8% monotonic rise. Per-gym lat/lon not stored (aggregate counts only) — flagged in chapter 6 as a remediation item.
- **Wayback validation attempted, failed, not yet retried.** First Builder picked single-gym detail pages as locator URLs (97800% deltas); API 500'd mid-run. Correct locator URLs hardcoded for 19 chains; retry ready on user go. This is the critical-path blocker: determines whether OHSOME is usable for the rigorous hypothesis test or we fall back to Google Places + present-day-only.
- **Altafit ownership corrected** public → private on both DBs.
- **Live venv orphan purge shipped** (580MB → 30MB); deploy script self-cleans on future deploys.

## Open questions

- **Wayback validation: go/no-go from user.** Retry Builder with hardcoded URLs was rejected last attempt. Awaiting direction.
- **Promote thesis to live?** Currently preview-only. User hasn't said "ship it" on the writeup.
- **Migration: preview DB is the valuable one** (has OHSOME backfill + reclassification + ownership data that live DB lacks). Migration inventory flagged this at `helpers/migration-inventory-gym-intelligence.md`.

## Next step

After migration settles: retry Wayback validation with corrected locator URLs → produce accuracy metrics → user decides GREEN/YELLOW/RED → either run rigorous hypothesis test on OHSOME or fall back to Google Places + present-day spacing analysis.
