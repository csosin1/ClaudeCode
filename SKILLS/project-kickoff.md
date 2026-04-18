---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Project Kickoff — one protocol, two paths, structured debate → template merge

## When to use

Any project work that would take >8 hours of build time to finish, OR any brand-new project regardless of scope. If scope is <8h on an existing project, skip this skill and use the existing Clarify-Before-Building path (`CLAUDE.md § Clarify Before Building`). User can override the threshold in either direction via `helpers/kickoff.sh --force` or by skipping outright.

The protocol exists to shrink the "wrong build done confidently" failure mode (the most expensive iPhone-user outcome) without turning every task into a ceremony. It dogfoods `SKILLS/four-agent-debate.md` — research runs first and alone; three peer agents run in parallel; orchestrator merges deterministically via template, no fifth LLM call.

## Shape (one protocol, `--scope` internal branch)

1. **Step 0 — scaffold (new-project only; no-op for existing).** Fires in parallel with Step 1 via `SKILLS/new-project-checklist.md`.
2. **Step 1 — Research agent runs FIRST, alone.** Fixed 7-question template baked into `helpers/kickoff.sh`, plus up to 2 orchestrator-injected project-specific slots (Q8/Q9). **Hard cap at 9 questions.** For existing-project scope, Research is auto-replaced with `read_project_context()` that reads `/opt/<project>/PROJECT_CONTEXT.md` + last 50 `git log --oneline` + LESSONS tagged to this project + `tests/<project>.spec.ts`.
3. **Step 2 — three peer agents IN PARALLEL.** Each writes structured YAML (schemas below), not free text. Peers do NOT read each other's output mid-run (per `SKILLS/four-agent-debate.md` asymmetry rules).
   - Understand-the-ask
   - Challenge-the-approach
   - Improver / risks (pivots to **regressions-risk mode** for existing-project scope; reads actual source, not just PROJECT_CONTEXT)
4. **Step 3 — DETERMINISTIC TEMPLATE MERGE.** No Synthesize LLM call. `kickoff.sh` renders the Accept card from the 3 structured outputs using a fixed template with three slots, preserving provenance line-by-line.
5. **Step 4 — Accept card surfaces via `helpers/accept-card.sh` at milestone tier.** Full `KICKOFF_REPORT.md` persisted to `/opt/<project>/KICKOFF_REPORT.md` **BEFORE** the Accept card fires, so a returning dormant user re-reads cold without LLM replay.

## The 7 fixed research questions (baked into `kickoff.sh`)

1. **Comparable products** — 3 best-in-class tools in this category, one sentence each, link each.
2. **User complaints** — top 3 recurring complaints across App Store / G2 / HN / Reddit reviews. Cite.
3. **Fastest-shipped MVP path** — 2-week rebuild: minimum surface, what was cut.
4. **Anti-pattern graveyard** — similar products that shut down / pivoted, publicly-known reason.
5. **Standards / regulations** — GDPR / HIPAA / COPPA / PCI / accessibility — which apply, one-line each.
6. **Managed-service shortcuts** — is there a Stripe/Clerk/Supabase-shaped service that collapses 40% of the build?
7. **Unknown unknowns** — one paragraph: what would a domain expert know that research doesn't? Surface as user-question.

Q8/Q9 reserved for orchestrator-injected project-specific questions. Hard cap 9.

## Structured schemas — the three peers MUST emit these

**Understand-the-ask output:**

```yaml
title: string <60 chars
outcome: string, 1 sentence, user-facing
in_scope: [bullets, max 10]
non_goals: [bullets, max 10]   # empty list is a smell — challenge it
success_criteria: [bullets, each MEASURABLE]
user_journey:
  entry_url: string
  steps: [ordered list of user-visible actions]
  done_state: string
file_locations:
  new_files: [absolute paths, no speculation]
  modified_files: [absolute paths]
sizing:
  hours_low: int
  hours_high: int
  confidence: low|medium|high
open_questions:
  - question: string
    why_it_matters: string
    default_if_no_answer: string   # LOAD-BEARING: user silence ships
```

**Challenge-the-approach output:**

```yaml
alternatives:
  - rank: 1
    alternative: string
    what_it_collapses: string
    swap_if: string
    keep_current_if: string
  # max 5 alternatives
verdict: SHIP_AS_SPECCED | REDIRECT_TO_#N | HYBRID: use #N for <part>, build rest
rationale: string, 2-4 sentences
```

**Improver/risks output:**

```yaml
risks:
  blocking:   # must resolve before build starts
    - {risk, mitigation, cost_to_fix_hours}
  shipping:   # known risks we ship with
    - {risk, monitor_how, when_to_revisit}
  watch:      # low-probability tail risks, note only
    - string
improvements:
  quick_wins:   # <2h, default IN unless user declines
    - {change, why, added_hours}
  stretch:      # 2-8h, default OUT, Accept-card checkbox
    - {change, why, added_hours}
  future:       # >8h, auto-file to PROJECT_STATE backlog
    - {change, why, rough_hours}
```

## Accept card (rendered by `helpers/accept-card.sh`)

```
Title / Outcome (1 sentence)
Estimate: X-Y hours
  # if outside spend required: "requires outside spend: ~$X, approve cap: $Y"
  # otherwise: "no outside spend required"
Risks accepted (top 3)
Stretch improvements [ ] [ ] [ ]
Open questions (if any; else just tap Accept)
[ Accept ]  [ Refine ]  [ Cancel ]
```

Below the card (collapsed by default, expandable): the full `KICKOFF_REPORT.md`.

**No token cost displayed anywhere. Ever.** Per `feedback_cost_model.md` and `SKILLS/walkaway-invariants.md` invariant #6.

## `KICKOFF_REPORT.md` structure (written to `/opt/<project>/KICKOFF_REPORT.md`)

```markdown
---
kind: episodic
last_verified: <ISO>
refresh_cadence: on_touch
sunset: null    # immutable after Accept; re-kickoff creates a new numbered report
---

# Kickoff Report — <project> — <ISO date>

## Accept Card (top, always current)
<rendered card text>

## Synthesized Spec (from Understand)
<YAML block>

## Alternatives Considered (from Challenge)
<table + verdict>

## Risks & Improvements (from Improver)
<YAML tiers>

## Research Report (from Research)
<Q1-Q9 answers>

## Committee Metadata
- agents: research, understand, challenge, improver
- wall_clock_minutes: int
- tokens_total: int     # logged but NOT surfaced in Accept card
- outside_spend_estimate: $X OR "none"
- model_versions: {...}
```

## Multi-month projects — iterative re-kickoff

For scopes where `sizing.hours_high` corresponds to >4 calendar weeks of work, `kickoff.sh` schedules re-kickoff triggers at 25% / 50% / 75% milestones (Shape Up iterative shaping). Milestones are marked in `PROJECT_STATE.md § Milestones`; when one is crossed, orchestrator fires a slim-kickoff on remaining scope. Log the trigger in `SKILLS/kickoff-retros.md`.

## Content-triggered staleness (walk-away safe)

If user taps Accept >24h after kickoff completes AND PROJECT_CONTEXT / LESSONS / target-branch HEAD has changed since kickoff wrote, `kickoff.sh accept` re-fires the Challenge agent only (fast, single call) against latest state. If Challenge returns the same verdict, accept proceeds. If verdict flipped, surface a staleness-flag card: "Since this kickoff was written, <summary>. Refresh the kickoff, or Accept anyway."

**Never calendar-triggered.** Per `user_usage_pattern.md` (bursty with long dormancy) and `feedback_walkaway_default.md`, a cold kickoff that has not churned is still valid. Only content churn can invalidate.

## Effectiveness loop — `helpers/kickoff-retro.sh`

**Content-triggered, NEVER calendar.** Hook into existing post-deploy-qa-hook OR the project's `end-task.sh`: on QA-green + user-accepts-live, run:

1. Read `KICKOFF_REPORT.md § Synthesized Spec`.
2. Walk the project's current state (`git log --since <kickoff-date>`, `git diff <kickoff-commit>..HEAD`, current `PROJECT_STATE.md`, LESSONS entries since kickoff).
3. Emit spec-vs-reality deltas: (a) non-goals that became in-scope; (b) in-scope that got cut; (c) new LESSONS born during build; (d) `hours_low..hours_high` vs actual.
4. Append to `SKILLS/kickoff-retros.md` with a categorized root-cause tag (research-miss / user-mind-change / spec-ambiguity / platform-drift).
5. **NO ntfy. Silent log.** Future-session agents read `kickoff-retros.md` when writing new kickoffs.

## Usage

```
helpers/kickoff.sh --prompt "<user text>" --project <name> --scope {new|existing-big} [--force] [--dry-run]
helpers/kickoff-retro.sh --project <name> [--since <ISO>]
```

`--dry-run` exits cleanly without dispatching real agents, prints what WOULD be dispatched — use for smoketest.

## What NOT to do

- Do NOT add a 4th LLM Synthesize agent. Template merge only — determinism beats prose.
- Do NOT surface token cost in the Accept card. Only outside spend.
- Do NOT calendar-schedule anything in this protocol. Content-triggered or ship-event-triggered only.
- Do NOT build a 2-mode bifurcation into separate docs. One `SKILLS/project-kickoff.md`, one `kickoff.sh`, internal branching on `--scope`.
- Do NOT add a reviewer rule enforcing "kickoff was run" — this protocol is a helper, not a gate.
- Do NOT let the three peer agents see each other's output mid-run — groupthink bug, see `SKILLS/four-agent-debate.md`.

## Related

- `SKILLS/four-agent-debate.md` — the committee pattern this protocol dispatches.
- `SKILLS/new-project-checklist.md` — Step 0 scaffold fires from here for new projects.
- `SKILLS/walkaway-invariants.md` — Accept card conventions, notification tiers, outside-spend framing.
- `SKILLS/irreversible-actions.md` — HITL rules for outside-spend caps declared at kickoff.
- `SKILLS/kickoff-retros.md` — accumulated spec-vs-reality deltas consulted when writing new kickoffs.
- `helpers/accept-card.sh` — the emitter this protocol calls at milestone tier.
- `helpers/kickoff.sh` / `helpers/kickoff-retro.sh` — the implementations.
