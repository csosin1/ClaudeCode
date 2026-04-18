---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Non-Blocking Prompt Intake

## When to use

Use this skill when working on non-blocking prompt intake. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**The main thread is a coordinator, not an executor.** When a new user prompt arrives while other work is in flight, the chat hands it off to a fresh subagent and stays available for the next prompt. The user should never be stuck watching the chat "Canoodling…" for 18 minutes because two earlier subagents haven't returned.

## Why This Exists

Observed failure mode: the carvana-abs chat launched 3 parallel subagents for a data-quality audit. The user then fired two new prompts ("why only 3 agents" and "kmx note tabs are missing data"). Both sat in the queue for 18+ minutes because the main thread was blocked waiting on the in-flight subagents to finish.

The fix isn't to make subagents faster. It's to stop treating the main thread as something that must "finish" before taking the next input.

## The Decision (fast)

When a new prompt arrives, categorize it in one sentence, then act:

| Category | Example | Action |
|---|---|---|
| **Independent** | "Look at the KMX note tabs for missing data" while running a Carvana integrity audit | Spawn a subagent immediately. Don't block. Report subagent dispatch to the user in a sentence, then return to orchestrating in-flight work. |
| **Clarifying / refining** | "Actually focus on delinquency not FICO" while a builder is mid-extraction | Integrate into in-flight context. If the subagent is far down a wrong path, interrupt it and relaunch with the refined scope. |
| **Correcting / aborting** | "Stop", "undo", "that's wrong" | Interrupt in-flight work immediately (`esc` / task cancellation). Surface the correction. |
| **Read-only status** | "What's happening", "any blockers", "show me X" | **Always** spawn a subagent or answer from cache — never block on anything. Status questions are the #1 reason blocking feels broken. |

When in doubt, default to "independent → spawn a subagent." False-positive spawning costs a few thousand tokens; false-negative blocking costs the user's patience.

## How To Dispatch (the mechanics)

In a single assistant message:

1. Acknowledge the new prompt in one short sentence. ("Dispatching an agent for the KMX note-tab question.")
2. Call `Agent` with a tight, self-contained brief (per `SKILLS/parallel-execution.md` — the agent hasn't seen the conversation, so the prompt must stand alone).
3. In the *same* message, continue orchestrating in-flight work (report on subagents, check their progress, plan the merge).
4. When the new subagent returns, surface its result in a new turn.

The key is **one message, multiple tool-use blocks**. Spawning the agent and continuing with existing work happen in parallel, not sequentially.

## What Belongs In The Main Thread

Short:

- Routing decisions ("this goes to subagent X, this to subagent Y").
- Merging outputs from returning subagents.
- Writing the final user-facing response once things converge.
- Interrupting / redirecting subagents when new info invalidates their scope.

What does NOT belong in the main thread:

- Running tests.
- Reading large files.
- Deep code investigation.
- Anything that blocks for >30 seconds.

If the main thread is doing any of those, the next user prompt will feel like a hang. Delegate.

## Anti-Patterns

- **Queue-and-wait.** Letting user prompts sit unread until the current work finishes. The queue is fine as a transport; the chat's job is to drain it in real time by dispatching each one.
- **"Let me just finish this first."** No. Spawn, report, move on. "Finishing first" is how 18-minute silences happen.
- **Spawning a subagent for something that takes 10 seconds.** The orchestration overhead isn't worth it. Trivial answers come from the main thread directly.
- **Spawning a subagent without a self-contained brief.** The subagent doesn't have your conversation context. If the prompt is "look at the KMX tabs," the brief needs to say *which* tabs, *what* "look at" means, *where* the data lives, *what output format*. See `SKILLS/parallel-execution.md § How To Dispatch`.
- **Letting subagents accumulate silently.** Every ~10 min of no status back to the user, surface a one-line progress update. "3 subagents still running: A done, B 70% through, C just started."

## Quick Rubric For When To Spawn

If **all** of these are true, spawn an agent:
- The new prompt can be answered by reading/grepping/searching code or running a tool with a known answer.
- It doesn't require reverting or redirecting in-flight work.
- It's more than a trivial 1-line answer.

If **any** of these is true, don't spawn — handle in the main thread:
- Correcting or aborting in-flight work.
- Trivial answer ("yes", "running fine", "3 agents still going").
- Requires synthesis across multiple in-flight results.

## Integration

- Companion: `SKILLS/parallel-execution.md` — the dispatch mechanics. This skill is the *when*; parallel-execution is the *how*.
- When in-flight work is expensive and a new prompt arrives, this skill has priority: do not make the user wait for the current stack to drain.
- Orchestrator chats (windows named `timeshare-surveillance`, etc. when acting as orchestrators) follow the same rule — even more strictly, since they tend to have more concurrent work.
