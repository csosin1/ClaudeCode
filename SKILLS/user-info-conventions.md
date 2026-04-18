---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: User-Information Conventions

## When to use

Use this skill when working on user-information conventions. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**The user's attention is the scarcest resource on the platform.** Design every interaction as if they walked away five minutes ago and are coming back to check in. Make it trivial for them to understand current state, trivial for them to decide what's next, and impossible for a failure to go unsurfaced.

## When To Use

- Starting any non-trivial task (scope-upfront + status-file).
- Completing a task (done-signal + cost summary).
- Hitting a blocker (stuck detector).
- Anywhere a notification would save the user from having to check.
- End-of-session cleanup.

## Scope Upfront

Before starting any non-trivial task, say how long it'll take. "~15 min", "~1 hr", "~3 hr with multiple iterations." The user may walk away between prompt and completion — they need to know when to check back.

## Spec Template

For non-trivial scope, surface to the user and wait for "go" before building. Four bullets, in order:

1. **What will be built** — 1-2 sentences. Plain English, no jargon.
2. **Success criteria** — what QA will verify. Observable, not aspirational.
3. **File locations** — mandatory, no speculative paths. If you don't know the path, find it first.
4. **Non-goals** — what this intentionally does NOT cover, so scope doesn't drift mid-build.

For UI-shipping changes, also name which user journey (from the project's `PROJECT_CONTEXT.md#user-journeys`) this extends, modifies, or introduces — specs without journey-anchoring for UI changes return to Clarify.

## The Task-Status File

Canonical source of "what's happening right now" for the projects dashboard.

```bash
/usr/local/bin/task-status.sh set "<project>" "<name>" "<stage>" "<detail>"    # when starting
/usr/local/bin/task-status.sh done "<project>" "<name>" "<summary>; ~42k tokens" <preview_url>  # when finished
/usr/local/bin/task-status.sh clear "<project>"                                 # when fully handed off
```

Writes to `/var/www/landing/tasks.json`. The user taps `https://casinv.dev/projects.html` to see status anytime. Don't skip `done` — the completion badge is how they know to check.

## Cost Visibility

Always include approximate token cost in the `done` summary:
```bash
task-status.sh done <project> "<name>" "completed; ~42k tokens" "<preview_url>"
```
The dashboard surfaces this per project. Users should be able to tell which tasks are cheap and which are expensive over time.

## Notifications

Push via `notify.sh`:
```bash
/usr/local/bin/notify.sh "<message>" "<title>" <priority> "<click-url>"
```
Priorities:
- **`urgent`** — hard blockers needing input NOW (droplet failing, credential leaked, user action needed).
- **`high`** — task done and awaiting review, or a milestone crossed.
- **`default`** — routine progress updates, job completions.

Preview deploys auto-notify via the webhook — no manual notify needed. For discrete milestones beyond deploy, call directly.

## Token-Cost Guardrail

If a single task exceeds ~200k tokens or has burned through that much without reaching QA-green, stop and surface the scope blowout via `notify.sh` with `urgent` priority. Do not spiral. User decides whether to continue, abort, or re-scope.

## Stuck Detector

If the same fix is attempted twice without progress (e.g., same test failure after two edits to the same file), stop. Update `/tasks.json` via `task-status.sh set "<project>" blocked "<what's blocking>"` and notify. **Never attempt a third identical fix.** Something deeper is wrong — investigate or escalate.

## GitHub Actions QA

Read QA run results:
```bash
gh run list --branch main --limit 5
gh run view <id>
```
`GH_TOKEN` is pre-configured in the environment.

## Context Compaction

Long sessions degrade response quality. At natural checkpoints (task done, big milestone, end of a QA iteration cycle), run `/compact` to trim conversation history. **Always before continuing to a new task in the same window.**

## Anti-Patterns

- **Silent completion.** Task done but no `task-status.sh done`, no notify. The user doesn't know to check.
- **Surprise scope blowouts.** Estimated 15 min, it took 3 hours, first the user hears is the completion notify. Update `task-status` halfway through with a revised ETA.
- **Burying an ask in a long response.** If the user needs to do something, `user-action.sh add` it — don't embed in prose.
- **Over-notifying.** Every tool call is not a notification. Milestones only. Otherwise the user's phone becomes noise.

## Integration

- `SKILLS/user-action-tracking.md` — the companion for asks that need the user's manual action.
- `SKILLS/platform-stewardship.md` — "problem solved once, never again" applies here too; surface patterns that save future informing overhead.
- `SKILLS/session-resilience.md` — status files + PROJECT_STATE.md survive chat death; they're the reliable communication surface.
