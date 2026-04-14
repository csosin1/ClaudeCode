# Skill: Paid Human Loop (Prolific + MTurk)

## What This Skill Does

When automation hits a wall — bot detection, a form that keeps changing, a site nobody has fully mapped — you pay real humans to do the task while screen-recording. Their recordings become your ground-truth specification: exact selectors, exact field order, exact prompts. Then you either automate from that spec, or keep the humans in the loop for ongoing validation.

## When To Use Which Platform

| Use case | Platform | Why | Typical price |
|---|---|---|---|
| One-time deep walkthrough with narration | **Prolific** | Vetted panel, better English, willing to narrate, 5–20 min jobs work | $8–$15 per participant |
| Ongoing spot-check ("run this VIN, tell us the number") | **MTurk** | Large worker pool, cheap, fast turnaround, no narration expected | $2–$5 per assignment |
| Anything with video/audio upload requirements | **Prolific** | Participants are used to screen-recording tasks; MTurk workers resist it | — |
| Near-realtime validation (need 10 answers in an hour) | **MTurk** | Deeper worker pool, most jobs fill in <30 min | — |

Rule of thumb: if reward per task is ≥ $8, Prolific. Under $5, MTurk. The $5–$8 middle is a judgment call — if you need narration, pay up and go Prolific.

## Writing a Brief

A brief is a small JavaScript module (see `car-offers/lib/briefs/` for examples):

```js
module.exports = {
  title: 'Short, action-oriented. First 10 words matter most.',
  description: 'One paragraph on WHAT they're doing and WHY it exists.',
  steps: ['Step 1', 'Step 2', '...'],
  success_criteria: 'Exact, verifiable, list-check-able. No fuzzy adjectives.',
  reward_usd_cents: 1000,          // integer cents, always
  participants: 5,                 // Prolific places / MTurk MaxAssignments
  max_minutes: 20,                 // time cap per participant
  prefer: 'quality',               // 'quality' | 'volume' | 'auto'
  external_url: 'https://...',     // where the participant goes
};
```

Key principles:

- **Steps are a checklist, not a paragraph.** Participants scan, they don't read.
- **Success criteria is what gets people rejected.** Be explicit: "Video at least 5 minutes" not "reasonably thorough".
- **STOP conditions** protect the worker and your budget: tell them where to stop so they don't try to buy something.
- **No personal data.** Never ask the participant to enter their own email/phone/card. Use a VIN you own or a test account.
- **Pay fairly.** Prolific enforces $9/hr minimum. MTurk doesn't, but underpaying is unethical and gets you a bad reputation.

## Credential Setup

### Prolific

1. Create researcher account at https://www.prolific.com
2. Fund the account from Settings → Billing. Minimum $50 useful ($250 typical first-run budget).
3. Generate an API token: Settings → API → Generate new token.
4. Paste into your app's `/setup` (or drop into `/opt/<project>/.env` as `PROLIFIC_TOKEN=...`).
5. Set `PROLIFIC_BALANCE_USD` to whatever you funded — this is the per-process guardrail cap.

### MTurk (Amazon Mechanical Turk)

1. Have an AWS account in good standing.
2. Create a Requester account at https://requester.mturk.com (separate from aws.amazon.com — same AWS account, different portal).
3. Pick a requester display name that doesn't sound automated (e.g. "Used Car Research", not "HIT Bot v3").
4. Fund the requester account: Profile → Funds → add (minimum $100 is typical).
5. Create an IAM user with the `AmazonMechanicalTurkFullAccess` policy, generate an access key pair.
6. Paste `MTURK_ACCESS_KEY_ID` + `MTURK_SECRET_ACCESS_KEY` into `/setup`.
7. Set `MTURK_BALANCE_USD` — this is the per-process guardrail cap.

## Budget Guardrails

Every client enforces a hard cap:

```js
const client = createProlificClient({ token, balanceCapUsd: 300 });
// If running_spend + next_planned > 300, the call throws before hitting the network.
```

The running-spend counter is process-local — a restart resets it. The real protection is the **funded balance** on Prolific/MTurk itself. Never fund more than you're comfortable spending in a 24-hour window while the code is being iterated on.

## Typical Costs (2026 numbers)

| Job | Platform | Reward | Participants | Subtotal | Platform fee | **Total** |
|---|---|---|---|---|---|---|
| 10-min site walkthrough w/ narration | Prolific | $10 | 5 | $50 | ~33% | **~$67** |
| 2-min validation check | MTurk | $3 | 1 | $3 | ~20% | **~$3.60** |
| 2-min validation, 20 assignments | MTurk | $3 | 20 | $60 | ~20% | **~$72** |

Ongoing-validation monthly cost for one site, 30 MTurk audits: roughly **$110/month**.

## Canonical Example

See `/opt/site-deploy/car-offers/` for the reference implementation:

- `lib/prolific-client.js` — REST client, budget guardrail
- `lib/mturk-client.js` — aws-sdk wrapper, same guardrail shape
- `lib/humanloop.js` — routes briefs to the right platform, persists to SQLite
- `lib/briefs/*.js` — one file per brief template
- `server.js` routes: `POST /api/humanloop/fire-baseline/:site`, `GET /api/humanloop/jobs`, `POST /api/humanloop/harvest/:jobId`

## Gotchas

- **Prolific studies default to DRAFT.** `postBriefedJob()` does NOT auto-publish unless you pass `autoPublish: true`. This is deliberate — draft studies don't cost money. Go to prolific.com and click Publish after reviewing.
- **MTurk ExternalQuestion requires HTTPS.** A plain-HTTP URL will be rejected by the SDK client here.
- **MTurk is us-east-1 only.** The SDK lets you pick a region; don't.
- **Prolific rebrand:** use `api.prolific.com`. The old `api.prolific.co` 301s — most clients handle it, but some HTTP libs don't follow 301s on POST. Ours does.
- **Rejections hurt workers.** On MTurk especially, a reject affects the worker's approval rate and their eligibility for future work. Reject only when you can specifically describe why — the message field shows up in their notification.
