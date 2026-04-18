# PROJECT_CONTEXT — <project>

<!--
  This template is reference, not authoritative. The `context-researcher` agent
  always produces a project-tailored output; this file exists so humans and
  agents can see the expected shape at a glance.

  The seven sections below are fixed in name and order. Their DEPTH is adaptive
  per project type (industry-dominant vs personal-dominant vs infra-dominant).
  See SKILLS/project-context.md for the three worked archetypes.
-->

_Authored: <ISO timestamp, e.g. 2026-04-17T12:00:00Z> · Version: 1 · Mode: initial_
_Sources: chat history <files / date ranges>, repo artifacts <PROJECT_STATE / prior PROJECT_CONTEXT / ...>, external <urls or "n/a">_
_Next refresh due: <ISO date, +90 days from authorship>_

## The user

<Who they are in this project. Role. Mental model. What they already know;
what agents should NOT need to explain back. 2-6 sentences.>

## The builder context

<Solo operator on the multi-agent Claude-Code platform. Relevant shared-infra
this project uses or is affected by: nginx location block(s), systemd units,
cron entries, notify.sh, paid-call gateway, capacity monitoring. Scale
assumption: one user, handful of projects. 2-5 sentences.>

## The world this project lives in

<THE ADAPTIVE SECTION.

For industry/regulatory projects: the industry primer. Peers, norms,
regulators, standard metrics, reporting conventions. Can be long.

For personal/relational projects: the actual people, rhythms, places. Can be
long in a different shape.

For internal-infra projects: the platform itself and the other projects it
supports.

For something else: do what fits.

Leave this thin only if the project genuinely has no external world worth
describing.>

## Success in the user's own words

<How the user will know this is working, in their vocabulary. Felt sense,
not metrics. 2-4 sentences, first-person if natural.>

## Out-of-scope / not-concerns

<Things this project explicitly is NOT trying to do. Bullet list. Prevents
specialized agents from scope-creeping into adjacent problems.>

## Shorthand vocabulary

<Established terms between user and head agent that specialized agents should
understand. "When user says X, they mean Y." Extract verbatim where possible.
Bullet list; 3-15 entries typical.>

- "<phrase>" — <meaning>
- "<phrase>" — <meaning>

## QA calibration

<Read by visual-reviewer and acceptance-rehearsal at QA time. Five axes:

- **Audience** — external/investor, internal/research, public showcase, utility-grade, etc.
- **What correctness means here** — numbers traceable to what source, disclaimer requirements, freshness windows.
- **Red-flag patterns** — hard-HALT list. "No loan-level PII." "No forward-looking claims without disclaimer." etc.
- **Aesthetic bar** — investor-grade polish vs utility-grade vs playful. One line is enough.
- **Known exceptions** — legitimate things that might look like bugs but are intentional.

Infra-only projects with no user surface may write `_None — infrastructure project with no end-user surface._` and skip.>

## User Journeys

<The canonical definition of "what this project does for a user." Referenced by:
- User ↔ head-agent communication ("add X to the [journey-name] journey")
- Spec conversations for new features ("this feature extends [journey-name]")
- Acceptance-rehearsal QA gate (agent rehearses declared journeys)
- Builder onboarding ("read the journeys to understand user context")

Target: 1-7 journeys per project. More = scope sprawl; 0 on a user-facing project = missing critical paths.

Infra-only projects: write `_None — infrastructure project with no end-user surface._`>

### <journey-name>
- **Entry URL:** <url or none>
- **Declared success:** <1-sentence outcome that means this journey worked>
- **Steps (high level):** <ordered list, 3-7 items>
- **Key failure modes:** <what breaks this journey>

## Authorship + refresh

_Authored: <ISO timestamp>_
_Version: <n>_
_Mode: <initial | refresh>_
_Sources consulted:_
- Chat history: <file paths or ranges>
- Repo artifacts: <list>
- External URLs: <list, or "n/a">
_Next refresh due: <ISO date>_
_Refresh triggers: quarterly cron, QA-calibration or journey shift (update `## QA calibration` / `## User Journeys` in place), user-initiated via `/usr/local/bin/refresh-project-context.sh <project>`, or head-agent-initiated._
