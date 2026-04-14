# Persona Email — scalable programmatic email identities

## Purpose
Many projects need real, working email addresses for programmatically-created online identities (Carvana accounts, test users, research personas, etc.). Gmail/Outlook signup requires phone verification which defeats autonomy. This skill is the decision tree for when to use which approach, and how to build it.

## Decision ladder (pick the cheapest tier that works for your use case)

### Tier 0 — don't bother (if the target site doesn't require email)
If the target accepts `anystring@anything.com` without validating deliverability, just use a fabricated address and don't build receive infra.

### Tier 1 — free disposable-email APIs (30-second setup, 60% of sites accept)
- **mail.tm** — REST API. Create inbox, read messages, no auth. Free, no rate limits at <100/day.
- **1SecMail**, **GuerrillaMail**, **TempMail** — similar APIs.
- **Caveat**: ~30–40% of consumer sites blacklist these domains as disposable. Good for discovery + sites that don't check; poor for production.
- **Usage sketch**:
  ```python
  import requests
  r = requests.post('https://api.mail.tm/accounts', json={'address': 'test-abc@mail.tm', 'password': 'x'})
  # receive via GET /messages with bearer token
  ```

### Tier 2 — custom persona domain + AWS SES (production-grade, scales to thousands)
When Tier 1 fails blacklist checks OR you need persistent addresses across weeks/months.
- **Domain**: register a dedicated persona domain (not your main project domain). Cost: ~$12/yr via Route 53, NameCheap, or Porkbun. Purpose: isolate from anything with brand value attached — these addresses will occasionally hit spam filters and have their reputation dinged.
- **DNS**: on Cloudflare or Route 53. Need DNS-edit API access for automation.
- **Mail**: AWS SES for send + receive. Receive writes to S3 bucket; a cron or Lambda parses and stores in your project's inbox DB.
- **Aliases**: SES receiving supports catch-all. `*@{domain}` delivers to one bucket. You pick any alias per-persona at runtime.
- **Scaling**: one domain can host thousands of personas. Cost is ~$0.10 per thousand emails received/sent. Free tier covers first 62k/month outbound.
- **One-time setup**: ~2 hrs total — domain register + DNS records + SES verification + prod-access request (AWS approves in 24 hrs).

### Tier 3 — SimpleLogin or AnonAddy on your persona domain (even more flexible)
Adds on-demand alias generation per project. Masters forward to a single inbox you can read via IMAP. Useful when you want ephemeral aliases that can be killed without touching DNS.
- **Cost**: SimpleLogin Premium ~$30/yr on custom domain. AnonAddy Lite free tier works with own domain.

### Tier 4 — Google Workspace with Gmail (only if you need Gmail-reputation deliverability)
- **Cost**: $6/user/month. Overkill for most use cases. Skip unless human-trust of the recipient inbox matters.

## What NOT to use
- **Gmail signup with programmatic phone verification (e.g., Twilio SMS)** — Google detects and banns the account within days.
- **Gmail +addressing on a single account** — many sites (including Carvana) strip `+tags` and treat all `you+anything@gmail.com` as the same address. Can't create multiple accounts.
- **Postfix on the droplet (DigitalOcean host)** — DO blocks outbound port 25 on all droplets. Can receive, can't send.
- **Free Proton / Tutanota** — require phone verification for new accounts.

## Credential requirements

Store under project `.env` or a shared secrets store:

```
PERSONA_EMAIL_DOMAIN=<your persona domain, e.g. "cheapmail.ai">
PERSONA_EMAIL_INBOX_BUCKET=s3://persona-inbox/
AWS_PERSONA_SES_ACCESS_KEY_ID=...
AWS_PERSONA_SES_SECRET_ACCESS_KEY=...
# Or for Tier 1 fallback
MAILTM_USE=true
```

## Reusable helper module

A future `lib/persona_email.js` (Node) or `lib/persona_email.py` (Python) that any project imports:

```python
from persona_email import get_or_create_persona_email, read_inbox

addr = get_or_create_persona_email(name="Catherine Smith", project="car-offers", consumer_id=1)
# -> "catherine.b.smith@cheapmail.ai"  (or "test-abc123@mail.tm" in Tier 1 fallback mode)

# Verification-link scraping:
msgs = read_inbox(addr, since=run_start_time, timeout_sec=120)
for m in msgs:
    if 'verify' in m['subject'].lower():
        link = re.search(r'https://\S+verify\S*', m['body']).group(0)
        # click it
```

## One-time user asks (log them upfront so you can batch)

When setting up Tier 2 for the first time:
1. Pick a persona domain name (suggest: short, generic, not brand-adjacent).
2. Register it (1 click at Route 53 / NameCheap / Porkbun; ~$12/yr).
3. Add DNS records for SES verification + MX + DKIM (can be automated via DNS API).
4. Open AWS console once, request SES production access (unblocks outbound beyond sandbox).

Total human time: ~15 minutes, one-time. After that, every project inherits unlimited persona emails via the shared module.

## Reference implementation

First one will live in car-offers at `car-offers/lib/persona_email.py` once Tier 2 is provisioned. Until then, car-offers uses Tier 1 (mail.tm) as a temporary fallback, gated on whether each target site accepts the domain.

## Failure modes and mitigations

- **Target blacklists your persona domain.** Rotate to a second domain. Cost of having two is still ~$24/yr.
- **Target requires phone verification too.** Escalate to Twilio numbers (~$1 setup + $0.04/text per verification). Document per-target which require this.
- **SES sandbox rejects your sends.** Request prod access (one-time, 24-hr turnaround). Until then only verified addresses receive.
- **Persona domain reputation drops (emails go to spam).** SES per-domain reputation means you can isolate damage. Rotate the persona domain; old addresses still receive.
