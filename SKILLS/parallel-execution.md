# Skill: Parallel Execution

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
