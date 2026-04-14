# Skill: Capacity Monitoring

## Guiding Principle

**The user can add compute — but only if an agent tells them in time.** Silent thrashing is the worst outcome: the platform stays up but degrades everything, and no one realizes why.

## What This Skill Does

Tracks RAM, swap, disk, and CPU load on the droplet every 5 minutes. Publishes `/var/www/landing/capacity.json`, renders it at `https://casinv.dev/capacity.html` with a severity banner, and fires urgent phone notifications when thresholds breach. The `/projects.html` nav bar lights up orange (warn) or red (urgent) so it's visible from any session.

## When To Use It

- **Before heavy work** — batch scraping, model training, large Playwright runs, concurrent builds. Check `/capacity.json` first; if already warn or urgent, flag it to the user instead of adding load.
- **After noticing slow operations** — if tool calls feel sluggish, capacity is the first thing to check before blaming anything else.
- **In RCA investigations** — many "it's flaky" or "the deploy failed" incidents are really "the box was swapping at 100%."

## Thresholds (in `capacity-check.sh`)

| Metric | Warn | Urgent | Notes |
|---|---|---|---|
| RAM %     | 75%  | 90%  | Available — not cache-included. |
| Swap %    | 25%  | 75%  | Any swap use = RAM pressure. High swap = thrashing. |
| Disk %    | 70%  | 85%  | Rises slowly; easy to keep ahead of. |
| Load 15m  | 1.5× cores | 3.0× cores | 15-minute load avg; the short-term load fluctuates. |

Thresholds are intentionally conservative — the cost of a false-positive notification is a phone buzz; the cost of a silent overload is hours of thrashing and failed tasks.

## How To Check From An Agent

```bash
# Quick check inside any chat before spawning new load
curl -s https://casinv.dev/capacity.json | jq '.overall, .ram.pct, .swap.pct, .load.ratio'
```

If `.overall` is `"urgent"`:
1. Do not start new heavy work.
2. Check whether a process you control is part of the load (`ps aux --sort=-%mem | head -10`).
3. Notify the user with a concrete recommendation (see below).
4. If the user has authorized trimming, kill the safe-to-kill processes (headless browsers that are already done, dangling Playwright workers, caches that will regenerate).

## Notification Policy

- Transition to **warn**: one `default`-priority notify.sh.
- Transition to **urgent**: one `urgent`-priority notify.sh.
- While stuck at the same severity: re-alert every 30 min max (debounced by state file in `/var/run/claude-sessions/capacity-*.state`).
- Recovery to **ok**: one `default` "recovered" notify.

## Upgrade Guidance

When urgent is sustained across sustained resource classes, the fix is a bigger droplet. Rough DigitalOcean sizing:

| Current → Next | vCPU | RAM | Disk | Monthly | Good for |
|---|---|---|---|---|---|
| `s-2vcpu-4gb` (current) | 2 | 4 GB | 80 GB | ~$24 | idle platform + 1 active chat |
| `s-4vcpu-8gb` | 4 | 8 GB | 160 GB | ~$48 | 3-4 active chats + light scraping |
| `s-4vcpu-16gb` | 4 | 16 GB | 200 GB | ~$84 | heavy scraping / multi-browser work |
| `s-8vcpu-16gb` | 8 | 16 GB | 320 GB | ~$96 | concurrent builders + subagent fan-out |

DigitalOcean droplets can be resized live with a few minutes of downtime; no rebuild needed. Disk can only be resized up, never down.

## Integration

- `/projects.html` nav bar shows capacity severity — user sees it on every page load without tapping in.
- `capacity-check.sh` wired via `/etc/cron.d/claude-ops` every 5 min; versioned at `helpers/capacity-check.sh`.
- Companion: `SKILLS/root-cause-analysis.md` — capacity pressure is a frequent underlying cause for "flaky" behavior; always rule it in or out first.
