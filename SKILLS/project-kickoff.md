---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Project Kickoff — iterative refinement loop with the user, not a one-shot report

## When to use

Any project work that would take >8 hours of build time to finish, OR any brand-new project regardless of scope. If scope is <8h on an existing project, skip this skill and use the existing Clarify-Before-Building path (`CLAUDE.md § Clarify Before Building`). User can override the threshold in either direction via `helpers/kickoff.sh --force` or by skipping outright.

The protocol exists to shrink the "wrong build done confidently" failure mode (the most expensive iPhone-user outcome). It treats the committee as a **sparring partner the user iterates against**, not a report-delivery pipeline. A non-technical iPhone prompt arrives with a 30-50% spec; the missing 50% lives in the user's head and only comes out through Q&A, pushback, and sharpening against disagreement.

It dogfoods `SKILLS/four-agent-debate.md`: research runs first and alone; three peer agents run in parallel; orchestrator merges deterministically via template. **No fifth LLM synthesis call.** Disagreements between peers are surfaced explicitly in a Draft Plan card that the user iterates against until they tap Finalize.

## Shape (one protocol, `--scope` internal branch, refinement loop on top)

1. **Step 0 — scaffold (new-project only; no-op for existing).** Fires in parallel with Step 1 via `SKILLS/new-project-checklist.md`.
2. **Step 1 — Research agent runs FIRST, alone.** Fixed 7-question template baked into `helpers/kickoff.sh`, plus up to 2 orchestrator-injected project-specific slots (Q8/Q9). **Hard cap at 9 questions.** For existing-project scope, Research is auto-replaced with `read_project_context()` that reads `/opt/<project>/PROJECT_CONTEXT.md` + last 50 `git log --oneline` + LESSONS tagged to this project + `tests/<project>.spec.ts`.
3. **Step 2 — three peer agents IN PARALLEL.** Each writes structured YAML (schemas below), not free text. Peers do NOT read each other's output mid-run (per `SKILLS/four-agent-debate.md` asymmetry rules). Each MUST emit a `disagreements_with_others` block (may be empty only if the peer genuinely concurs).
   - Understand-the-ask
   - Challenge-the-approach
   - Improver / risks (pivots to **regressions-risk mode** for existing-project scope; reads actual source, not just PROJECT_CONTEXT)
4. **Step 3 — DETERMINISTIC TEMPLATE MERGE.** No Synthesize LLM call. `kickoff.sh` renders the **Draft Plan card** from the 3 structured outputs using a fixed template, preserving provenance line-by-line AND surfacing every disagreement entry as a first-class Draft-Plan element.
5. **Step 4 — Draft Plan card fires** via `helpers/accept-card.sh --kind draft-plan` at milestone tier. Full `KICKOFF_REPORT.md` persisted to `/opt/<project>/KICKOFF_REPORT.md` **BEFORE** the card fires.
6. **Step 5 — refinement loop.** User taps Ask / Push back / Add constraint / Answer. Orchestrator routes targeted re-runs (not full re-dispatch). Each round re-renders a fresh Draft Plan card at `kickoff-<project>-r<N>.html` and appends a Round History entry. Loop ends **only** when user taps Finalize (terminal) or Cancel.

**No round cap, no timer.** The committee exists to serve the user's confidence, not burn a fixed budget. See `feedback_committee_collaborative.md`.

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

All three peers now emit a mandatory `disagreements_with_others` block. Silent merge is the anti-pattern — see `feedback_committee_collaborative.md` and `SKILLS/four-agent-debate.md § Disagreements must be user-visible`.

```yaml
disagreements_with_others:
  - other_agent: understand | challenge | improver
    my_position: string
    their_position: string
    tradeoff: string
    my_recommendation: keep_mine | defer_to_them | hybrid
    rationale: string
```

An **empty list is legitimate ONLY when the agents genuinely concur**. A peer that claims zero disagreements on a contested spec is a smell — orchestrator flags.

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
  - id: oq1
    question: string
    why_it_matters: string
    default_if_no_answer: string   # LOAD-BEARING: user silence ships this default
disagreements_with_others: [...]   # schema above
```

**Challenge-the-approach output:**

```yaml
alternatives:
  - id: alt1
    rank: 1
    alternative: string
    what_it_collapses: string
    swap_if: string
    keep_current_if: string
  # max 5 alternatives
verdict: SHIP_AS_SPECCED | REDIRECT_TO_#N | HYBRID: use #N for <part>, build rest
rationale: string, 2-4 sentences
disagreements_with_others: [...]
```

**Improver/risks output:**

```yaml
risks:
  blocking:   # must resolve before build starts
    - {id, risk, mitigation, cost_to_fix_hours}
  shipping:   # known risks we ship with
    - {id, risk, monitor_how, when_to_revisit}
  watch:      # low-probability tail risks, note only
    - string
improvements:
  quick_wins:   # <2h, default IN unless user declines
    - {id, change, why, added_hours}
  stretch:      # 2-8h, default OUT, Accept-card checkbox
    - {id, change, why, added_hours}
  future:       # >8h, auto-file to PROJECT_STATE backlog
    - {id, change, why, rough_hours}
disagreements_with_others: [...]
```

## User interaction during refinement

Every action below is a single `helpers/kickoff.sh <subcommand>` call. The orchestrator does NOT full-re-dispatch the committee on each interaction — targeted routing is the point. Each action appends one entry to `KICKOFF_REPORT.md § Round History` and re-renders a fresh Draft Plan card at a new round-numbered URL.

- **Ask** — `kickoff.sh ask --project X --agent <name> --question "..."`
  Single-agent Q&A. One LLM call to that peer's archetype with its prior output as context. Response written inline on the next Draft Plan card under `Answers-to-direct-questions`. No merge re-run required.

- **Push back** — `kickoff.sh pushback --project X --on <disagreement-id|suggestion-id> --text "..."`
  Single-agent reconsider on a specific disagreement entry or suggestion. That one peer re-runs with user text + its prior YAML + the contested item highlighted. Deterministic merge re-runs with the updated YAML; the other two peers' YAML is untouched.

- **Add constraint** — `kickoff.sh constrain --project X --text "..."`
  All three peer agents re-run in parallel with the new constraint injected as a preamble to their briefs. Research output is reused as-is (not re-run). Merge then re-renders.

- **Answer open question** — `kickoff.sh answer --project X --question <oq-id> --text "..."`
  Updates Understand's `default_if_no_answer` for that open question to the user's text (promoted from default → answered). Merge re-runs over the updated Understand YAML; the other two peers are untouched.

- **Finalize** — `kickoff.sh finalize --project X`
  **Terminal.** Stamps `status: finalized` into KICKOFF_REPORT frontmatter, seeds `PROJECT_STATE.md` + `PROJECT_CONTEXT.md` from the finalized spec, dispatches the first builder, fires a milestone-tier ntfy. No further refinement accepted on this kickoff; re-kickoff creates a new numbered report.

- **Cancel** — `kickoff.sh cancel --project X`
  Scaffold rollback (Step 0 side-effects, if any) + moves `KICKOFF_REPORT.md` to `/opt/site-deploy/graveyard/kickoff-<project>-<ts>.md`. Silent; no ntfy.

`kickoff.sh refine --project X` is a manual "re-render Draft Plan card from current state" — no re-dispatch, just re-rendering after e.g. a manual YAML edit.

`kickoff.sh accept` is preserved as a **backward-compat shim** that calls `finalize` with a `via_shim=true` log entry. New callers should use `finalize`.

## Draft Plan card (rendered by `helpers/accept-card.sh --kind draft-plan`)

```
Round <N> — <project>
Title / Outcome
Current merged spec:
  scope / non-goals / success criteria
DISAGREEMENTS (one row per entry)
  [Understand] assumes X  ←→  [Challenge] recommends Y
    tradeoff: Z
    [Override — keep X]   [Discuss — push back]
OPEN QUESTIONS (one row per unanswered)
  Q: <question>
  default-if-no-answer: <text>
  [Answer]
REFINE ACTIONS
  [Ask] [Push back] [Add constraint]
TERMINAL
  [ Finalize ]   [ Cancel ]
```

Output path: `/var/www/landing/accept-cards/kickoff-<project>-r<N>.html` (one per round; Round History links them).

**No token cost displayed anywhere. Ever.** Per `feedback_cost_model.md`. Outside-spend estimate surfaces only when expected spend >$0.

## `KICKOFF_REPORT.md` structure (written to `/opt/<project>/KICKOFF_REPORT.md`)

```markdown
---
kind: episodic
last_verified: <ISO>
refresh_cadence: on_touch
sunset: null
status: draft | finalized    # set to 'finalized' by kickoff.sh finalize
---

# Kickoff Report — <project> — <ISO date>

## Draft Plan (top, always current)
<rendered card text of latest round>

## Round History
- r1 <ISO> initial committee dispatch — (link)
- r2 <ISO> user pushback on <disagreement-id> (challenge re-ran) — (link)
- r3 <ISO> user added constraint "<first 40 chars>" (all 3 peers re-ran) — (link)
- ...

## Synthesized Spec (from Understand, latest YAML)
<YAML block>

## Alternatives Considered (from Challenge, latest YAML)
<table + verdict>

## Risks & Improvements (from Improver, latest YAML)
<YAML tiers>

## Research Report (from Research, immutable after Step 1)
<Q1-Q9 answers>

## Committee Metadata
- agents: research, understand, challenge, improver
- rounds: int
- wall_clock_iso_first: <ISO>
- wall_clock_iso_latest: <ISO>
- outside_spend_estimate: $X OR "none"
- model_versions: {...}
```

Round History entry format (appended by each refine action):

```
- r<N> <ISO> <action> [agents: <which-re-ran>] <1-line summary>
```

## Multi-month projects — iterative re-kickoff

For scopes where `sizing.hours_high` corresponds to >4 calendar weeks of work, `kickoff.sh` schedules re-kickoff triggers at 25% / 50% / 75% milestones (Shape Up iterative shaping). Milestones are marked in `PROJECT_STATE.md § Milestones`; when one is crossed, orchestrator fires a slim-kickoff on remaining scope. Log the trigger in `SKILLS/kickoff-retros.md`.

## Content-triggered staleness (walk-away safe)

If user taps Finalize >24h after the latest round AND PROJECT_CONTEXT / LESSONS / target-branch HEAD has changed since then, `kickoff.sh finalize` re-fires the Challenge agent only (fast, single call) against latest state. If Challenge returns the same verdict, finalize proceeds. If verdict flipped, surface a staleness-flag card: "Since the latest round, <summary>. Re-open refinement or Finalize anyway."

**Never calendar-triggered.** Per `user_usage_pattern.md` (bursty with long dormancy) and `feedback_walkaway_default.md`, a cold draft that has not churned is still valid. Only content churn can invalidate.

## Effectiveness loop — `helpers/kickoff-retro.sh`

**Content-triggered, NEVER calendar.** Hook into existing post-deploy-qa-hook OR the project's `end-task.sh`: on QA-green + user-accepts-live, run:

1. Read `KICKOFF_REPORT.md § Synthesized Spec` (the finalized version).
2. Walk the project's current state (`git log --since <kickoff-date>`, `git diff <kickoff-commit>..HEAD`, current `PROJECT_STATE.md`, LESSONS entries since kickoff).
3. Emit spec-vs-reality deltas: (a) non-goals that became in-scope; (b) in-scope that got cut; (c) new LESSONS born during build; (d) `hours_low..hours_high` vs actual; (e) **disagreements that the user overrode in refinement that came back to bite**.
4. Append to `SKILLS/kickoff-retros.md` with a categorized root-cause tag (research-miss / user-mind-change / spec-ambiguity / platform-drift / refinement-override-regret).
5. **NO ntfy. Silent log.** Future-session agents read `kickoff-retros.md` when writing new kickoffs.

## Usage

```
helpers/kickoff.sh --prompt "<user text>" --project <name> --scope {new|existing-big} [--force] [--dry-run]
helpers/kickoff.sh ask       --project <name> --agent <understand|challenge|improver> --question "..."
helpers/kickoff.sh pushback  --project <name> --on <id> --text "..."
helpers/kickoff.sh constrain --project <name> --text "..."
helpers/kickoff.sh answer    --project <name> --question <oq-id> --text "..."
helpers/kickoff.sh refine    --project <name>
helpers/kickoff.sh finalize  --project <name>
helpers/kickoff.sh cancel    --project <name>
helpers/kickoff.sh accept    --project <name>          # deprecated shim → finalize
helpers/kickoff-retro.sh --project <name> [--since <ISO>]
```

`--dry-run` exits cleanly without dispatching real agents, prints what WOULD be dispatched — use for smoketest. `--dry-run` also works on subcommands (ask / pushback / constrain / answer) — prints routing plan without LLM calls.

## What NOT to do

- Do NOT add a 4th LLM Synthesize agent. Template merge only — determinism beats prose.
- Do NOT silently merge away disagreements. Surface every `disagreements_with_others` entry on the Draft Plan card. See `SKILLS/four-agent-debate.md § Disagreements must be user-visible`.
- Do NOT full-re-dispatch the committee on every user interaction. Targeted routing (ask → 1 agent, pushback → 1 agent, constrain → 3 peers, answer → Understand only) is the point.
- Do NOT cap rounds or set a calendar timer on refinement. Loop ends on Finalize / Cancel, nothing else.
- Do NOT surface token cost in any card. Only outside spend.
- Do NOT calendar-schedule anything in this protocol. Content-triggered or ship-event-triggered only.
- Do NOT build a 2-mode bifurcation into separate docs. One `SKILLS/project-kickoff.md`, one `kickoff.sh`, internal branching on `--scope`.
- Do NOT add a reviewer rule enforcing "kickoff was run" — this protocol is a helper, not a gate.
- Do NOT let the three peer agents see each other's output mid-run — groupthink bug, see `SKILLS/four-agent-debate.md`.

## End-to-end wiring (phone → committee → builder)

Entry point: tap **Start new project** on https://casinv.dev/ — leads to `/new-project.html` (source `deploy/new-project.html`). Form POSTs to `/cgi-bin/kickoff-start` (source `helpers/cgi-bin/kickoff-start`), which fires `helpers/kickoff.sh` in the background and redirects to `/kickoff-status.html?project=<slug>`. That page polls `/cgi-bin/kickoff-status` every 5s and redirects to the Draft Plan card when ready.

Draft Plan card action buttons (Ask / Push back / Add constraint / Answer / Override / Discuss / Finalize / Cancel) render as HTML forms POSTing to `/cgi-bin/kickoff-action` (source `helpers/cgi-bin/kickoff-action`). The CGI backgrounds the `kickoff.sh <subcommand>` call and redirects back to the status page polling for round N+1.

Nginx routes `/cgi-bin/` via `fastcgi_pass unix:/run/fcgiwrap.socket`. Set `KICKOFF_DRY_RUN=1` by appending `?dry_run=1` to any CGI URL — invocation is logged to `/tmp/kickoff-cgi-dryrun/` without dispatching real agents.

On `finalize`, `kickoff.sh` touches `/opt/<project>/.kickoff-state/BUILDER_READY`. The `kickoff-builder-watcher.path` systemd unit (source `helpers/kickoff-builder-watcher.path`) triggers `helpers/kickoff-builder-watcher.sh --once` which:
1. Moves the sentinel to `BUILDER_DISPATCHED` (race-free claim).
2. Reads the finalized `KICKOFF_REPORT.md § Synthesized Spec` + constraints.
3. Dispatches a Claude Code builder subagent via `claude -p <brief>` in the background.
4. Fires a milestone-tier ntfy with the project's preview URL as the click target.
5. Appends one JSONL line to `/var/log/kickoff-dispatches.jsonl` with fields: `ts, project, spec_sha, builder_agent_id, notify_tier, status`.

Onboarding a new project to the watcher: add a `PathModified=/opt/<slug>/.kickoff-state` line to `helpers/kickoff-builder-watcher.path` and `systemctl daemon-reload; systemctl restart kickoff-builder-watcher.path`.

## Related

- `SKILLS/four-agent-debate.md` — the committee pattern; see new section "Disagreements must be user-visible".
- `SKILLS/new-project-checklist.md` — Step 0 scaffold fires from here for new projects.
- `SKILLS/walkaway-invariants.md` — Draft Plan / Accept card conventions, notification tiers, outside-spend framing.
- `SKILLS/irreversible-actions.md` — HITL rules for outside-spend caps declared at finalize.
- `SKILLS/kickoff-retros.md` — accumulated spec-vs-reality deltas consulted when writing new kickoffs.
- `helpers/accept-card.sh` — emitter; supports `--kind draft-plan` for the refinement loop.
- `helpers/kickoff.sh` / `helpers/kickoff-retro.sh` — the implementations.
- `helpers/kickoff-builder-watcher.sh` / `.path` / `.service` — systemd-driven dispatch on finalize.
- `helpers/cgi-bin/kickoff-start` / `kickoff-action` / `kickoff-status` / `kickoff-projects` — phone-tap CGI front-end.
- `deploy/new-project.html` / `deploy/kickoff-status.html` — entry + status pages.
- `feedback_committee_collaborative.md` — principle driving the reshape (collaborative refinement, not report delivery).
