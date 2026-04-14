# Driveway — sell-your-car wizard knowledge

## Status: BLOCKED on first page (bot detection before any form interaction)

First LLM-nav attempt 2026-04-14 14:15 UTC on Consumer 5 (Miami Beach 2022 Civic, VIN 19XFL2H88NE021488, zip 33139) hit Driveway's "Whoops! Something went wrong" modal 129 seconds into the run, immediately after VIN submission. This is the same signal earlier Builder runs saw — Driveway's detection is fingerprint + IP level, not selector level.

## Start URL
`https://www.driveway.com/sell-your-car` (the shorter `/sell` 404s).

## What the agent saw (brief, from trace)
- Landing page loaded.
- VIN/License-plate tab toggled to VIN.
- VIN entered.
- "Get an Offer" clicked.
- Immediate error modal: "Whoops! Something went wrong. Please refresh your page and try again." with a "support@driveway.com" link.

## Diagnosis

Three scenarios, ordered by likelihood:

1. **IP on threat-intel feed.** Driveway subscribes to IPQualityScore or similar, Decodo's IP for Consumer 5 scored >0.8 proxy-risk. Instant block.
2. **Fingerprint flag.** Our Patchright/stealth fingerprint triggers a heuristic Driveway uses. Less likely because the page loaded and accepted the VIN input — fingerprint blocks usually kill the page earlier.
3. **Backend VIN rejection masquerading as a generic error.** Driveway's own odometer/vehicle lookup might have failed and returns the generic "Whoops" instead of a specific error.

## Retry strategy (in flight as of 2026-04-14 14:39 UTC)

- **Different consumer**: Consumer 4 (Cambridge MA 2023 Elantra, different IP, different fingerprint, different VIN). Rules out VIN-specific rejection and IP-specific flag.
- **Extended warmup**: 20 minutes browsing driveway.com/shop inventory, reading the "why choose Driveway" page, scrolling the blog — building a legitimate session history before the sell flow.
- **Slower agent cadence**: `max_actions_per_step=1`, human-persona prompt, 10–30s read pauses.

## If the retry also blocks

Driveway's detection is structural, not incidental. Escalate:
- **Paid human baseline** (Prolific study for Driveway — ~$50, 5 testers): gives us narrated recordings + verifies a real human can even complete the flow from our geography.
- **Alternative fingerprint stacks**: try camoufox (Firefox-based) instead of Patchright. Different TLS signature, different JS runtime, may slip past Driveway's WAF that's tuned for Chromium-stealth.
- **Rotate proxy provider**: some of Decodo's US residential pool is aggressively blacklisted. Try a second provider (IPRoyal, Oxylabs) for Driveway specifically.

## Consumer health on Driveway
- Consumer 5 (33139): **flagged** — instant bot modal. Quarantine 7d.
- Consumer 4 (02139): unknown — retry in flight.
