---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: User-Action Tracking

## When to use

Use this skill when working on user-action tracking. (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## Guiding Principle

**Never ask the user for something manual and then assume it's done.** If the action isn't programmatically verifiable by you, it belongs in the tracker, not buried in the chat.

## What This Skill Does

Tracks manual actions the user must perform (account signups, clicking UI buttons, pasting credentials, approving external requests) so they can't be forgotten. Produces a mobile-visible to-do list at `https://casinv.dev/todo.html` with a counter badge on the projects dashboard.

## When To Use It

Any time you're about to tell the user "please do X" where X happens outside the terminal. Examples:
- "Sign up for a Stripe account and paste the publishable key here."
- "Go to the Cloudflare DNS panel and add a TXT record."
- "Authorize the Gmail OAuth prompt when it opens."
- "Add the admin user in the Supabase dashboard."
- "Enable the Google Maps API in your Cloud Console."

## How To Use It

### Add a pending action

```bash
/usr/local/bin/user-action.sh add \
  <project-slug> \
  "<short title, one line>" \
  "<numbered step-by-step instructions, \\n separated>" \
  "<how you will verify — what you'll run or check to confirm done>"
```

Returns an action id (e.g. `ua-3a8edadb`). A push notification fires to the user's phone.

Example:
```bash
/usr/local/bin/user-action.sh add \
  timeshare-surveillance \
  "Add SMTP app-password for alert emails" \
  "1. Go to https://myaccount.google.com/apppasswords\n2. Create a password for 'timeshare-alerts'\n3. Paste it at https://casinv.dev/timeshare-surveillance/admin/" \
  "I'll GET /admin/ping and confirm SMTP_PASSWORD is set in .env"
```

### Check what's pending at the start of a session

Always run this at the top of any session before assuming prior asks are complete:
```bash
/usr/local/bin/user-action.sh remind
```

If anything in the list is relevant to the current session, attempt verification before doing new work that depends on it.

### Mark done — only after verification

```bash
/usr/local/bin/user-action.sh done <id>
```

**Before calling `done`, you must verify independently.** Curl the endpoint, read the env var, query the service's API, whatever the `verify_by` field described. Don't trust "I did it" from the chat — verify.

### Cancel if no longer needed

```bash
/usr/local/bin/user-action.sh cancel <id>
```

## Rules

1. **One action per ask.** If you need the user to do three things, file three actions. Individually trackable, individually verifiable.
2. **Steps must be runnable by a non-technical person on iPhone.** Plain prose, one action per numbered step, plain URLs (no markdown formatting — iOS tap detection chokes on it).
3. **Verification must be something *you* can run.** Not "confirm with me." A curl, a grep, an API check, an explicit page load that returns 200.
4. **Check the list at session start.** `user-action.sh remind` before deciding whether past asks are complete.
5. **Don't batch-close.** Each `done` is one verification. If you haven't verified, don't call done.

## Anti-Patterns

- **Assuming completion from chat context.** "They said they did it last session" ≠ done. Verify.
- **Vague verification.** `verify_by: "confirm with user"` is useless; that's exactly what the tracker is avoiding.
- **Bulk-cancelling stale entries.** If something's been pending a week, nudge the user once, don't silently cancel.
- **Adding the same action twice.** Check `user-action.sh list` first.

## Integration with Other Tools

- Notifies the user via `notify.sh` on every `add` and `done` — they see it on their phone immediately.
- Counter badge on `https://casinv.dev/projects.html` shows pending count.
- State is at `/var/www/landing/pending-actions.json`, served at `/pending-actions.json`.
- Companion: `SKILLS/accounts-registry.md` for tracking signed-up services themselves.
