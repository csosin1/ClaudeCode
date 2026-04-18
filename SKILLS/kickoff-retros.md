---
kind: lesson
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Kickoff Retros — spec-vs-reality deltas (institutional memory)

## When to use

**Read** before writing a new kickoff brief (consulted by `helpers/kickoff.sh` and the Understand / Challenge / Improver peers) — the deltas named here are the patterns past projects got wrong. **Updated automatically** by `helpers/kickoff-retro.sh` on ship events (QA-green + user-accepts-live); do not hand-edit except to fix typos.

Entries accumulate newest-first. Each entry is terse — one spec / one reality / one root-cause tag.

## Root-cause tag glossary

- `research-miss` — the Research agent didn't surface the thing that bit us; Q1-Q9 needs tightening.
- `user-mind-change` — scope shifted because the user clarified late; not a research defect.
- `spec-ambiguity` — Understand YAML was ambiguous (e.g., vague success criteria); schema tightening needed.
- `platform-drift` — the platform (shared infra, SKILLS, LESSONS) changed during build; Step-4 staleness check would have caught it.

## Entries (newest first; `kickoff-retro.sh` prepends)

<!-- Seed entry (delete once real retros accumulate) -->

## 2026-04-18 — seed — protocol shipped, no real projects retro'd yet

- **Spec:** ship `SKILLS/project-kickoff.md` + `helpers/kickoff.sh` + `helpers/kickoff-retro.sh` in one shared-infra commit.
- **Reality:** shipped as specified; first real retro will overwrite this seed when a real project completes.
- **Root cause:** n/a (seed).
