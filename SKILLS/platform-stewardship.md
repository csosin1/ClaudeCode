# Skill: Platform Stewardship

## Guiding Principle

**A problem solved once should never need to be solved again.**

Every other rule in this file is mechanism in service of that principle. If a write-up, edit, or extraction makes the next encounter of the same problem cheaper, do it. If it doesn't, skip it.

## What This Skill Does

Keeps the platform improving with every session. Defines *where* to put different kinds of learning, *when* to trigger a write-up, and *how* to keep CLAUDE.md thin so it stays readable and authoritative.

## When To Use It

At the end of every non-trivial task, and any time you notice friction, duplication, or a one-time cost that could be amortized. This is not optional — it's the mechanism by which the platform compounds rather than stagnates.

## The Four Registers of Knowledge

Every learning goes in exactly one of these. Picking the wrong one dilutes the others.

| Register | What belongs there | Test |
|---|---|---|
| `CLAUDE.md` | **Rules** that apply to every agent on every task. Behavioral norms, invariants, safety guardrails. | If it doesn't start with "always", "never", or "before X, do Y", it probably doesn't belong here. |
| `SKILLS/<topic>.md` | **How-to** for a reusable pattern — library, service, technique, integration. | "Next time someone needs to do X, they read this and succeed without relearning." |
| `LESSONS.md` | **Incidents and gotchas** — specific things that broke, root causes, what to watch for. | Written in past tense. "In April 2026, X happened because Y. Now we Z." |
| `RUNBOOK.md` | **Per-project operational facts** — URLs, paths, env var names, health checks. | Grounded in a specific project's reality; updates when infra changes. |

If a piece of knowledge feels like it fits two registers, you're probably about to bloat one. Split it: the rule goes in CLAUDE.md as a one-liner, the detail goes in SKILLS/.

## Triggers That Demand a Write-Up

Whenever any of these happen, write or update an entry **in the same commit as the work**:

- You spent >30 minutes figuring out a non-obvious pattern, API quirk, or integration → `SKILLS/<topic>.md`.
- You used a new library or managed service for the first time on this platform → `SKILLS/<library>.md`.
- Something broke in production or nearly did → `LESSONS.md` with root cause + fix + preventive rule.
- You solved the same class of problem twice across projects → it's now a skill; write it.
- You discovered a CLAUDE.md rule is wrong, stale, or missing a clause → edit CLAUDE.md *in the same commit* as the work that proved it, so the cause and correction stay linked.
- You noticed the platform doing something inefficient that a 1-hour fix would eliminate forever → add a task to track it, or fix it inline if trivial.

## Keep CLAUDE.md Thin

CLAUDE.md is the constitution. Power lives in SKILLS/. The invariant:

- **Every section ≤ one screen on an iPhone.** If it grew past that, factor the detail into a SKILLS/ file and leave a one-line pointer.
- **No examples, gotchas, or code snippets in CLAUDE.md.** Those belong in SKILLS.
- **No history.** "We used to do X but changed to Y" goes in LESSONS.md, not CLAUDE.md.

Pattern to use when extracting:

> ## <Section name>
> <One-sentence rule.> See `SKILLS/<topic>.md`.

## Periodic Review

At the end of any session that touched CLAUDE.md:
1. Re-read the changed section. Is any part of it a "how" rather than a "what"? Extract.
2. Check total line count. If CLAUDE.md has grown >20% since last review without the section count growing proportionally, something is getting fat — find it and trim.
3. Diff the SKILLS/ index mentally — is there a skill that was referenced three times this week but doesn't exist yet? Write it.

## Efficiency-Seeking Mindset

Beyond bug fixes and feature work, every session should leave one artifact that makes future sessions cheaper: a new skill, a sharper rule, a deleted dead file, a script that removes a manual step, a trimmed CLAUDE.md section. If the session ended with no such artifact, the platform stood still — that's the failure mode to avoid.

## Anti-Patterns

- **Silent learning.** Figuring something out, shipping the fix, and not writing it down. The cost of the write-up is ~3 minutes; the cost of relearning is hours.
- **CLAUDE.md as dumping ground.** Rules should be crisp enough to read in 90 seconds. Long-form guidance lives in SKILLS.
- **Skill files that read like essays.** SKILLS/*.md are reference, not narrative. Structure: What it does / When to use / Required setup / Minimal example / Gotchas.
- **Duplicate knowledge.** Same guidance in two places means it'll drift. Single source of truth; link from everywhere else.
