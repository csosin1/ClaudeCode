# Skill: Accounts Registry

## Guiding Principle

**Every third-party account or subscription has one canonical record.** The user never has to wonder "do I have a Stripe account for this? What's the login? Where are the keys?" It's in one place.

## What This Skill Does

Tracks all accounts and subscriptions the platform uses — service name, purpose, URL, credential location, monthly cost — with a mobile-visible page at `https://casinv.dev/accounts.html`. Renders the same data into `/opt/site-deploy/ACCOUNTS.md` (human-readable and versioned in git).

## When To Use It

- **Immediately after signing up for a new service.** Add it before touching any code that uses it.
- **When rotating credentials.** Update the `cred_location` field.
- **When cancelling a subscription.** Mark it cancelled; don't delete — the history matters for audits.
- **When auditing costs.** `account.sh list` shows everything and the dashboard sums monthly totals.

## How To Use It

### Register a new account

```bash
/usr/local/bin/account.sh add \
  <service> \
  <one-line-purpose> \
  <url> \
  "<where the credential lives>" \
  [monthly-cost]
```

Examples:
```bash
/usr/local/bin/account.sh add \
  "Stripe" \
  "Payment processing for car-offers checkout" \
  "https://dashboard.stripe.com" \
  "STRIPE_SECRET_KEY in /opt/car-offers/.env" \
  "2.9% + 30¢/txn"

/usr/local/bin/account.sh add \
  "Cloudflare" \
  "DNS + CDN for casinv.dev" \
  "https://dash.cloudflare.com" \
  "CF_API_TOKEN in /opt/site-deploy/.env (deploy-only)" \
  "\$0"
```

Fires a notification so the user sees the new account on their phone. Re-adding the same service name **replaces** the entry (idempotent).

### List or inspect

```bash
/usr/local/bin/account.sh list               # all accounts, status-grouped
/usr/local/bin/account.sh show Stripe        # one account, full JSON
```

### Cancel

```bash
/usr/local/bin/account.sh cancel <service>
```

Keeps it in the record, moves it to the Cancelled section on the dashboard.

## What To Record

For each account, capture:

- **service** — canonical name ("Stripe", not "payment processor").
- **purpose** — one line, why we're using it, specific to our use case.
- **url** — the dashboard or login page (plain URL, no markdown wrapping — iOS URL detection needs it clean).
- **cred_location** — exact path to the credential. Env var name + which `.env` file, or "stored only in GitHub Secrets as $FOO", or "API key is the login — no separate credential."
- **monthly_cost** — approximate is fine. Use "usage-based" or "\$0" when applicable.

If a service has multiple credentials, list all of them in the `cred_location` field — or split into multiple entries if they serve different purposes.

## Rules

1. **Register before use.** Sign up → register in the tracker → write code. Never in a different order. If you wire up a service and only later realize no one tracked it, stop what you're doing and register it.
2. **One canonical record per service.** Not one per project that uses it. Reuse via `cred_location` listing multiple locations.
3. **Credentials never in git.** Only the *location* goes in the registry. The value stays in `/opt/<project>/.env` (gitignored) or GitHub Secrets.
4. **Cancel, don't delete.** If the user cancels a subscription, `account.sh cancel` — the history stays for audits.

## Anti-Patterns

- **Tribal knowledge.** "Oh yeah, we have an X account from last month." If it's not in `account.sh list`, it doesn't exist for the purposes of the platform.
- **Vague purpose.** "APIs" is not a purpose. "Sending transactional emails from car-offers" is.
- **Orphan credentials.** Env vars in `.env` files with no corresponding account registry entry. Every credential has a service it belongs to; register the service.

## Integration

- Companion: `SKILLS/user-action-tracking.md` — when the user needs to sign up for a new account, file a user-action with the steps, and have the verification step include `account.sh add` after the signup completes.
- State: `/var/www/landing/accounts.json` (machine-readable) and `/opt/site-deploy/ACCOUNTS.md` (human, versioned).
