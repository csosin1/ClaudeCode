# Skill: Secrets

## When To Use

Any time you're handling credentials — API keys, passwords, tokens, connection strings.

## Rules

- **No credentials in git.** `.gitignore` includes `.env`. nginx denies `.env`, dotfiles, `.md`.
- Secrets live in `/opt/<project>/.env` on the droplet (gitignored), or GitHub Secrets for CI.
- For user-entered secrets from a phone, expose a `/setup` page in the app (basic-auth gated or behind a one-time token). Never ask the user to SSH.
- Every credential has a corresponding entry in the `account.sh` registry so there's one canonical record of what service it serves. See `SKILLS/accounts-registry.md`.

## Anti-Patterns

- **Committing `.env.example` with real values.** Template files must contain only placeholders.
- **Hardcoding credentials "temporarily for debugging."** These stay.
- **Storing secrets in `CLAUDE.md`, `RUNBOOK.md`, `PROJECT_STATE.md`, or any `.md` file.** All `.md` files are publicly readable if nginx config slips; assume they will be.
- **One credential shared across projects.** If two projects both need Anthropic API, each has its own `.env` with its own key — so revoking one project's access doesn't disturb the other.

## DO API Tokens (Specific Hygiene)

User rule as of 2026-04-17: **one DigitalOcean API token at a time across the platform, not many.** Token sprawl in the DO audit log is a signal something's wrong.

- Before creating a new DO API token: revoke any old one that was serving the same purpose.
- Label each token with its purpose (e.g., "claude-infra-2026-04", not the default "Generated").
- Store in `/opt/site-deploy/.env` as `DIGITALOCEAN_TOKEN=...` (gitignored).
- Register in `account.sh` under service "DigitalOcean API" with the purpose in the `purpose` field. When rotating, `account.sh cancel` the old entry + add the new one.
- If an audit shows multiple tokens you didn't consciously create: investigate before creating another. Each token is a separate credential that can leak independently.

## If A Credential Leaks

1. Revoke on the provider's dashboard immediately (don't rotate — revoke).
2. Issue a new credential.
3. `git log --all -p | grep -i <partial-cred>` to confirm it's not in any commit or branch. If it is: force-push a scrubbed history and rotate everything that ever touched that repo.
4. LESSONS.md entry covering root cause (how did it slip past .gitignore / review / pre-commit?) and preventive rule.

## Integration

- `SKILLS/accounts-registry.md` — register every credential's service there.
- `SKILLS/security-baseline.md` — the overall security posture this operates within.
