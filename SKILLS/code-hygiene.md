---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Code Hygiene

## When To Use

Any diff that adds or modifies **runtime code** — scripts, app code, cron jobs, systemd services, helpers, workflow steps that execute commands. Applies to bash, Python, JavaScript/TypeScript, SQL, and any other language we run.

Not required for docs-only (`*.md`), config-only (`*.json` / `*.yaml` without embedded code), or comment-only changes.

The rules here are the minimum bar. A diff that violates any of them is a code-hygiene FAIL during review (see `infra-reviewer.md` rule #13).

## Named Constants Over Magic Values

Any value that might reasonably change — ports, URLs, thresholds, paths, API endpoints, retry counts, timeouts, file size limits — lives in one of:

- `.env` (project-scoped, gitignored)
- `/etc/<project>.conf` (droplet-wide, managed)
- A top-of-file `CONSTANTS` block with UPPERCASE names

Magic values inline are a smell. If you *must* inline one (protocol-mandated like HTTP status `200`, or a hardware constant like `1024`), add a one-line comment explaining why it cannot be configured.

```python
# BAD
if retries > 3:
    sleep(30)
    requests.get("https://api.example.com/v2/status", timeout=5)

# GOOD
MAX_RETRIES = 3
BACKOFF_SECONDS = 30
STATUS_URL = "https://api.example.com/v2/status"
REQUEST_TIMEOUT_SECONDS = 5

if retries > MAX_RETRIES:
    sleep(BACKOFF_SECONDS)
    requests.get(STATUS_URL, timeout=REQUEST_TIMEOUT_SECONDS)
```

## Dependency Pinning

**Node.** Commit `package-lock.json`. Use exact versions (`"playwright": "1.48.2"`) in dependencies for anything load-bearing. Never `"*"` — a wildcard version string in a lockfile resolves to whatever's latest at install time and silently breaks `npm ci`. **Reference: the 2026-04-17 playwright incident.** A `"playwright": "*"` in `package-lock.json` broke `npm ci` across CI and preview deploys. Exact pins would have prevented it.

**Python.** Prefer a committed `requirements.txt` with `==X.Y.Z` pins, or `pyproject.toml` with exact specs, or a committed Poetry/uv lockfile. `>=` is not a pin — it's a time bomb.

**System packages.** Where reproducible droplet rebuilds matter, pin apt installs: `apt-get install -y nginx=1.24.0-2ubuntu1`. For ephemeral tooling (jq, curl) default-latest is usually fine.

**Versioned assets in static sites.** Use stable filenames: `plotly-2.27.0.min.js`, not `plotly.min.js`. Browser cache hits depend on stable names, and an unversioned CDN URL can silently change content behind you.

## Standard Bash Preamble

Every new bash script starts with this:

```bash
#!/bin/bash
# <script-name>.sh — <one-line purpose>
set -eE -o pipefail
trap 'echo "ERROR at $LINENO: $BASH_COMMAND (rc=$?)" >&2' ERR
```

Why each flag:

- `-e` exits on first error.
- `-E` propagates the ERR trap through functions and subshells (plain `-e` doesn't).
- `-o pipefail` makes a failure mid-pipe fail the whole pipeline. Without it, `failing_cmd | grep -v foo` returns grep's exit code, silently hiding the upstream failure.
- The ERR trap gives line-number diagnostics when a script dies — invaluable during outage RCA.

For longer scripts that do their own notification on failure, add a recursion guard so the trap doesn't fire a second time while the notifier itself is running:

```bash
_FAILED_FIRED=0
on_err() {
    [[ $_FAILED_FIRED -eq 1 ]] && return
    _FAILED_FIRED=1
    notify.sh "<project> deploy failed at line $1"
}
trap 'on_err $LINENO' ERR
```

See `deploy/auto_deploy_general.sh` for the worked example.

## Human Readability — First-Class Concern

**Agents must produce code that a human — or another agent — can read and modify without spelunking.** This is not optional style; it is what makes future sessions cheap instead of expensive.

**Naming.** Variables and functions describe *what*, not *how*. `parsed_offers` not `po`. `fetch_vin_offer(vin)` not `get_data(x)`. Names > 2 characters except loop counters (`i`, `j`, `k` are fine). Acronyms stay acronyms (`api_url` not `a_u`).

**Function granularity.** One function, one thing. If a function's name contains "and" (`fetch_and_parse_and_save`), split it. Target <50 lines; >100 lines is a strong smell and needs a "why big" comment or a refactor.

**File size.** >400 lines is a smell. >1000 lines almost always means multiple concerns are mixed and the file wants to be split. Add a "why big" comment at the top if a large file is genuinely justified (e.g. generated code, tight coupling to a single API surface).

**Comments explain *why*, never *what*.**

```python
# BAD — the code says this
i += 1  # increment i

# GOOD — surprising decision with context
# Cloudflare strips port numbers from Host header when proxying;
# rewrite here so downstream nginx sees the canonical host. See LESSONS 2026-02-12.
host = host.split(":")[0]
```

Comments that document surprising decisions or link to incidents / vendor docs are gold. Comments that restate the code are noise.

**Explicit over implicit.**

- Explicit imports: `from foo import bar, baz` — never `from foo import *`.
- Explicit returns: don't fall off the end of a function and rely on `None`. Return `None` explicitly if that's the intent.
- Explicit encodings: `open(path, encoding="utf-8")`, never `open(path)` for text.
- Explicit types at shell / number boundaries: `count=$((count + 1))`, not string concatenation you'll debug at 2am.

**Standard file ordering.** Imports → constants → helpers → main logic → entrypoint guard (`if __name__ == "__main__":` in Python; `main "$@"` at the bottom of bash). Consistent ordering means a reader always knows where to look.

**Consistent formatting per language.** Python uses PEP 8 basics: 4-space indent, snake_case functions and variables, PascalCase classes. JS/TS uses Prettier defaults. Bash uses 4-space indent; lowercase for local variables, UPPERCASE for globals and constants. Don't fight the language's conventions — surprise is cost.

**Avoid clever one-liners when multi-line is clearer.** A dense regex or a chained list comprehension that takes 30 seconds to parse should be split and named. "Clever" code is tech debt disguised as elegance. If a one-liner needs a comment to explain it, it wanted to be multiple lines.

## Maximize Open-Source Use — Minimize Self-Maintained Code

**Default is consume, not build.** Every new capability starts with four questions, in order:

1. Does a `SKILLS/*.md` cover this?
2. Does a well-maintained OSS library cover this?
3. Is there a managed service (Cloudflare, Anthropic, DigitalOcean, GitHub, Stripe, Clerk) that covers this?
4. Only if all three fail — write custom, and justify *why* in the commit.

**"Well-maintained" criteria.** A package qualifies if it meets **all** of:

- Published a release within the last 12 months.
- Commits to the main branch within the last 90 days.
- Issues responded to within ~30 days (spot-check the tracker).
- >1k stars on GitHub, **or** clearly authoritative (a vendor's official SDK, a W3C reference implementation, etc.).

Stale-looking packages are future maintenance burden. A library with 10k stars but last commit 3 years ago is a worse choice than a newer package with half the stars but an active maintainer.

**When custom is necessary, wrap it in a replaceable interface.** If no OSS exists today, write a thin wrapper around your custom code so that when OSS emerges you swap the implementation without rewriting callers. Worked example: our `notify.sh` wraps ntfy.sh. If we swap to Pushover tomorrow, every caller (`notify.sh "message"`) stays unchanged.

**Avoid re-implementing well-solved problems.** Don't build: auth, cron, queuing, logging, rate limiting, HTTP routing, JSON schema validation, PDF generation, CSV parsing, date math, retry-with-backoff. There are mature libraries and services for every one of these.

**Cite the dependency in a comment.** When adopting OSS, a one-line comment helps future maintenance:

```python
# using weasyprint 68.1 — drops to Pango native lib for text shaping
from weasyprint import HTML
```

Makes it possible to find the right version of docs when something changes.

**Annual review cadence.** Once a year, skim every project and per-component ask: *could this be replaced by OSS that didn't exist when we wrote it?* Document the review in `CHANGES.md`. Don't automate this — it's a judgment call.

## Reuse Before Build Checklist

Run in order before writing anything:

1. `grep -r <pattern> SKILLS/` — does a SKILL already cover this?
2. `grep -r <functionality> /opt/site-deploy/helpers/` — does a helper script already do it?
3. Check PyPI / npm top results for a well-maintained package.
4. Is there a managed service (Cloudflare, Anthropic, DO, GitHub) already on our stack that does this?
5. Only now consider writing custom — and document *why* in the commit message.

## Standard Logging Format

One format family per output surface:

**Machine-consumable (events, metrics):** JSONL with at minimum `ts`, `project`, `level`, `event`, plus optional metadata. Reference: `/var/log/paid-calls.jsonl`, `/var/log/events.jsonl`.

```json
{"ts":"2026-04-17T14:32:01Z","project":"car-offers","level":"info","event":"fetch_success","vin":"1HGBH41JXMN109186","cost_usd":0.004}
```

**Human-read (app logs, deploy logs):** `<ISO-8601-ts> [<level>] <component>: <message>`.

```
2026-04-17T14:32:01Z [INFO] deploy: pulled commit abc123, running tests
```

**Never silently swallow failure.** Never use `|| true` without a comment explaining why the failure is expected and acceptable.

**Never log secrets.** Sanitize API keys, tokens, passwords, and auth headers on the way to any log. Assume every log line will end up in a GitHub issue someday.

## Error Handling Discipline

**Bash.** `set -eE -o pipefail` is the default (see preamble above). Intentional failure-tolerance is explicit: `rm -f /tmp/stale.lock || true  # lock may not exist on first run`.

**Python.** `except Exception:` is almost always wrong — it catches `KeyboardInterrupt` on older versions, swallows bugs, and hides genuine failures. Catch specific exception classes:

```python
# BAD
try:
    response = requests.get(url)
except Exception:
    response = None

# GOOD
try:
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
except (requests.Timeout, requests.ConnectionError) as e:
    logger.warning("fetch failed: %s", e)
    response = None
```

**Never use bare `except:`** without an explicit rationale comment. Bare except catches `SystemExit` and `KeyboardInterrupt` and makes Ctrl-C not work.

## Function / File Size Heuristics

Recapping from above, these are smells not hard rules:

- Function > 50 lines: smell — consider splitting.
- Function > 100 lines: split, or add a "why big" comment.
- File > 400 lines: smell — likely mixing concerns.
- File > 1000 lines: almost certainly wants to be multiple files.

## What NOT To Do

Deliberately out of scope for this SKILL:

- **No strict linter enforcement in CI.** Too brittle; would break existing code and create noise.
- **No forced auto-formatter** (Black, Prettier) in pre-commit. Individual projects opt in if they want.
- **No refactor of existing code** purely to match new conventions. Fix on touch — when you modify a file for another reason, bring it up to standard.
- **No architectural dogma.** "All code must use design pattern X" is not a rule.

The goal is a default level of quality that makes future work cheap, not compliance for its own sake.

## Related Skills

- `secrets` — credential handling and `.env` patterns.
- `costly-tool-monitoring` — paid-API hygiene, complements dependency pinning for runtime cost control.
- `data-audit-qa` — the skeptical-auditor pass for number-heavy code.
- `perceived-latency` — user-facing code has perf-hygiene rules on top of these.
- `python-script-path-hygiene` — specific Python path / import rules.
- `llm-vs-code` — when to reach for an LLM vs write deterministic code.
- `platform-stewardship` — how this SKILL fits the "solve once, never twice" discipline.
