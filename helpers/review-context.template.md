# REVIEW_CONTEXT for <project-name>

Maintained by the <project> chat. Read by visual-reviewer agents at QA time.
Update when product direction, audience, or standards shift.

## Purpose
<1-2 sentences. What does this project do? Who are the primary users?>

## Audience
<1 line. External/investor-facing? Internal/research-only? Public showcase?>

## What correctness means here
<Project-specific. Numbers must be traceable to <source>? Must include
appropriate disclaimers? Data freshness requirements? This calibrates
reviewer severity.>

## Red-flag patterns
<What absolutely must not appear. E.g., "No loan-level PII ever." "No
forward-looking claims without disclaimers." "No placeholder text."
Reviewer flags these as HALT.>

## Aesthetic bar
<Short. Investor-grade polish? Utility-grade? Playful/informal?
Calibrates the unbriefed reviewer's sensitivity to aesthetic issues.>

## Known exceptions
<Legitimate things that might look like bugs but are intentional.
E.g., "NULL cells in CarMax 2014-2015 data are source-faithful, not
parser bugs." Prevents false-positive HALTs.>

## User journeys

Authored at project start. Maintained as product direction shifts. The canonical
definition of "what this project does for a user." Referenced by:
- User ↔ head-agent communication ("add X to the [journey-name] journey")
- Spec conversations for new features ("this feature extends [journey-name]")
- Acceptance-rehearsal QA gate (agent rehearses declared journeys)
- Builder onboarding ("read the journeys to understand user context")

Each journey: persona (who), goal (one sentence), steps (3-6 concrete actions),
outcome (what they understand or accomplish). Target: 1-7 journeys per project.
More = scope sprawl; fewer = missing critical paths.

### Journey: <short-name>
**Persona**: <who is this user>
**Goal**: <one sentence>
**Steps**:
1. <action>
2. <action>
3. <action>
**Outcome**: <what they know or have done>

### Journey: <short-name>
...
