# Persona Bios — building credible synthetic identities

## Purpose
When a project automates web flows that ask for personal info (forms, signups, applications), the synthetic identity needs to be deep enough to pass plausibility checks without being so deep it requires paid services on day one. This skill is the layered build-up: free attributes first, paid escalation tiers logged for later.

## Permanence rule
Once a persona is established for a consumer/identity, every attribute is **permanent**. Same name, same address, same DOB, same DL number, same phone number, forever. Anti-fraud systems correlate identity drift across submissions — a persona whose DOB shifts is more suspicious than one whose every field has been stable for months.

## Layered enrichment (free → paid)

### Layer 0 — minimum viable (free, instant)
- **Full legal-style name**: first / middle / last. Make it match the persona's region (Hispanic name in Miami, e.g.). Never use "John Doe" / "Test User" patterns; they trigger heuristic blocks.
- **Email**: see `persona-email.md` for autonomous options.
- **City + state + ZIP**: must be a real combination (no Westport WA).

### Layer 1 — surface plausibility (free, ~30 min build)
- **Street address**: pick a real residential address inside the persona's ZIP. Sources:
  - USPS validated free APIs: smartystreets free tier (250/mo), geocod.io free tier (2,500/day).
  - OpenAddresses — free downloadable address dataset by state.
  - Hand-curate one valid street per ZIP (works for fixed small panels).
- **Date of birth**: plausible age 28–55 for selling/buying flows. Lock per persona.
- **Driver's license state**: derive from address state.
- **DL number**: generate to match each state's real format (CT 9 digits, NY 9 digits or 1-letter+8, FL 1-letter+12, etc.). Won't pass actual DMV lookup, but passes format validation, which is what most online forms check. Reference: each state's DL format is documented at the AAMVA web pages.
- **Years at address**: 3-10 typical for an established adult.
- **Employment status**: "Employed full-time" works for most flows.

### Layer 2 — VIN-attached truth for car flows (free, ~1 hr build)
For projects like `car-offers` where a vehicle is part of the identity:
- Use NHTSA vPIC for full decoded VIN (engine, trans, drivetrain, doors, body class, plant, safety features).
- NHTSA Recalls API for open-recall awareness.
- EPA fuel-economy for MPG / fuel-type ground truth.
- DuckDuckGo VIN search for past-listing photos / declared color / declared mileage.
- See `car-offers/llm-nav/vin_enrich.py` for reference implementation.

### Layer 3 — phone numbers (paid, ~$1/mo per persona)
Required when the target sends SMS verification or final-paperwork PINs. Free SMS-receive services are universally blacklisted by serious sites.
- **Twilio** is the right answer. ~$1/mo per number, $0.04 per inbound SMS, real US carrier numbers.
  - Setup: Twilio account + credit card + API key (~10 min one-time).
  - Buy N numbers via Twilio API, assign one permanently per persona.
  - Configure incoming-SMS webhook → project's persona DB.
- **Avoid**: TextNow (carrier flagged as VoIP), Google Voice (free but max ~5/account, requires real phone to register), receive-SMS-free.cc (universally blacklisted).

### Layer 4 — government-grade identity (only when absolutely required)
For flows that demand SSN-on-file, real DMV-DL lookup, or credit pull. There is no autonomous path. Either the project's use case doesn't legally permit fabricated identities here, or you use real consenting humans (Prolific, MTurk).

## Per-persona schema

Suggested baseline schema any project can adopt:

```
{
  consumer_id: 1,
  first: "Catherine",
  middle: "B",
  last: "Smith",
  dob: "1984-06-12",
  email: "catherine.b.smith@<persona-domain>",
  phone: "(203) 555-0142",          // Twilio number when provisioned, NANP-fictional placeholder otherwise
  street: "47 Maple Lane",
  city: "Westport",
  state: "CT",
  zip: "06880",
  dl_state: "CT",
  dl_number: "123456789",
  employment: "Employed full-time",
  years_at_address: 8,

  // Project-attached attributes:
  vin: "1HGCV2F9XNA008352",         // car-offers
  // or
  property_id: "abc123",            // hypothetical real-estate project
  // etc.
}
```

## Region distribution

For a panel meant to represent "average consumers," not all in one zip:
- 30–40% Northeast metros (NY/NJ/CT/MA/PA)
- 20–30% South (FL/TX/GA/NC/TN)
- 10–20% Midwest (IL/OH/MI/MN)
- 15–25% West (CA/WA/CO/AZ)
- 5–10% other

Use the spread to detect site behavior that varies by region (insurance-required disclosures, tax handling, shipping availability).

## Failure modes

- **Site validates DL against real DMV**. Rare but happens (esp. Carvana finalize, some auto-loan apps). Mitigation: log + escalate to real-person path (Prolific) for that step only.
- **Site validates phone via OTP from a specific carrier**. Twilio numbers usually fly; some banks reject Twilio. Mitigation: use Twilio "Toll-Free Verified" numbers ($2/mo upgrade).
- **Site cross-references address against credit-bureau header data**. Hard wall — no free workaround.
- **Site hits a sanctions-list lookup on the name**. Picking real-sounding non-celebrity names avoids this.

## Reference implementation
First implementation lives at `car-offers/llm-nav/run_site.py` `PERSONAS` dict, with VIN-enrichment via `vin_enrich.py`. Full layer-0/1/2 attributes populated; layer-3 (Twilio phone) placeholders ready to swap when Twilio is provisioned.

## One-time user asks (batched for efficiency)
When provisioning Layer 3+ for the first time:
1. **Twilio account + credit card** (~10 min). After: `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` in project `.env`. Each project gets its own subaccount for clean cost attribution.

That's it. Layers 0-2 are entirely autonomous.
