# Product Vision — Captured Ideas

_Ideas surfaced during infra stewardship that are potentially product-shaped. Not committed direction; preserved so they survive conversation compaction._

---

## 2026-04-18 — Platform-as-product: non-technical-user full-stack software

_Surfaced by user after the PROJECT_CONTEXT system discussion._

**The idea, stated back:**
The harness we're building (three gates, visual QA, acceptance rehearsal, data audit, perceived latency, cost monitoring, project context, journey-first framing, etc.) could itself become a product. What we're working towards is a very easy-to-use tool that allows a non-technical user to "automagically" have one conversation on mobile with Claude and get full-stack working software — with infra, testing, deployment, QA all handled by the platform.

**Why this is interesting:**
- Non-technical users are the underserved market for software creation. Existing low-code tools hit a ceiling fast; bespoke development requires technical literacy.
- A single-conversation-to-software flow on mobile is a genuinely novel interface pattern.
- Most of the moat isn't the LLM (anyone has Claude) — it's the *harness*: the accumulated conventions, checks, gates, and post-incident learnings that make agent-written code trustworthy without human review.
- We've been organically building that harness over weeks. Every LESSONS entry, every reviewer rule, every SKILL, every QA layer — it's all product IP.

**Current state of what's built toward it:**
- Multi-project platform (dev + prod droplets, 5 projects coexisting)
- Claude Code agent orchestration (infra chat coordinating project chats)
- Full CI/CD: webhook → auto-deploy → preview → live
- Three-gate QA (build, review, QA, accept) with 14+ reviewer rules
- Post-deploy QA hook (auto-deploy regens get tested against live URL)
- Visual QA system (deterministic + LLM dual-reviewer)
- Acceptance rehearsal (LLM plays end user before user Accept)
- Data audit (5 phases including display-layer sanity)
- Perceived latency checks
- Cost monitoring (paid-call gateway + spend-audit)
- Code hygiene enforcement (rules on magic values, deps, readability, OSS reuse)
- Platform services (paid-call, log-event, visual-review-orchestrator, smoketest, capacity, OOM detector, etc.)
- Non-technical-friendly interface patterns: iOS-plain-URLs, mobile-first, ntfy push, remote-control URLs
- Post-incident learning loop (LESSONS → SKILLS → reviewer rules → builder behavior)

**What would be needed to turn it into a product:**
- Provisioning (customer signs up, spins up their own platform instance)
- Billing abstraction (LLM spend + infra spend aggregated, marked up)
- Onboarding flow (first conversation → first project)
- Templates / starter projects for common use cases (dashboards, scrapers, personal tools)
- Multi-tenant isolation (probably one droplet per customer, simpler than shared)
- Observability at the platform-of-platforms level
- Support surface (when the harness fails, the customer doesn't have us to intervene)
- Security / compliance posture suitable for external customers

**Open questions (for future self):**
- Is the harness generalizable, or deeply coupled to this user's specific preferences?
- What's the right pricing model — flat monthly, usage-based, tied to LLM spend?
- Who's the buyer persona — solo operators? Startup founders non-technical? Small-business owners?
- How much of the harness is durable IP vs. "convention for Claude Code as it exists today"?
- What's the minimum viable product — single-project, or multi-project from day one?

**Do not act on this now.** User explicitly said "just remember." This file is the memory.

**When to revisit:**
- When user explicitly raises it again.
- When the current platform reaches stability such that attention can shift to productization.
- If a clear triggering event occurs (e.g., someone else ships something similar).

---

_To add entries: new top-level section with ISO date. Preserve all prior entries. This file is append-only._
