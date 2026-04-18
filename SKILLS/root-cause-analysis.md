---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Root-Cause Analysis

## When to use

Use this skill when working on root-cause analysis. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Restore service fast when needed — then always fix the root cause.** Patching and RCA are not alternatives; the patch buys time, the RCA prevents recurrence. Stopping at the patch is how incidents compound into outages.

## What This Skill Does

Defines how to respond when code, tests, infra, or a deploy breaks. Forces the investigation down to the actual cause, requires the fix target that cause, and captures the finding in `LESSONS.md` so no one ever re-investigates the same thing.

## When To Use It

Any unexpected failure: test red, build broken, deploy stuck, prod alert, data corruption, agent loop, silent degradation. "Unexpected" is the trigger — if the failure is surprising, you don't yet know the cause.

## The Investigation

Ask "why" until the answer is either a concrete defect you can fix, or an environmental invariant you can enforce. Five levels is a rough floor; more is fine.

```
Symptom:       Playwright test flakes with "element not visible"
Why #1:        The element exists but isn't rendered when we assert.
Why #2:        The React component that renders it depends on an async fetch.
Why #3:        The test doesn't wait for the fetch to complete.
Why #4:        We have no `waitFor(network idle)` hook; tests assume instant render.
Why #5:        The test harness was written when the page was static.
Root cause:    Test harness pattern is incompatible with async-rendered pages.
Fix:           Replace `expect().toBeVisible()` with `await expect().toBeVisible()` + testid-based waitFor; add a harness helper so other tests inherit the pattern.
NOT a fix:     Adding `await page.waitForTimeout(500)` before the assertion.
```

If you find yourself about to write any of these, you're patching, not fixing:

- `sleep N` / `waitForTimeout`
- `retry: N` without understanding why it fails
- `try { ... } catch { /* ignore */ }`
- `// TODO: figure out why this is needed`
- Pinning a dependency version you haven't audited
- Restarting the service as the resolution
- Catching an exception and returning a default

These are symptom suppressors. They let the failure recur silently, often in a worse form.

## Mandatory Write-Up

After fixing the root cause, append to `LESSONS.md` in the same commit:

```markdown
## YYYY-MM-DD — <one-line symptom>
**Root cause:** <the actual cause, 1-3 sentences>
**Fix:** <what changed and where — file:line>
**Preventive rule:** <what should have caught this earlier — a test, a lint rule, a CLAUDE.md clause, a runbook check>
```

The preventive-rule line is the compound-interest part. If the same class of bug could happen again, turn it into a rule, test, or guardrail. If it can't — say so explicitly ("one-off, environment-specific") so future readers don't invent a guardrail for a non-recurring problem.

## Patch → Restore → RCA (the normal flow for urgent breakage)

When prod is down or a user is blocked and the root cause will take time, you **patch to restore first**. That is the right call — users shouldn't wait for your investigation. But the RCA is not optional; it's the second half of the same incident.

1. **Patch to restore.** Apply the minimum change that makes it work again. Mark the site with `// HOTFIX <date>: RCA pending — <one-line symptom>` so it's visible in code review.
2. **File the RCA follow-up immediately.** Before moving to anything else: `TaskCreate` or `user-action.sh add` with a deadline (default: within 24h, sooner for recurring incidents).
3. **Do the investigation.** 5-whys ladder until you hit the real cause. Don't let the patch lull you into assuming you understand what happened — the patch proves the symptom stopped, not the cause.
4. **Land the permanent fix + LESSONS.md entry in the same commit.** Remove the HOTFIX comment.
5. **Close the follow-up only after the real fix is deployed and verified.**

A patch that ships without step 2 is invisible incident debt. A patch that ships without steps 3-5 is technical debt with a fuse on it.

## Anti-Patterns

- **"It worked after I restarted it."** The state that made it fail is still there; you just reset the clock. Investigate what got into that state.
- **"Flaky test."** There's no such thing. There are tests with unhandled non-determinism, and tests whose assertions don't match the actual contract. Both have root causes.
- **Incremental patches on the same symptom.** If you're touching the same file three times to fix the same class of failure, stop patching and audit the whole component.
- **Fixing the error message instead of the error.** Changing what the logs say without changing why.
- **Root cause in the wrong layer.** If the bug is in config, fixing the code that mis-reads config doesn't help — fix the config schema so it can't be mis-read.

## Integration

- Companion skills: `SKILLS/platform-stewardship.md` (learnings belong in the right register), `SKILLS/parallel-execution.md` (spawn Explore agents in parallel while investigating — multiple hypotheses tested at once).
- `LESSONS.md` entries get read by every Builder and Reviewer — this is how preventive rules actually prevent.
