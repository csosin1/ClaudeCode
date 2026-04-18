---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Parallel Execution

## When to use

Use this skill when working on parallel execution. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Never do work sequentially that can run in parallel.** Wall-clock time is the scarce resource for the user. Five independent things run in parallel finish in the time of the slowest one, not the sum.

## What This Skill Does

Tells agents when to parallelize operations, when to keep them sequential, and how to actually dispatch them correctly with the tools available.

## When To Parallelize

Parallelize by default whenever all of these hold:

- **Independence of inputs.** Neither operation needs the other's output.
- **Independence of state.** They don't write to the same file, database row, branch, or external resource.
- **Independence of order.** The final result is the same regardless of which finishes first.

Concrete cases that should almost always be parallel:

| Situation | How to dispatch |
|---|---|
| Multiple Bash / Read / Grep / Glob calls with no data dependency | Single assistant message with multiple tool-use blocks. |
| Audit / research queries across several files or repos | Multiple `Agent` tool calls (with `subagent_type: Explore`) in one message. |
| Builder work on independent files/features | Multiple `Agent` tool calls with different scopes in one message (see Parallel Builders note below). |
| Status polls / health checks across services | One message, one tool call per service. |
| Running tests for different projects that share no fixtures | Fork Playwright workers, or parallel bash invocations. |

## When To Keep Sequential

- **Pipe dependencies.** Output of step N is input to step N+1. Forcing parallelism here just re-serializes with bookkeeping overhead.
- **Shared mutable state.** Two agents editing `package.json` or touching the same database migration will corrupt each other.
- **Exploratory work where early findings should redirect later steps.** Running three speculative builds in parallel wastes two when the answer to the first invalidates the others.
- **Rate-limited external APIs.** Parallelizing into a 429 is worse than serial.

## How To Dispatch In Claude Code

Independent tool calls go in **one assistant message with multiple tool-use blocks** — not sequential messages. That's what actually runs them concurrently; calling them in separate turns serializes them with full round-trip latency between each.

For heavier work (research, building), fan out `Agent` calls the same way: one message, N tool-use blocks, each with its own scope and clear file-path ownership.

When the orchestrator dispatches subagents, it must:
1. List the file paths each subagent will touch.
2. Verify zero overlap.
3. Launch them all in one message.
4. After all return, merge outputs and run a single Reviewer + single QA pass.

## Common Pitfalls

- **False independence.** Two Builders both writing to a shared `tests/` file — looks independent, isn't. If either touches a file the other might, serialize them or split the file first.
- **Race on shared branch.** Multiple project chats writing to the same branch in the shared repo. Avoided by the worktree-based branch hygiene (`/opt/worktrees/<project>-<slug>/`); see `CLAUDE.md § Feature-Branch Workflow`.
- **Sequential out of habit.** Running `git status`, then `git diff`, then `git log` as three separate messages. They're independent — one message, three tool-use blocks.
- **Over-parallelization.** Dispatching 20 Agents at once when 3 would do. Each Agent costs tokens; fan out to the granularity that matters.
- **Missing the join.** Fanning out without a plan for how to merge the outputs back. Always know who merges.

## Efficiency Self-Check

At every decision point ask: "Is anything I'm about to do next independent of anything else I'm about to do next?" If yes and I was planning them as separate messages, that's a bug — batch them.

## Escalation

If work that should have run in parallel ran serially and wasted >5 minutes, note it in `LESSONS.md` with the missed-parallelization pattern, so it becomes a tell-tale for future agents.

## "Phases" Considered Harmful (Anti-Pattern)

If your plan uses "Phase 1, Phase 2, Phase 3…" language, **stop and check each phase**: does it actually depend on the prior, or does the number just reflect the order you happened to think of them in?

If no real dependency, rename:

> Independent task A, Independent task B, Dependent task C (depends on A).

The linguistic framing "phases" silently implies sequence. Planners who commit to phase-numbered shape rarely escape it on self-review — even when 4 of the 6 "phases" are fully independent. The frame traps the planner.

**Worked example — 2026-04-18 carvana adoption miss.** The infra orchestrator dispatched a 6-phase directive to adopt the platform's PROJECT_CONTEXT + journey / QA-calibration sections (then still named `REVIEW_CONTEXT.md`; merged into `PROJECT_CONTEXT.md` later on 2026-04-18) + speedup-reviewer standards into the carvana chat. All six "phases" were framed as sequential. In fact:
- Phase 1 (research PROJECT_CONTEXT) — independent; could run from infra chat or carvana chat.
- Phase 2 (draft journey / QA-calibration skeleton) — independent of 1.
- Phase 3 (wire acceptance assertions) — independent of 1 and 2.
- Phase 4 (update carvana CLAUDE.md pointer) — independent of 1-3.
- Phase 5 (integrate) — genuinely depended on 1-4.
- Phase 6 (QA) — genuinely depended on 5.

Four of six were independent. The frame ate hours of user wall-clock before the user pushed back with "so slow, can this be parallelized?" The fix: rename phases by dependency (A, B, C, D all parallel; E needs A-D; F needs E), dispatch A-D in one message.

## Cross-Chat / Cross-Session Parallelism

The less-visible axis, because it straddles chats and is invisible from inside any one of them.

When the orchestrator is writing a directive to another chat/agent, always ask: **"what can I do from here WHILE they do their part?"** Sitting idle waiting for the recipient to finish is the default because it's quiet; quiet isn't the same as right.

**Worked example — same 2026-04-18 miss.** The orchestrator wrote a directive to the carvana chat, then waited. But the PROJECT_CONTEXT researcher could have been dispatched from the infra chat simultaneously — reading carvana history, drafting the initial file — while the carvana chat worked on the journey / QA-calibration sections + assertion wiring. Two chats in parallel > sequential hand-off.

**Explicit question to run on every dispatch:** "For every piece of work I'm handing off, is there work I can be doing concurrently from my end?" If yes, dispatch them both in parallel. The recipient chat doesn't notice; the user sees half the wall-clock.

## When Parallelism Is Wrong

Parallelism is not free. Before recommending it, check:

- **Shared-state writes.** Two agents editing the same file, the same DB row, the same git branch. Merge hell or lost writes. Either serialize, or split the file / row / branch first.
- **Rate-limited APIs.** Decodo, Anthropic tier limits, any third-party endpoint that 429s. Parallel into a 429 is slower than serial. Respect the token bucket.
- **Ordered side effects.** Step B genuinely needs to observe step A's effect on the world (not just its data). Example: deploy-then-smoketest. You can't smoketest what isn't deployed.
- **Coordination overhead > savings.** 3 small tasks × 10s each to coordinate them > 1 task × 25s sequential. Parallelism has a floor cost. Below some per-task size, the dispatch tax dominates.

The rule is **consider parallelism explicitly, don't default to either answer.** Sometimes sequential is right. Say so, with reason.

## Anti-Pattern Catalog

Seeded so future misses of the same shape get caught faster. Append here when you find a new one.

### (a) Phase-N framing used for independent tasks
- **Observed:** 2026-04-18 carvana adoption directive. 6 "phases"; 4 were independent. Missed until user pushed back.
- **Tell-tale:** plan uses "Phase 1, 2, 3…" language.
- **Fix:** rename as Independent task A/B/C with explicit dependencies. If any "phase" has no upstream dependency, it's not a phase — it's a parallel task.

### (b) Orchestrator sequential with recipient chat
- **Observed:** 2026-04-18 — infra orchestrator sat idle while carvana chat worked. PROJECT_CONTEXT research could have run on the infra side simultaneously.
- **Tell-tale:** orchestrator dispatches a directive and then its next step is "wait for reply."
- **Fix:** dispatcher always asks "what can I do concurrently from my end?" before hitting send.
