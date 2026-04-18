---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Acceptance Rehearsal (journey-first)

## When to use

Any UI-touching ship that affects a user-facing feature. Runs after visual-reviewer passes, before the user's Accept gate.

Non-UI infra changes (cron tuning, nginx reloads, secret rotation, background-job refactors with no user-visible surface) are exempt. If in doubt, run it — the cost is ~$0.20 and 2 minutes.

## The journey-first framing

User journeys are **not QA tests**. They are the **shared-language artifact** that anchors everything this project does: spec conversations, build prioritization, rehearsal, and the vocabulary the user uses when talking to the head agent.

Why this framing matters:
- **Catches misunderstanding at journey-authoring time, not at ship time.** If user and head agent disagree about what the project is for, a journey that reads wrong on day one is cheaper to fix than a UI that ships wrong in month three.
- **Gives the user a vocabulary.** "Add a Q4 filter to the comparing-deals journey" is a precise request. "Add a Q4 filter" isn't.
- **Onboards new builders fast.** A builder who reads three journeys understands the product more than one who reads a 40-page spec.
- **Anchors the Accept conversation.** When the user reads the rehearsal narrative, the narrative is grounded in the journey they already know — not a generic walkthrough.

Journeys are maintained by the project chat. They evolve when product direction shifts. They are not frozen.

## What a good user journey looks like

A journey has four parts:

- **Persona** — who is this user in concrete terms. "Investor evaluating deal performance" is good. "A person" is not.
- **Goal** — one sentence. What the user is trying to accomplish.
- **Steps** — 3-6 concrete actions. Each step is something the user *does*, not something the system does.
- **Outcome** — what the user has accomplished or understands by the end.

### Worked example — abs-dashboard "comparing deals"

> **Journey: comparing deals**
> **Persona**: Investor with ~20 min, evaluating whether to underwrite a new securitization, already familiar with the asset class.
> **Goal**: Rank three recent deals on cumulative-loss trajectory and pick the one most worth a follow-up call.
> **Steps**:
> 1. Land on the dashboard, scan the deal cards for the three names.
> 2. Click the first deal, read the loss curve, note the CGS.
> 3. Switch to the second deal via the deal picker; compare visually.
> 4. Open Methodology to sanity-check the bucketing on the worst performer.
> 5. Export the comparison note or copy the deal name for follow-up.
> **Outcome**: Ranked the three deals with a defensible reason; knows which one to schedule a call on.

### Worked example — a simple static games hub

> **Journey: kill ten minutes between meetings**
> **Persona**: Returning visitor on an iPhone, wants something frictionless.
> **Goal**: Pick a game, play for ~5 minutes, close the tab without friction.
> **Steps**:
> 1. Tap the site link, land on the hub.
> 2. Pick a game from the thumbnails.
> 3. Play one session.
> 4. Navigate back without pinch-zoom or refresh required.
> **Outcome**: Played a round, closed the tab, no bugs or broken controls.

## Where journeys live

`REVIEW_CONTEXT.md#user-journeys` per project. Maintained by the project chat. Updated when product direction shifts. The `helpers/review-context.template.md` includes the section scaffold.

## Authoring journeys at project start

**Before any UI is built**, 1-7 journeys must be declared in `REVIEW_CONTEXT.md`. Target 3 for most projects. More than 7 is scope sprawl; 0 is a missing shared language. The reviewer fails project-kickoff PRs without journeys (per `SKILLS/new-project-checklist.md`).

This is deliberately front-loaded. Journeys written after the fact tend to describe what got built — not what the user wanted. Authored up front, they constrain the build.

## How rehearsal works mechanically

**Inputs (dispatcher supplies):**
- Spec of the change (1-2 sentences).
- `REVIEW_CONTEXT.md` path.
- Live preview URL.
- **Target journey** — which journey this ship affects. Dispatcher or project head chat picks. `all` triggers a broad rehearsal across every declared journey.

**Agent process:**
1. Reads `REVIEW_CONTEXT.md`, absorbs persona + target journey steps + aesthetic bar + red-flag patterns + known exceptions.
2. Navigates the preview URL via Playwright MCP (Bash-dispatched), taking a screenshot at each journey step.
3. Reads content as encountered — labels, numbers, error states.
4. Attempts the journey's stated outcome, recording observations step-by-step.
5. Emits a strict JSON verdict + a 1-paragraph first-person narrative.

**Output (orchestrator consumes):**
- Four-dimension verdict: `verdict`, `task_completion`, `findings`, `user_narrative`.
- Narrative attached to `CHANGES.md` for the user at Accept.

## Integration with QA sequence

```
Builder → Reviewer → QA (functional / visual-lint / visual-reviewer / data-audit / perceived-latency)
                                                                                                    ↓
                                                                                      Acceptance Rehearsal
                                                                                                    ↓
                                                                                                 Accept
```

Rehearsal is the **final gate** before the user. Failing rehearsal loops back to Builder. A rehearsal failure is not a reviewer failure — the earlier gates passed on their axes; rehearsal is specifically checking end-to-end journey coherence, which the other gates don't cover.

## What rehearsal catches vs doesn't

**Catches:**
- Comprehension issues — labels that confuse, copy that misleads.
- Broken flows — clicking the expected next step goes nowhere.
- Missing pieces — a promised export button isn't wired.
- Integration issues across pages — step 2 and step 3 were built by different dispatches and don't line up.
- Overall "does this make sense to me as the user this was built for."

**Doesn't catch:**
- Domain-specific numerical errors requiring external knowledge (data-audit's job).
- Subtle aesthetic bugs the LLM is insensitive to (visual-reviewer + user at Accept).
- Performance regressions (perceived-latency).
- Bugs that require multi-user state, auth-as-other-user, or production-only data.

When in doubt about which gate owns a concern, default to the gate earlier in the chain — rehearsal is the catch-all for what slipped through.

## Reading the narrative summary

The `user_narrative` field is the user's interface to rehearsal. 3-6 sentences, first-person, tone: "what did it FEEL like to be the user?" User reads it in ~30 seconds at Accept.

**Decision rule for the user:**
- Narrative reads smoothly + `verdict: READY` → confident-approve; share the live URL.
- Narrative flags rough edges OR `verdict: READY_WITH_NOTES` → user decides whether notes are blocking; the head agent defaults to "fix the notes, rerun rehearsal, then Accept."
- `verdict: NOT_READY` → do not show the user; loop back to Builder.

## Cost + timing

- ~$0.10-0.30 per rehearsal (Opus call + Playwright session).
- 60-180 sec wall-clock, run between QA green and Accept.
- Runs in parallel with nothing — it's the final gate.

If a project rehearses `all` journeys, cost scales linearly with journey count; dispatcher should target a single journey when the ship is scoped.

## Anti-pattern catalog

**1. Rehearsal produces vague approval without specifics.**
Symptom: narrative reads "looks fine, tried it out, no issues."
Fix: rehearsal must cite evidence — a quoted label, a screenshot reference, a step-by-step trace. The agent is instructed to self-HALT on vague output. If you see this symptom in the wild, the agent's self-check failed — file a LESSONS entry and tighten the agent brief.

**2. Journey exists but agent rehearsed a different one than the ship affects.**
Symptom: shipped a change to the Methodology tab; rehearsal targeted the "comparing deals" journey which doesn't touch Methodology.
Fix: dispatcher must specify the target journey. The project's head chat is responsible for tagging each dispatch with its affected journey. If the spec doesn't name a journey, the ship doesn't leave Spec gate (per CLAUDE.md "Spec Before Any Code").

## Related

- `SKILLS/visual-lint.md` — the deterministic + semantic visual gate that runs before rehearsal.
- `SKILLS/perceived-latency.md` — the perf gate in QA.
- `SKILLS/data-audit-qa.md` — the numbers gate for number-heavy projects.
- `SKILLS/platform-stewardship.md` — where learnings from rehearsal failures go.
- `SKILLS/new-project-checklist.md` — where journey-authoring is enforced at project start.
- `CLAUDE.md` "Spec Before Any Code" — spec must name which journey each UI ship extends.
