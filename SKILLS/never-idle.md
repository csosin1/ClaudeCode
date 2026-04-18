---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Never Idle

## When to use

Use this skill when working on never idle. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**The user's time is the scarce resource on the platform.** Do not end a turn waiting for permission when any useful work remains. Build in parallel with asks outstanding.

## Blocker Brief (at task start)

While the user is still paying attention, enumerate every permission, secret, external account, domain, or piece of information you'll need across the full task. Ask for them all in one batch. Examples:
- GitHub token scopes.
- API keys (Stripe, Anthropic, OpenAI, etc.).
- Third-party logins (Auth0, Cloudflare, SendGrid).
- DNS control.
- Billing setup.
- Access to existing data sources.

File the items via `user-action.sh add …` so they don't get buried in chat.

## Work Around Blockers

While waiting for answers:
- Scaffold files, write stubs and mocks, set up tests.
- Write docs and spec the integration.
- Research the library or API.
- Build the infrastructure that doesn't touch the pending items.
- Leave clean hooks (clearly marked `TODO: fill <ITEM>` or `os.environ["KEY"]`) so the blocking pieces slot in when answers arrive.

If you discover a new blocker mid-work, add it to the running brief, pivot to unblocked work, batch the new ask with any pending ones. Never stop and wait.

## Never Emit These Phrases

- "Want me to continue?"
- "Should I proceed?"
- "Tell me if …"
- "Let me know and I can …"

If a decision is genuinely irreversible or externally visible, state the plan explicitly and execute unless stopped.

## Legitimate Reasons To End A Turn

- Everything is blocked on user input AND no unblocked work remains.
- Task is complete and QA is green.
- Scope has exploded into work that warrants a revised estimate (call it out explicitly; don't just keep going silently past a 200k-token budget — see `SKILLS/user-info-conventions.md § Token-Cost Guardrail`).

## Integration

- `SKILLS/user-action-tracking.md` — how to file pending asks.
- `SKILLS/non-blocking-prompt-intake.md` — sibling rule for handling new prompts during active work.
- `SKILLS/user-info-conventions.md` — the token-cost and stuck-detector guardrails that override "never idle" when they trigger.
