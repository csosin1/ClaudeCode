# Skill: Project Context

## When to use

Every project on the platform has exactly one `PROJECT_CONTEXT.md`. Authored at kickoff (via the `context-researcher` agent, see `new-project-checklist.md`), refreshed quarterly or on product shift, consumed by every specialized agent that touches the project.

This skill tells you **what the file is, how it differs from its siblings, who writes it, who reads it, when to refresh, and the shape of a good entry.**

## Why this exists

Specialized builder / reviewer / QA / visual-reviewer / acceptance-rehearsal agents have tight context windows. They cannot hold the full history of a project in-context. `PROJECT_CONTEXT.md` is their reservoir — they dip into it when they need:

- **Domain grounding.** "What does CGS mean in ABS context?" "Is this number-format convention a bug or house style?"
- **User mental-model grounding.** "What does the user assume agents already understand? What should never need to be re-explained?"
- **Shorthand vocabulary grounding.** "When the user says \'the Methodology tab\' in the dispatch, which section of which page is that?"

It also **preserves context across head-agent conversation compaction.** When the head agent\'s thread compacts and the chat-derived context gets lost, PROJECT_CONTEXT.md is the durable externalised memory the next head-agent session reads to catch up.

## The adaptive schema

Seven standard section headers. Same names every time. **Depth and weight adapt to project type.**

1. `## The user` — who the user is in this project, their role, mental model, constraints.
2. `## The builder context` — solo operator, platform plumbing this project sits in.
3. `## The world this project lives in` — domain / personal / regulatory context.
4. `## Success in the user\'s own words` — felt sense, not metrics.
5. `## Out-of-scope / not-concerns` — what this project is explicitly NOT doing.
6. `## Shorthand vocabulary` — "when user says X, they mean Y."
7. `## Authorship + refresh` — timestamp, source trail, next-refresh-due.

### Worked excerpts — three archetypes, same headers, wildly different content

**Archetype 1: abs-dashboard (industry/regulatory dominant)**

```
## The world this project lives in
Auto-loan asset-backed securitizations. Primary comparables: CarMax Auto
Owner Trust (CAOT), Santander Drive Auto Receivables Trust (SDART),
Carvana Auto Receivables Trust (CART). Standard metrics: CNL (cumulative
net loss), CGS (cumulative gross loss), 60+ DQ roll rate, excess spread.
Reporting convention: monthly distribution date + prior-month
collection-period data. Regulator: SEC Reg AB II (EX-102 loan tapes are
the primary source).

## Shorthand vocabulary
- "The loan tape" = the EX-102 file attached to each 10-D filing.
- "The Methodology tab" = /methodology on the live site.
- "Severity" = loss given default, not the finding severity in QA.
```

**Archetype 2: family-management software (personal/relational dominant)**

```
## The world this project lives in
Household of four. Two school-age kids, one dog, two working adults on
overlapping-but-not-identical schedules. Kitchen is the logistics hub;
the fridge door is where the paper calendar currently lives. The user
is trying to replace the fridge-door coordination, not replicate a
project-management tool. No teammates outside the household will ever
use this.

## Shorthand vocabulary
- "The calendar" = the shared Google calendar, not a new one.
- "Pickup" = school-end-of-day pickup, the highest-frequency event.
- "The thing we talked about" = the grocery-delegation flow from chat
  /root/.claude/projects/<slug>/<file>.jsonl, ~2026-03-28.
```

**Archetype 3: fund-accounting software (compliance/audit dominant)**

```
## The world this project lives in
Private-equity fund accounting. Delaware LPs primarily, one Cayman LP.
Year-end audit (Big 4) is the dominant compliance event. Fund admin is
outsourced; this tool is for the GP\'s internal review, not the admin\'s
ledger of record. ILPA reporting template is the north-star output
format.

## Shorthand vocabulary
- "The NAV" = net asset value at period end, pre-crystallization.
- "The waterfall" = the distribution waterfall model, not any UI element.
- "Audit-ready" = every number traces to a primary source with a
  one-click drill.
```

Three wildly different worlds. Same seven headers. That is the skill.

## Sources + priorities

The context-researcher agent draws from these, in priority order:

1. **Head-agent chat history** — `/root/.claude/projects/<slug>/*.jsonl`. Canonical. Richest. The user\'s and head agent\'s back-and-forth is where stated intent, rejected approaches, and shorthand vocabulary actually live.
2. **Repo artifacts** — `PROJECT_STATE.md`, `REVIEW_CONTEXT.md`, `CLAUDE.md`, `LESSONS.md`, `CHANGES.md`, `RUNBOOK.md`. Whatever exists.
3. **User kickoff text** — when the dispatcher supplies one.
4. **External web research** — only where external context materially applies. Often "n/a" for personal projects and internal infra. That is the correct answer when it is correct. Do not pad.

## How to author a good PROJECT_CONTEXT entry

**`## The user`** — what the user would say about themselves if asked, without needing to be prompted. Not a CV; not a product spec. "Solo operator, non-technical but product-literate, prompts from iPhone, has high taste for polish but short patience for friction." That sort of thing.

**`## The builder context`** — the platform this project sits in. "DigitalOcean droplet, nginx + systemd, five active projects share shared infra, auto-deploy via webhook, Playwright QA in CI, notifications via ntfy." Specialized agents need this so they do not propose a kubernetes cluster for a two-tap landing page.

**`## The world this project lives in`** — this is the adaptive section. Industry primer for an ABS dashboard; household brief for family software; jurisdictional primer for fund accounting. What would an agent need to know to not sound like a tourist?

**`## Success in the user\'s own words`** — in their vocabulary, their tone. Not "NPS > 50"; more like "I open it, I see the thing I was hoping to see, I close it without swearing."

**`## Out-of-scope / not-concerns`** — what the project explicitly is not. Guards against scope creep when a specialized agent sees an adjacent problem and tries to solve it.

**`## Shorthand vocabulary`** — "phrases you\'d feel awkward re-explaining to a new agent." Terms that in the user-head-agent conversation have become load-bearing. Extract verbatim where possible.

**`## Authorship + refresh`** — ISO timestamp, version, source trail (which chat files + which URLs), next-refresh-due date. Machine-readable enough that the refresh cron can check staleness.

## Refresh triggers

- **Quarterly baseline.** `/etc/cron.d/claude-ops` runs `/usr/local/bin/refresh-project-contexts.sh` at 04:00 on the 1st of every 3rd month. Iterates projects sequentially (not parallel — avoid LLM cost spikes), dispatches `context-researcher` in `refresh` mode for each.
- **REVIEW_CONTEXT.md material change.** When product direction, audience, or aesthetic bar shifts, the head agent dispatches a refresh.
- **User-initiated.** `/usr/local/bin/refresh-project-context.sh <project>` for any one project on demand.
- **Head-agent-initiated.** When the head agent notices substantial new context has surfaced in conversation that is not yet reflected in PROJECT_CONTEXT.md.

**Staleness decay:**
- `> 90 days since last refresh` → warn (surface in reviewer preamble).
- `> 180 days since last refresh` → fail kickoff PR of any new feature in that project until refreshed.

## Consumption by agents

| Agent | Reads PROJECT_CONTEXT.md? | How they use it |
|---|---|---|
| Head agent | Yes, on compaction recovery and session start | Reconstructs pre-compaction situational context |
| `infra-builder` | Yes, at start of any project-touching task | Design choices must fit the project\'s world |
| `builder` (per-project) | Yes, at task start | Same — ground design in user world |
| `infra-reviewer` | Yes, when PR touches `/opt/<project>/` | Cite a relevant section in review rationale |
| `reviewer` (per-project) | Yes | Calibrate against the user\'s actual standards |
| `infra-qa` | Yes, at start of project-scoped QA | Understand what "correctness" means for this user |
| `visual-reviewer` | Yes, before reviewing screenshots | Calibration comes from here, not just REVIEW_CONTEXT |
| `acceptance-rehearsal` | Yes, before rehearsing | Rehearse as an informed user of THIS project\'s world |
| `context-researcher` | Writes it | N/A |

## The files-in-this-project taxonomy

Why we have this many doc files and how they differ. Use this decision tree before writing a new entry:

| File | Scope | Cadence | Who writes | Core question it answers |
|---|---|---|---|---|
| `PROJECT_CONTEXT.md` | Broad, durable, situational | Quarterly refresh + on-shift | `context-researcher` | "What world does this project live in?" |
| `PROJECT_STATE.md` | Narrow, current state | Updated every 30 min of active work | Project chat / head agent | "Where are we right now, what is in flight?" |
| `REVIEW_CONTEXT.md` | Per-project QA calibration + user journeys | Updated when product shifts | Project chat | "What does \'good\' look like for this project at ship time?" |
| `CLAUDE.md` (root) | Platform-wide rules for every agent | Paired-edit on each change | Infra chat | "What rule must every agent follow?" |
| `LESSONS.md` | Incident + RCA log | Per incident | Agent closest to the incident | "What broke, why, how do we prevent it?" |
| `CHANGES.md` | Per-ship change log | Per ship | Builder of the change | "What did this ship do, what should QA verify?" |
| `RUNBOOK.md` | Operational facts (URLs, env vars, health checks) | When infra changes | Infra chat | "Where does this live, how do I poke it?" |

Rules of thumb for picking the right file when you have new info:

- **Dynamic per-task vs durable per-project** → PROJECT_STATE vs PROJECT_CONTEXT.
- **Per-project vs platform-wide** → PROJECT_* vs CLAUDE.md / LESSONS / SKILLS.
- **Incident vs planned** → LESSONS vs CHANGES / RUNBOOK.
- **How it ships vs what it is for** → REVIEW_CONTEXT vs PROJECT_CONTEXT.

If a piece of content plausibly fits two of these, it probably belongs in just one — pick the one matching the **cadence** at which the content will change. Split if needed; cross-link; do not duplicate.

## Anti-pattern catalog

**1. PROJECT_CONTEXT bloated with verbatim chat-log excerpts.**
Symptom: entire paragraphs quoted from jsonl files; reads like a diary; 8 KB files. Reviewer has to skim to find the distilled signal.
Fix: distill, do not transcribe. Each section is a briefing, not an archive. Quote only short load-bearing phrases in `## Shorthand vocabulary`; everything else is summarised.

**2. PROJECT_CONTEXT identical across projects because researcher applied the template rigidly.**
Symptom: family-software project has a two-paragraph "industry competitors" list; ABS-dashboard project has a generic one-liner world section.
Fix: the researcher must adaptively weight per project type. Same section headers; wildly different depth. The three worked excerpts above are the calibration.

## Related skills

- `new-project-checklist.md` — PROJECT_CONTEXT authorship is a required kickoff step.
- `perceived-latency.md`, `acceptance-rehearsal.md`, `data-audit-qa.md` — consumers of PROJECT_CONTEXT via their respective agents.
- `platform-stewardship.md` — the four registers of knowledge; PROJECT_CONTEXT is a fifth specifically-scoped register that did not previously exist.
- `session-resilience.md` — PROJECT_STATE.md conventions, the short-cadence sibling to PROJECT_CONTEXT.
