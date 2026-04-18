---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Notification Tiers — critical / milestone / heartbeat

## When to use

Every time you're about to notify the user via `helpers/notify.sh`. Pick a tier before you pick a message — the tier determines whether the phone vibrates, pushes silently, or just updates a state without interrupting. Picking the wrong tier is worse than not notifying: a heartbeat dressed as critical trains the user to ignore vibrations, and a critical dressed as heartbeat gets missed.

These three tiers are always-on per `SKILLS/walkaway-invariants.md` invariant #4. There is no mode gating them.

## The three tiers

### `critical` — ntfy priority 5, vibrates

Use when: the agent is fully blocked on user decision AND the decision is irreversible (see `SKILLS/irreversible-actions.md`). Examples:
- Outside-spend approaching cap; need re-approval before next paid call.
- Production promotion ready; waiting for "ship it."
- Destructive operation detected; paused waiting for explicit accept.
- Task kickoff itself requires outside-spend approval.

Payload: short title, one-line outcome, Click header pointing at the Accept card URL. User sees the vibration even if the phone is in their pocket.

Command: `helpers/notify.sh "<msg>" "<title>" --tier critical --click <url>`

### `milestone` — ntfy priority 3, default push

Use when: a deliverable is ready for Accept, user review is wanted but not urgent, dormant-user-returns-in-three-days is acceptable. Examples:
- Feature built, preview URL ready, QA green.
- Research leg finished, findings ready to read.
- Long job completed normally.

Pairs with an Accept card at `https://casinv.dev/accept-cards/<id>.html`. Use `helpers/accept-card.sh` which emits this tier automatically.

Command: `helpers/notify.sh "<msg>" "<title>" --tier milestone --click <url>`

### `heartbeat` — ntfy priority 1, silent

Use when: long-running work is progressing, user might want to glance but should not be interrupted. Examples:
- Sub-task boundary crossed in a multi-hour job.
- Periodic pulse every ~10 min during a scrape / build.
- "Still running, on step 4 of 7, no issues."

Silent means the phone's notification drawer updates but there's no vibration or sound. Walk-away-by-default means the user ignores heartbeats unless they pull — and that's correct.

Command: `helpers/notify.sh "<msg>" "<title>" --tier heartbeat`

## Wiring

`helpers/notify.sh` accepts `--tier {critical|milestone|heartbeat}` which maps to ntfy priority 5 / 3 / 1 respectively. Legacy positional-arg form (`notify.sh "msg" "title" default`) still works for backward compatibility; new code MUST use `--tier`. When both forms are supplied, `--tier` wins.

Anti-pattern to watch: `helpers/notify.sh "msg" "title" urgent` (legacy string priority) when the underlying event was a heartbeat. Reviewers should flag any `urgent`/`high` priority notification that doesn't correspond to a blocker or an irreversible-action pause.

## Decision rubric

When in doubt, ask "if the user is asleep, which answer is least wrong?":
- Action is irreversible and blocked → **critical** (waking someone up for a real block is correct).
- Work is done, can wait → **milestone** (push but don't vibrate).
- Work is continuing, informational → **heartbeat** (silent).

## Related

- `SKILLS/walkaway-invariants.md` — invariant #4; the always-on tier routing.
- `SKILLS/irreversible-actions.md` — the list that justifies a `critical`-tier pause.
- `helpers/notify.sh` — the emitter, with `--tier` flag.
- `helpers/accept-card.sh` — wraps `milestone`-tier notifications around a persistent card.
