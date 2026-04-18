# Competitive Analysis — Our Platform vs Open-Source AI Coding Tools

_Drafted 2026-04-18. Refresh when we add major capabilities or notable OSS tools ship new ones._

> **Status**: scaffold — research agents populating the matrix and per-tool summaries in parallel; merge in progress.

---

## Executive summary

_[filled after both research legs merge; 2-3 paragraph answer to "what's distinct about our platform and what are we missing."]_

---

## Methodology

Two parallel research subagents covered ~12 tools in the OSS AI-coding-tool space:

- **Leg A** (developer-productivity IDE/CLI tools): Cursor, Cline, Continue, Aider, Claude Code, Zed AI
- **Leg B** (autonomous agents + multi-agent frameworks): OpenHands, AutoGen, CrewAI, LangGraph, SWE-agent, GPT Engineer / GPT Pilot

Each tool surveyed on: primary mode, autonomy level, multi-file/multi-project/session-resume support, agent architecture, QA/review/testing mechanisms, observability, extensibility, notable strengths/gaps.

Ground truth for "our platform" came from `/opt/site-deploy/CLAUDE.md`, `/opt/site-deploy/SKILLS/`, `/opt/site-deploy/.claude/agents/`, and recent `/opt/site-deploy/CHANGES.md` entries — not speculation.

---

## Unified feature matrix

| Capability | Cursor | Cline | Continue | Aider | Claude Code | Zed AI | OpenHands | AutoGen | CrewAI | LangGraph | SWE-agent | GPT Eng | **Our Platform** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IDE integration | | | | | | | | | | | | | |
| CLI mode | | | | | | | | | | | | | |
| Multi-file edits | | | | | | | | | | | | | |
| Multi-project coexistence | | | | | | | | | | | | | |
| Session resume / durable context | | | | | | | | | | | | | |
| Explicit plan/act separation | | | | | | | | | | | | | |
| Multi-agent orchestration | | | | | | | | | | | | | |
| Narrow-scope independent reviewers | | | | | | | | | | | | | |
| Post-deploy QA (tests live URL) | | | | | | | | | | | | | |
| Acceptance rehearsal (LLM-as-user) | | | | | | | | | | | | | |
| Visual / UI-specific QA | | | | | | | | | | | | | |
| Data-audit / semantic correctness | | | | | | | | | | | | | |
| Incident → reviewer-rule feedback loop | | | | | | | | | | | | | |
| Cost tracking | | | | | | | | | | | | | |
| Cost circuit-breakers (fail-closed) | | | | | | | | | | | | | |
| Mobile-first UX | | | | | | | | | | | | | |
| Non-technical user target | | | | | | | | | | | | | |
| Formal benchmark coverage (SWE-bench) | | | | | | | | | | | | | |
| Tracing / observability UI | | | | | | | | | | | | | |
| Extensibility / plugin mechanism | | | | | | | | | | | | | |

_✅ = has feature; ⚠️ = partial/indirect; ❌ = absent; blank = insufficient info._

---

## Tool-by-tool summaries

### Developer-productivity IDE/CLI tools (Leg A)
_[research agent A fills in: per-tool paragraph with primary mode, autonomy, distinct strengths, gaps]_

### Autonomous agents and multi-agent frameworks (Leg B)
_[research agent B fills in: per-tool paragraph with same fields]_

---

## Our platform's distinct strengths

_[filled after merge — synthesis of both legs' observations on what we have that they don't]_

Preliminary hypotheses (to be verified by research):

1. **Operational harness for production services, not just code writing.** Most OSS tools optimize for "help a developer write code in their IDE." We optimize for "run a small software company autonomously for a non-coder."
2. **Post-deploy QA with freeze sentinels.** Tests against live URLs after auto-deploy regens, freezes pipeline on failure. Not observed in OSS agent frameworks.
3. **PROJECT_CONTEXT as externalized shared memory.** Per-project durable context file that all agents dip into. Most tools assume single-session or per-task context.
4. **Acceptance-rehearsal agent.** LLM plays end user before user-Accept. Not observed in OSS.
5. **Cost monitoring at paid-API-wrapper level with circuit breakers.** Most tools have usage tracking; ours refuses paid calls when cap would be breached.
6. **Multi-project coexistence with strict isolation + shared platform services.** Closer to a FAANG internal platform team than an OSS tool.
7. **Reviewer-rule feedback loop from LESSONS.** Incidents mechanically modify future review behavior.
8. **Mobile-first UX with ntfy push + iOS-plain-URLs + /remote/ pages.** Zero OSS tools target iPhone-from-anywhere.
9. **Narrow-scope independent reviewers (4 shipped, more queued).** The pattern of "each reviewer has ONE narrow job" rather than one monolithic review step.
10. **Data-audit with display-layer sanity ranges.** Domain-specific QA beyond functional correctness.

---

## Our platform's gaps vs OSS

_[filled after merge]_

Preliminary hypotheses:

1. **No IDE integration.** Pure CLI/tmux. Probably fine given non-technical-user target; material gap if we ever serve developers.
2. **No formal benchmarks.** OpenHands, Aider, SWE-agent publish SWE-bench scores. We have no empirical "does our harness improve agent output vs. naive Claude Code?" measurement.
3. **No tracing/observability UI.** LangSmith, OpenLLMetry give web dashboards. Ours lives in log files.
4. **Ad-hoc session checkpoint.** Claude Code has built-in resume. Our durability relies on PROJECT_STATE/CONTEXT discipline.
5. **Claude-only.** Multi-model orchestration frameworks (LangChain/LangGraph) route by task. Fine given commitment; weakness if provider shifts.
6. **No plugin/extension ecosystem.** SKILLS/ is our extension mechanism but designed for us, not third-party contribution.
7. **No semantic code search.** grep-based. Fine at our size; doesn't scale.
8. **No formal plan/act toggle.** Cline/OpenHands have explicit modes; our "Spec Before Any Code" is softer.

---

## Recommendations for productization story

_[filled after merge — actionable list based on the gap analysis]_

Preliminary framing (to be verified):

- **Differentiation narrative**: "production-operations harness for LLM-driven software teams" — different product than OSS developer-productivity tools.
- **Critical pre-productization gap**: formal benchmarks. Without SWE-bench (or equivalent), we can't honestly claim improvement over naive Claude Code. Fills one specific gap; earns the right to make claims.
- **Near-term closure targets**: benchmark integration, tracing UI (lightweight — extend spend-audit dashboard pattern), session checkpoint formalization.
- **Defer indefinitely**: IDE integration, multi-model routing, plugin ecosystem. Not relevant to non-technical-user target unless we pivot.

---

## Sources

_[filled after merge — cite specific docs, READMEs, blog posts the research agents pulled from]_

---

## Appendix: research leg raw outputs

_[paths to leg A and leg B research fragments, preserved for traceability]_
