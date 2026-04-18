---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Lesson Promotion — the tier ladder for turning a LESSONS.md entry into something that can't happen again

## When to use

Every time you append a new entry to `LESSONS.md`, and every time `lessons-lint.sh` nags about a `doc_only` entry. Pick the right tier up front; re-evaluate when the same class recurs.

## The tier ladder

Stronger tiers sit earlier. Pick the strongest tier that actually fits the failure class; don't overshoot.

| Tier | Mechanism | What enforces it | Fails when |
|---|---|---|---|
| **code_assert** | A running script, systemd unit, cron, or wrapper refuses the bad shape | `helpers/*.sh`, systemd service, cron job | A caller tries the bad shape → gets an error or loud warning |
| **ci_gate** | A GitHub Actions job fails the build | `.github/workflows/*.yml` | PR merge blocked on red CI |
| **pre_commit** | A git pre-commit hook rejects the commit | `helpers/*.sh` wired via `.git/hooks/pre-commit` | Local commit aborted before it reaches main |
| **reviewer_rule** | A numbered rule in an agent brief that the reviewer MUST check | `.claude/agents/*.md` | Reviewer returns FAIL in its structured output |
| **doc_only** | A `LESSONS.md` entry with preventive rules in prose; no automation | nothing — human recall | Nothing mechanical fails; we hope the next agent reads LESSONS |
| **doc_only_accepted** | Same as doc_only but explicitly signed off as "rare but worth remembering" | nothing | (Intentional long-tail — see below) |

**Promotion direction: right → left.** Every time the lint nags a `doc_only` entry, ask "can this move one tier left?" Usually yes; sometimes no.

## `doc_only_accepted` — the long-tail escape hatch

Some lessons are load-bearing precisely **because** they are rare. Examples:

- `patchright evaluate() runs in an isolated world` — bites exactly one project, exactly one time per debugging-session that gets confused by it. Building a CI gate is absurd overhead.
- `zram missing from stock DigitalOcean Ubuntu kernel` — fires once per new-droplet bring-up; no automation shape fits.
- `Overpass attic queries silently return 0 for bbox+tag` — external-API surprise we never expect to hit again for this query shape.

These don't belong in `doc_only` (the linter would nag forever) and they can't honestly be promoted — nothing to enforce, by construction. `doc_only_accepted` says: **"we read this, agreed it's rare, chose not to build tooling, and accept the residual risk."** The nag silences permanently.

**Rarity is a feature.** Don't retire an entry because it hasn't fired in months. Don't retire it because it looks niche. A single lesson that saves one future debugging session has already paid for the line it occupies. The rule is:

- **Retire on obsolescence** (the underlying tool/service is gone), not on frequency or dormancy.
- **Never auto-delete.** Deletion is a human-in-the-loop decision, not a lint action.

## Picking the right tier

Questions to ask, in order:

1. **Can I write a script that refuses the bad shape with zero false positives?** → `code_assert`. (Paid-call wrapper, dev-python-guard, start-task worktree isolation.)
2. **Can CI detect this in the diff reliably?** → `ci_gate`. (Type-check, lint, migration-safety check.)
3. **Is it detectable in `git diff --cached` with a grep or AST walk?** → `pre_commit`. (doc-reality-check, lessons-lint, skills-shape-lint itself.)
4. **Does it need human judgment on context the diff alone can't carry?** → `reviewer_rule`. (Test-completeness, state-drift in snapshot docs, bot-fingerprint QA coverage.)
5. **Is it domain lore — a quirk of an external tool, a provisioning oddity, a "gotcha" nobody will remember in six months?** → `doc_only_accepted`.
6. **Otherwise: `doc_only`.** And the lint will nag you in 14 days to promote or accept.

## Anti-patterns

- **Promoting to `code_assert` without an actual helper.** The frontmatter `enforcer_path:` must point at a real file. Fiction is worse than `doc_only`.
- **Leaving `doc_only` forever because "the failure is rare."** Rare + intentionally-accepted → `doc_only_accepted`. Rare + "I'll get to it" → the lint's job is to nag.
- **Reviewer rule without a numbered line in the agent brief.** `reviewer_rule` means the reviewer's output will cite rule #N. If no such rule exists, it's `doc_only`.
- **Demoting on frequency.** Never. See above.

## Related
- `SKILLS/platform-stewardship.md` — where different kinds of learning belong.
- `SKILLS/root-cause-analysis.md` — every incident ends with a LESSONS entry + a preventive fix.
- `helpers/lessons-lint.sh` — the pre-commit hook that enforces the frontmatter schema.
- `SKILLS/doc-frontmatter.md` — the broader doc-frontmatter schema this tier ladder lives inside.
