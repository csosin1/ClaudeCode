---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Doc Frontmatter — activity-gated freshness for durable platform docs

## When to use

Whenever you create or materially edit a `SKILLS/*.md`, `PROJECT_STATE.md`, `PROJECT_CONTEXT.md`, `RUNBOOK.md`, or any durable platform doc. The schema is prepended by `helpers/migrate-doc-frontmatter.sh` on first touch; on every subsequent edit, bump `last_verified` to today if the content was actually re-verified.

## The schema

```yaml
---
kind: skill | lesson | runbook | project_state | project_context
last_verified: YYYY-MM-DD
refresh_cadence: on_touch   # "on_touch" is the default — NOT a wall-clock trigger
sunset: null                # explicit date only if we know we'll retire it; null otherwise
---
```

Five fields, no more. Anything richer goes inside the doc, not in the header.

## Activity-gated freshness

**`refresh_cadence: on_touch` means "when someone edits this area, re-verify this doc as part of the change."** There is no background cron scanning `last_verified` against wall clock. A doc that sits untouched for six months during project dormancy is **not** stale.

The failure mode this avoids: calendar-gated freshness turns docs into a never-ending refresh treadmill that nobody actually reads. Agents either update `last_verified` without verifying (meaningless signal) or ignore the nag (lint blind). Neither is useful.

Activity-gated freshness makes the update load proportional to the area's churn. Hot areas self-refresh because humans touch them; cold areas stay cold, which is correct — their content is still accurate because the underlying system hasn't changed either.

## When to set `sunset`

Almost never. Reserve it for docs that describe a known-temporary state:

- A migration runbook for a migration with a planned completion date.
- A `SKILLS/residential-proxy.md` that assumes vendor X which we're already switching away from.
- A `SKILLS/provisional-*` doc flagged as pending an upstream capability.

If you set a `sunset`, name the trigger in the body of the doc (e.g., "retire when Phase 5 migration completes" or "retire when Anthropic publishes IP ranges"). A sunset with no trigger is a wish.

## `last_verified` — what "verified" means

When you touch a doc, `last_verified: <today>` should mean: **you read the doc and confirmed the statements it makes are still accurate as of today**. It does NOT mean "I edited one section and bumped the date as a formality." If the parts you didn't touch are stale, either re-verify them or leave the date alone.

The honest signal is more valuable than the fresh-looking signal.

## `kind` — what it's for

Distinguishes the doc's role for tooling and agents. Current consumers:

- `kind: skill` → indexed as a how-to pattern for `ls SKILLS/` discovery.
- `kind: lesson` → the inline `<!--lesson ... -->` block inside LESSONS.md uses a distinct schema (see `SKILLS/lesson-promotion.md`); the whole-file LESSONS.md header uses this top-level schema too.
- `kind: runbook` → human-executable procedures; read at incident-response time.
- `kind: project_state` → per-project live status; the thing `session-resilience.md` tells you to keep current every 30 min.
- `kind: project_context` → per-project situational context for specialized agents; see `SKILLS/project-context.md`.

Future consumers: dashboards, doc-search tools, context-assembly agents. Keep the set small and add new kinds only when a consumer actually needs the distinction.

## Related
- `SKILLS/lesson-promotion.md` — tier ladder for LESSONS.md entry frontmatter (sibling schema).
- `SKILLS/platform-stewardship.md` — where different kinds of learning belong.
- `helpers/migrate-doc-frontmatter.sh` — the one-shot migration helper.
