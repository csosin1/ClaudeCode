---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Four-Agent Debate — structured disagreement for consequential decisions

## When to use

Any decision with real tradeoffs where single-agent output would be confidence-theater. Specifically:

- Architecture / protocol design spanning multiple subsystems.
- "Should we change X" where the status quo has defenders and critics.
- Holistic reviews where one agent's scan won't fit the surface area.
- Any call whose downstream cost of being wrong exceeds ~2 hours of work.

**Do NOT use for:** clear user directives ("just do X") — do X; bugs with a known root cause — fix; single-choice decisions with an obvious answer — state and proceed; execution tasks — spawn a builder.

## The four asymmetric roles

One agent runs first and alone; three run as peers in parallel; synthesis is orchestrator work, not a fifth peer.

1. **Research (runs FIRST, alone)** — evidence layer. Surfaces named methodologies, incidents, postmortems, industry benchmarks. Writes to `/tmp/<topic>-research.md`. Does NOT prescribe. The other three read this output during their brief.
2. **Advocate (parallel)** — steelmans the proposal. Names what each design element catches (failure-class to mechanism mapping). Lists concessions honestly but argues outweighed.
3. **Skeptic (parallel)** — strongest critique. **Must propose ONE concrete deletion or collapse.** Names concrete failure modes, not vibes. A skeptic that refuses to cut anything is a bad skeptic.
4. **Improver (parallel)** — refinements that keep the spirit but sharpen the details. Numbered refinements, each 5-15 lines. Ends with a **top-3 most load-bearing** summary.

### Asymmetry rules (critical — do not violate)

- Research is never a peer. It runs alone first so the other three share a factual base.
- Synthesis is never a peer. Orchestrator (main thread) reads all three and produces the deliverable.
- The three parallel agents do NOT read each other's output during their run. Prevents groupthink; the whole point is independent probes.

## Mechanics

1. **Shared digest** → write `/tmp/<topic>-digest.md`. Extraction only, no interpretation. 200-400 lines. Cite sources. All agents read this.
2. **Research agent** → dispatch, wait, read output. (Parallel dispatch with the other three would poison the shared evidence layer.)
3. **Advocate + Skeptic + Improver** → dispatch **in parallel** in a single orchestrator message with three tool-use blocks. Each writes to its own `/tmp/<topic>-<role>.md`.
4. **Synthesize** → orchestrator reads all four outputs. Identifies cross-cuts (themes raised by ≥3 agents). Produces prioritized action list (top 3-5, not 20), "deliberately NOT recommended" section, and "monitor going forward" triggers.

### Brief structure (per agent)

Every brief names: role, read-first list (digest + research output if applicable), specific questions, evidence to draw on, format requirements (line budget, structure), end-with-summary requirement, exact output path.

## Variants

### 3-agent (lighter, for moderate-stakes calls)

Research + Tradeoffs + Improver. The Tradeoffs agent does skeptic-lite with the explicit "propose one deletion" mandate preserved. Use when the topic is less contested or when budget matters (e.g., telemetry design, ~half the wall-clock of the full 4-agent).

### Expanded N-chunk × 3-4 (for sprawling reviews)

For holistic reviews spanning multiple subsystems. Each chunk gets its own committee; every chunk produces an independent digest. The orchestrator synthesizes cross-cuts across chunks — themes appearing in ≥3 chunks or ≥3 agents get elevated in the final action list. Example: the 2026-04-18 platform review ran 4 chunks × avg 3.5 agents = 14 agents and produced a 5-action prioritized list.

## Output shape — the deliverable

Prioritized action list. NOT an essay. NOT a menu of options. Top 3-5 concrete actions, each with: **what** (one sentence), **why** (which cross-cut or agent finding), **rough cost** (hours or days), **ship order** (first, second, …).

Plus two required companion sections:

- **Deliberately NOT recommended** — anti-churn. Names proposals the committee raised but that don't belong in the action list, with one-sentence rationale each.
- **Monitor going forward** — trigger conditions (metric thresholds, frequency flags) that would cause us to revisit.

## What NOT to do

- Let agents see each other's output mid-run → groupthink.
- Dispatch sequentially when parallelism is available → wastes wall-clock; see `SKILLS/parallel-execution.md`.
- Skip the shared digest → agents invent their own facts and talk past each other.
- End with a menu of options → skeptics sniff that as decision-avoidance.
- Run 4-agent on execution tasks → use a builder.
- Run 4-agent on bugs with a known root cause → just fix.

## Cost/time envelope

Typical 4-agent run: 4 agents × 100-200 lines output × ~3-6 min each, three running in parallel → 6-10 min wall-clock dispatch. Tokens: ~$2-8 depending on digest size. Orchestrator synthesis adds 5-15 min. **Total ~20-30 min + low-single-digit dollars.** Cheap for any decision with >2 hours of consequence.

## Precedents on this platform (keep living list)

- 2026-04-18 — holistic platform review (4 chunks × avg 3.5 agents = 14; produced 5-action prioritized list).
- 2026-04-18 — kickoff-protocol design debate (4 agents; dogfoods this skill).
- earlier — competitive analysis vs OSS AI coding tools (4 agents).
- earlier — telemetry design (3-agent variant).

## Related

- `SKILLS/parallel-execution.md` — agent dispatch must be parallel.
- `SKILLS/never-idle.md` — orchestrator keeps other work moving while the committee runs.
- `SKILLS/platform-stewardship.md` — committee outputs often yield new skills / LESSONS.
