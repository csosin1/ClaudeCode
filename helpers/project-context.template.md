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
_Sources: chat history <files / date ranges>, repo artifacts <PROJECT_STATE / REVIEW_CONTEXT / ...>, external <urls or "n/a">_
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

## Authorship + refresh

_Authored: <ISO timestamp>_
_Version: <n>_
_Mode: <initial | refresh>_
_Sources consulted:_
- Chat history: <file paths or ranges>
- Repo artifacts: <list>
- External URLs: <list, or "n/a">
_Next refresh due: <ISO date>_
_Refresh triggers: quarterly cron, REVIEW_CONTEXT material change, user-initiated via `/usr/local/bin/refresh-project-context.sh <project>`, or head-agent-initiated._
