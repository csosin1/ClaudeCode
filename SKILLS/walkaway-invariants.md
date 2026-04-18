---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Walk-Away Invariants — the platform's always-on defaults

## When to use

Every session. These are not opt-in behaviours and there is no "Unattended Mode" toggle that turns them on — they are how the platform works. Read this when you're about to design or review any interaction pattern, notification, cost surface, or acceptance card, to check that the pattern still holds when the user has walked away mid-engagement.

## The invariant set

User operates from iPhone in bursty sessions separated by potentially long dormancy (see `feedback_walkaway_default.md` and `user_usage_pattern.md` in the user's memory). Any behaviour that requires "user is watching right now" to degrade gracefully is a bug. The following seven invariants are always-on:

### 1. Never assume the user is watching

The assumed baseline is "user may be gone." Agents behave **identically** whether the user is actively reading or has put their phone down mid-sentence. No per-engagement "I'm here / I'm gone" signal exists; building one would introduce exactly the friction the platform is meant to remove.

### 2. Never emit "want me to continue?" or equivalents

Extension of the `SKILLS/never-idle.md` rule to the whole platform. A turn that ends with a yes/no question mid-work stalls silently whenever the user has walked away. The only legitimate turn-endings are the three named in `SKILLS/never-idle.md` § *Legitimate Reasons To End A Turn*.

### 3. Milestone boundaries produce structured Accept cards, not chat paragraphs

When a deliverable is ready for user review, emit a persistent Accept card via `helpers/accept-card.sh` — not a paragraph summary in chat. Cards render at a stable URL under `https://casinv.dev/accept-cards/<id>.html`, so a user returning days later can still see and act on them. Mid-work updates that aren't milestone boundaries use `heartbeat`-tier notifications, not cards.

### 4. Notification priority tiers always route

Three tiers, always-on, no mode gating:

- **critical** — ntfy priority 5, vibrate. Blocker requires user OR an irreversible-action pause card is ready.
- **milestone** — ntfy priority 3, default push. A deliverable is ready for Accept.
- **heartbeat** — ntfy priority 1, silent. Long-running work emits periodic state pulses; ignorable by design.

Implementation: `helpers/notify.sh --tier {critical|milestone|heartbeat}`. Full routing spec in `SKILLS/notification-tiers.md`.

### 5. Irreversible-action HITL list always blocks

Certain actions always pause for explicit user approval regardless of context, agent, or mode. Canonical list in `SKILLS/irreversible-actions.md`. The list covers outside spend, destructive data ops, production promotion (including small fixes — the user explicitly opted for this), external reach, security/identity changes, and data leaving our control. Preview deploys, code edits, feature-branch pushes, and any dev-droplet change flow freely.

### 6. Outside-spend cost cap approved at task launch, never mid-work

**Tokens are not a cost surface.** Claude Max covers them. The only "cost" the platform surfaces is third-party spend (paid APIs, cloud beyond our droplets, domains, certs, vendor fees). Outside-spend approvals happen at task kickoff with a declared cap; mid-work cost pings for tokens are forbidden. If mid-task outside spend approaches the declared cap, pause for re-approval rather than silently truncate. See `feedback_cost_model.md` in the user's memory; enforcement lives in `helpers/paid-call`.

### 7. Heartbeat pulses default-on for work > ~5 min wall-clock

Any job with expected wall-clock >~5 min emits silent `heartbeat`-tier pings at natural checkpoints (sub-task boundaries, periodic every ~10 min). Silent means the user ignores them unless they pull; no vibration, no sound. This gives a returning user an at-a-glance "still moving / stalled" signal without any mid-work interruption.

## Why these are invariants, not a mode

A mode toggle would mean: forget to set it → work stalls waiting for a user who won't return for days. The cost of the forget-to-toggle failure is catastrophic (wasted hours of in-flight state); the cost of the invariants being always-on is near-zero (a few extra notification routing decisions, a couple of structured cards instead of chat paragraphs). Asymmetric payoff → always-on.

Walk-away is the fallback that survives the ugliest-case. Designing to the worst case means the best case (user is watching) works identically and no one has to think about mode state.

## How this interacts with other skills

- `SKILLS/never-idle.md` — the no-"want me to continue?" rule (#2 above) is the platform extension of never-idle's turn-ending rules.
- `SKILLS/notification-tiers.md` — expansion of invariant #4 with concrete `helpers/notify.sh` flags.
- `SKILLS/irreversible-actions.md` — canonical HITL list, expansion of invariant #5.
- `SKILLS/dual-surface-parity.md` — Accept cards must render on both mobile (390px) and desktop (1280px).
- `SKILLS/acceptance-rehearsal.md` — the journey-narrative consumer of milestone cards.
- `SKILLS/costly-tool-monitoring.md` — the `paid-call` wrapper that enforces invariant #6.

## Anti-patterns

- A reviewer rule that only catches a regression "if the user happens to read the PR" — invariant #5 says build a mechanical gate instead.
- A kickoff prompt that says "let me know if you want me to proceed" — invariant #2 forbids; state the plan and execute unless stopped.
- A mid-work "this is using ~$0.40 of tokens so far" notification — invariant #6 forbids; tokens are not a cost surface.
- A `~/TODO.md` that is the only record of a deliverable — invariant #3 says emit a persistent Accept card at `/var/www/landing/accept-cards/<id>.html`.
