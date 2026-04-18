---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Irreversible Actions — the HITL list

## When to use

Before executing any action that could affect outside spend, persistent data, production service state, external humans, security posture, or data leaving our control. If the action you're about to run appears (explicitly or by analogy) on the list below, pause and emit a `critical`-tier Accept card via `helpers/accept-card.sh` — do not proceed until the user explicitly clicks Accept.

This list is the canonical, user-approved HITL scope. It is not an advisory — every item always blocks, in every chat, regardless of mode. The "walk-away is default" invariant (`SKILLS/walkaway-invariants.md`) means the list must work identically whether the user is watching or not.

## The list

### Outside spend

- Any third-party paid API call **beyond the cap approved at task launch**.
- New paid service / subscription sign-up.
- New cloud resources incurring real cost — droplet upgrade, block storage, bandwidth overage, managed DB, etc.
- Domain purchase or renewal; SSL cert purchase.
- **Task kickoff itself**: if outside spend is expected during the task, approval + cap is required before dispatch, not after the first dollar.

*Why on the list:* spend, once incurred, doesn't come back. Token cost is free under Max; outside spend is the only real "cost" dial.

### Destructive data operations

- `DROP TABLE`, `TRUNCATE`, or destructive SQL on any persistent store.
- `rm -rf` on shared paths or anything under `/opt/*/data/` or `/var/*/`.
- Deleting a git branch with unmerged commits.
- `git push --force` to `main` or any published branch.
- Database migrations on prod that drop or alter columns on populated tables.

*Why on the list:* loss of data isn't patch-and-restore-able — there's no rollback from "rows are gone."

### Production promotion (all require HITL, including small fixes)

- Promoting preview → live (preserves the "ship it" Accept gate).
- Rolling back prod to a prior tag.
- Disabling a running prod service.
- Any change to `/etc/nginx/` on the prod droplet. Dev nginx stays free.
- Any change to `/etc/systemd/system/` on prod. Dev systemd stays free.

*Why on the list:* user explicitly chose this scope. Small-fix auto-promote was considered and rejected — the "ship it" moment is the one consistent feedback gate in the platform, and erosion of it is one-way.

### External reach (any other human sees it)

- Outbound email, Slack, Discord, SMS, tweets, or any channel reaching people.
- Public GitHub operations — opening PRs or issues on repos that aren't ours, commenting on them.
- Anything that pings other users of external services.

*Why on the list:* once another human sees a message from us, there's no undo. Reputation surface is not patchable.

### Security / identity

- Creating or rotating long-lived API keys.
- Adding SSH keys to the droplet.
- Firewall (ufw / iptables) changes.
- nginx auth, allowlist, or rate-limit changes on prod.
- DNS record changes.

*Why on the list:* the blast radius of a security regression is the whole platform. Cost of a second-look is a ~30-second pause; cost of a missed regression is catastrophic.

### Data leaving our control

- Uploading logs, database dumps, or user data to third-party tools (paste services, debugger clouds, external AI APIs).
- Sharing `PROJECT_CONTEXT.md` or similar docs outside our droplet.

*Why on the list:* once data leaves, we cannot un-leak. Privacy / confidentiality is one-way.

## Explicitly NOT on the list (flows freely, no HITL)

- All preview deploys. Preview is cheap, scoped, and reversible.
- All code edits, tests, commits, feature-branch pushes.
- Creating new projects or repos on the droplet.
- Running installed tools, local file operations.
- Any dev-droplet change (dev nginx, dev systemd, dev cron, dev rsync).
- Preview-only schema migrations and data resets in dev.

If the action is on this list, the builder must proceed without pausing. Over-pausing is friction — the HITL list is deliberately bounded.

## How this is enforced

Defense in depth — four independent mechanisms, each catching the class the others might miss:

1. **Reviewer rule lookup.** `.claude/agents/infra-reviewer.md` checks every diff against this list. An action on the list that lacks an Accept-card receipt in the PR / commit narrative is a FAIL. The review step is mechanical: match the diff's actions against the list, confirm a corresponding card id exists.

2. **Paid-call wrapper (`helpers/paid-call`).** Every outside-spend API call routes through this wrapper, which refuses (exit 127) when cumulative + est_cost_usd would exceed the cap declared at task launch. This covers the "beyond the cap" and "unexpected outside spend" shapes in the Outside-spend section. See `SKILLS/costly-tool-monitoring.md`.

3. **Pre-commit hooks (`helpers/install-pre-commit.sh` installs).** `helpers/doc-reality-check.sh` + `helpers/lessons-lint.sh` + `helpers/skills-shape-lint.sh` catch the doc-drift family. They are not, today, HITL gates for the action list itself — extending pre-commit to block `git push --force` or prod-nginx edits is a candidate for the next hardening pass.

4. **ntfy `critical`-tier wiring.** When an agent emits `helpers/notify.sh --tier critical` (priority 5, vibrate), the message reaches the user's phone regardless of whether they were watching. Combined with a persistent Accept card at `https://casinv.dev/accept-cards/<id>.html`, a blocked action surfaces whether the user responds in 30 seconds or three days.

## Related

- `SKILLS/walkaway-invariants.md` — the always-on invariant set that makes this list load-bearing.
- `SKILLS/notification-tiers.md` — the `critical` tier that routes HITL pauses.
- `SKILLS/costly-tool-monitoring.md` — the paid-call wrapper enforcing outside-spend caps.
- `SKILLS/acceptance-rehearsal.md` — narrative anchoring for milestone (not blocker) cards.
- `helpers/accept-card.sh` — the card emitter.
- `helpers/paid-call` — the spend wrapper.
