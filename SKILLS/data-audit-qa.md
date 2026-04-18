# Skill: Data Audit & QA

## Guiding Principle

**Act like a skeptical professional auditor, not a code reviewer.** The code may produce exactly what it was written to produce — and still be wrong. Every load-bearing number must be traceable back to an external primary source, and every calculation must be re-derived from first principles, not copied from the implementation.

## When To Invoke

- **Before promoting a data-heavy dashboard from preview to live** for the first time.
- **Before any analysis influences a real-world decision** (investment call, customer-facing price, regulatory filing).
- **When the user asks for a data audit** — they'll typically name the project.
- **After any non-trivial data-pipeline change** — not the schema, but anything that reshapes, aggregates, or re-ingests.
- **Quarterly or at a user-specified cadence** for live dashboards with ongoing ingestion.

Invocation trigger can be as simple as: "audit Carvana Loan Dashboard at 10% sample."

## The Two Phases

Both phases run in parallel where possible. See `SKILLS/parallel-execution.md` for dispatch mechanics.

### Phase 1 — Universal Outlier Scan (100% coverage, cheap)

Every numeric field / chart / dataset in scope gets a fast outlier pass. Automated first, visual second.

- Statistical outliers: z-score > 3 or IQR × 3 on each numeric column.
- Distribution smell tests: unexpected zeros, unexpected NULLs, uniform-looking values in fields that should vary, monotonic series that aren't monotonic, % fields outside 0-100, negative values where nonnegative is required, dates outside a plausible window.
- Cross-field invariants: `net = gross − allowance`, `pct_total ≈ sum(pct_components)`, `count_distinct ≤ count`, `min ≤ mean ≤ max`, time-series deltas within a plausible band.
- Visual smell: chart-by-chart, look for discontinuities, spikes that coincide with ingestion dates (a.k.a. "data error that looks like a market event"), 100% flat lines where variation is expected.

Phase 1 produces a ranked list of suspicious points. Everything flagged graduates automatically into Phase 2 — it gets checked regardless of sample selection.

Alongside random and risk-weighted selection, the Phase 1 sample must always include the three youngest items in the distribution (newest deals, freshest records, most recent entities) and the three oldest. Bugs that only manifest at distribution edges are invisible to middle-weighted samples: brand-new deals expose defects where realized-to-date approaches zero relative to lifetime-projected values (the abs-dashboard `actual_residual` bug surfaced exactly this way), and ancient records expose stale-format or deprecated-schema defects. Edge sampling is cheap — six extra points — and catches a class of bug that risk-weighting alone will miss.

### Phase 2 — Random-Sample Deep Verification (user-specified %, expensive)

- **Ask the user for a default sample rate** if not provided. Suggest 10% as a starting point; smaller datasets may need higher %, massive ones lower.
- **Risk-weight the sample.** Headline, load-bearing fields (anything the user looks at first, anything feeding a decision) get a higher rate, typically 2-3× the default. Helper / scratch fields can get the default or lower. The skill declares the weighting up-front so the user can override.
- **Sample deterministically.** Seed the RNG with the audit date + dataset name. This makes the audit reproducible and lets follow-up audits avoid re-sampling the same rows unless intentional.

For each sampled data point, do these three things — in parallel across the sample, one agent per batch of ~10-50 points:

1. **Trace to source.** Follow the data backward through every hop until you hit an external primary source. SEC filing URL, proxy site's original HTML, SQL from the raw ingestion table, API response body. Record the hop chain.
2. **Re-derive the math.** If the value is computed, figure out what the calculation *should* be from the domain and available inputs, then do the math yourself (arithmetic, aggregation, ratio). **Do not copy the calculation from the implementation** — that defeats the audit. Compare your number to the reported number.
3. **Document stopping condition.** If source is unreachable (filing deleted, site 404, API rate-limited), record "verification stopped at layer N: <reason>." Do not silently pass or silently fail — honest partial verification is the output.

## Sample Rate & Weighting Template

Before sampling, write this to the audit report so the user knows exactly what got checked:

```
Audit: <project> <date>
Default sample rate: 10%
Risk-weighted overrides:
  - Headline fields (net_receivables, allowance_coverage, delinquency_total): 30%
  - MD&A-derived narrative fields: 20%
  - Helper/scratch columns: 5%
  - Outliers from Phase 1: 100% (auto-included, not counted against sample)
Sample seed: <project>-<YYYY-MM-DD>
Total data points in scope: <N>
Total sampled: <M>
```

## Halt-Fix-Rerun Loop (how findings become fixes)

**Don't find the same root cause fifty times.** A single upstream defect typically produces many symptoms. Finding all fifty symptoms in one pass and then fixing is wasteful — the fix invalidates the already-completed verification, and you spent compute cataloguing duplicates.

Instead, the audit runs as a **halt-fix-rerun loop**:

```
while iteration < MAX_ITERATIONS (default: 10):
    run Phase 1 (outlier scan, 100%)  →  if any: halt immediately
    run Phase 2 (risk-weighted random sample, parallel batches)
    as soon as the first batch reports a finding:
        stop dispatching new batches
        let in-flight batches finish their current point (graceful halt, not abort)
        collect all findings that naturally surface in the drain
    if no findings:
        AUDIT PASSES — record and exit
    group findings by probable root cause
    fix the highest-severity group first
    mark symptoms in AUDIT_FINDINGS.md as "resolved pending re-audit"
    iteration += 1

if iteration == MAX_ITERATIONS:
    audit stops, flag to user — a fix isn't actually fixing and needs human review
```

### Finding format

Each finding — whether it triggers the halt or surfaces in the drain — appends one entry to `AUDIT_FINDINGS.md` at the project root:

```markdown
## F-<nnn> — <one-line symptom>
- **Location:** <file / dashboard tab / dataset field>
- **Observed:** <reported value>
- **Expected:** <re-derived value, with calculation>
- **Source chain:** <trace>
- **Stopping condition:** <if verification couldn't reach primary source>
- **Severity:** critical / high / medium / low
- **Iteration:** <which pass found it>
- **Flagged by:** <agent id / date>
- **Status:** open
- **Root-cause group:** <identifier, filled in during grouping>
```

Severity rubric:
- **Critical**: headline number wrong, or the error changes a user's decision.
- **High**: non-headline number materially off (> 1% error on a $-denominated field).
- **Medium**: cosmetic but noticeable (off-by-cent rounding, slightly wrong timestamp).
- **Low**: audit noise, self-consistent minor quirk.

### Grouping by root cause

Before fixing, the orchestrator asks: "could these findings share an upstream cause?" Common patterns:
- Same column across different rows → likely a formula or ingestion bug affecting that column.
- Same row across different columns → likely a single bad input record.
- Same time bucket across ticker/entity → likely a timestamp parsing or period-alignment bug.
- Numerical offsets that look like unit mismatches (factor of 1000, factor of 100, currency) → likely a units-of-measure bug.

If the pattern is clear, fix all findings with one change to the upstream code. If findings look genuinely independent, they get fixed in severity order, one group per iteration.

### Fixing (serial, root-caused)

Per `SKILLS/root-cause-analysis.md`:
1. Spawn one Builder subagent per root-cause group. Each fix ships with a `LESSONS.md` entry explaining the upstream defect and a preventive rule if applicable.
2. Mark the symptoms this fix resolves: `Status: resolved pending re-audit` in `AUDIT_FINDINGS.md`.
3. Next iteration: the rerun either confirms `resolved → verified` or escalates to `failed-after-fix` (the fix didn't work; RCA task filed).

### Pass criteria

One full iteration completes with zero findings → AUDIT PASSES. The `AUDIT_FINDINGS.md` reflects every finding from every iteration, with resolution blocks showing what fixed what. Users and future auditors can read the history.

### Why halt on first finding?

- **Compute efficiency.** Finding duplicates of the same root cause is wasted work.
- **Correctness.** Findings collected *after* a fix are stale — they're about an obsolete version of the code.
- **Forces RCA.** You can't chain "just fix them all" band-aids; every iteration commits a real upstream fix.

### When NOT to halt

- **Low-severity findings** (purely cosmetic): the orchestrator may choose to continue the pass and batch-fix lows at the end, IF the user has indicated tolerance for this. Default is halt-on-any.
- **Outlier scan is fast enough** that it usually completes before a halt decision matters.
- **If the user specifies "run to completion and show me everything"** (useful for a scoping pass before deciding on a sample rate). In that mode the halt is suppressed and all findings are reported as advisory.

## Parallelization Mechanics

- **Phase 1** is mostly one agent per dataset / chart — the outlier math itself is fast.
- **Phase 2** fans out aggressively. Batch ~10-50 checks per agent (each check has overhead; too-fine batching wastes tokens). Dispatch all batches in one orchestrator message with multiple `Agent` tool-use blocks.
- Each agent's brief must be self-contained: which rows it owns, what the expected schema is, which external source to trace to, which columns need re-derived calculation, what output format to return.
- Returning agents append directly to `AUDIT_FINDINGS.md` — no merge step needed beyond deduplication.

Before fan-out, the orchestrator checks `/capacity.json`. If warn/urgent, cap concurrency to stay within RAM headroom.

## Output Artifact

At the end of the audit loop, the project's `AUDIT_FINDINGS.md` is the canonical record, and a one-page summary goes into the user-facing response:

```
Audit: <project>
Date: <YYYY-MM-DD>
Scope: <what was in scope>
Iterations run: <N>   (halt-fix-rerun loop; clean pass required to exit)
Total findings across all iterations: <F>
  - <critical> critical, <high> high, <medium> medium, <low> low
Root-cause groups fixed: <G> (one commit per group)
Unreachable sources: <count> (honest stopping conditions recorded)
Final sample (clean pass): <M> points checked, 0 findings
Status: PASS | FAIL-MAX-ITER
```

`FAIL-MAX-ITER` means the loop hit `MAX_ITERATIONS` without a clean pass — typically a fix that isn't actually fixing the root cause. This is a human-review signal, not a platform decision.

The full finding list lives in `AUDIT_FINDINGS.md` with URLs/line refs and resolution blocks showing which commit resolved which finding. Future audits re-read this file as prior-art.

## Anti-Patterns

- **Trusting the code.** Reading the implementation and saying "looks right" is not an audit. Re-derive from first principles using the domain, not the code.
- **Verifying against the ingestion layer instead of the source.** If we ingested SEC filings into our own DB and you verify against the DB, you've verified nothing — you've confirmed the DB matches itself. Always go one hop further back.
- **Fixing in parallel.** Parallel agents making code changes collide and corrupt each other's output. Find in parallel, fix serially under orchestrator control.
- **Glossing over stopping conditions.** "Couldn't find the filing, moving on" is a finding, not a pass. Record where verification stopped and why.
- **Uniform sampling on non-uniform risk.** If a user looks at 5 headline numbers on a dashboard, those 5 should get near-100% coverage regardless of the overall sample rate.
- **Auditing once and calling it done.** Data changes; re-audit on a cadence. Quarterly is typical for live pipelines.
- **Finding everything, then fixing in bulk.** This is what the halt-fix-rerun loop avoids. Finding N symptoms of one root cause wastes N-1 agent-runs of compute AND produces stale findings once the fix lands.
- **Fix-and-move-on within an iteration.** After a fix, the loop *reruns* — do not mark findings resolved without re-audit verification. A "fix" that doesn't pass re-audit is a worse bug than the original (false confidence).
- **Infinite looping.** `MAX_ITERATIONS` exists. If the loop can't converge, stop and escalate to the user — the fix is probably touching a symptom, not the cause.

## Phase 5 — Display-layer sanity ranges

DB-layer audits (Phases 1-4) catch parser, ingestion, and stored-column defects. They do **not** catch bugs in **derived/computed columns rendered at display time** — values that exist only at render, never stored, so Phase 1's outlier scan has no surface to see them. Two production bugs on abs-dashboard in 36 hours share this root cause: the 2026-04-17 rendering-unit bug (percent-unit DB value re-multiplied by 100 in the formatter; `Exp Loss` showed 347.58% vs true 3.48%) and the 2026-04-18 WAL-collapse bug (pure-compute WAL derived from too-thin pool_performance rendered 0.1-2.1y across deals where prime-auto WAL should be 1.8-2.5y; cascaded into Total Excess Spread, Expected Residual Profit, and Variance columns). Neither bug had a stored row to audit. Phase 5 closes this gap.

### Requirements (every project with user-facing computed columns must do this)

1. **Define a `DISPLAY_RANGES` dict per user-facing tab/view**, one entry per rendered derived column, at the point of column definition.
2. **Each entry specifies**: `bounds` (min, max), `severity` (HALT or WARN), `provenance` (1-2 lines on where the range came from — domain knowledge, historical quantile, regulator-mandated, etc.), `rationale` (why out-of-range = bad), and optional `agg_bounds` for weighted-average aggregate sanity.
3. **On every dashboard regen and every promote**, invoke `helpers/audit_display_ranges.py` (or a project-local equivalent) with the rendered data + the `DISPLAY_RANGES` dict. HALT findings block the promote pipeline. WARN findings fire `notify.sh` at default priority for human review; pipeline continues.
4. **Aggregate sanity**: the weighted-or-simple average of each column across rendered rows should fall within a tighter band than per-cell bounds. Helper supports this via the optional per-column `agg_bounds` field (e.g., per-row WAL ∈ [0.5, 10]y HALT, but aggregate avg WAL should land in [1.8, 2.5]y).
5. **Cross-column consistency**: where derived columns chain (e.g., `total_excess_spread = excess_yr × WAL`), each project implements its own consistency check in-project — the generic helper does **not** cover this because the relationships are project-specific.

### Severity tiers — how to choose

- **HALT**: out-of-range means the value is definitely wrong. E.g., WAL outside [0.5, 10]y is physically impossible for auto-ABS; negative cumulative losses are impossible; tranche % > 100. Blocks the promote pipeline.
- **WARN**: out-of-range means suspicious-but-possible. E.g., WAL outside [1.5, 3.5]y is unusual for prime auto but legal for some structures; negative excess spread can occur transiently in distressed deals. Fires notify default-priority; doesn't block.

Rule of thumb: **HALT** if "a reasonable domain expert would say this can never happen." **WARN** if "a reasonable domain expert would want to look at this but wouldn't immediately say it's wrong."

### The `DISPLAY_RANGES` dict schema

```python
DISPLAY_RANGES = {
    "wal_years": {
        "bounds": (0.5, 10.0),
        "severity": "HALT",
        "provenance": "Physical: auto-ABS amortize over <=10y; no deal has WAL <0.5y at issuance.",
        "rationale": "WAL outside these bounds implies parser bug or empty pool_performance.",
        "agg_bounds": (1.8, 2.5),  # optional — weighted avg of rendered rows
    },
    "cum_net_loss_pct": {
        "bounds": (0.0, 30.0),
        "severity": "HALT",
        "provenance": "Domain: auto-ABS pools historically cap around 15-20% CNL; 30% is near-zero prior.",
        "rationale": "CNL > 30% almost certainly indicates parser error or restated-with-stale-data.",
    },
    "excess_spread_yr": {
        "bounds": (-2.0, 15.0),
        "severity": "WARN",
        "provenance": "Historical: most deals run 4-8% excess spread; negative is transient, >15% suggests unit-error.",
        "rationale": "Values outside this range possible in distressed deals but warrant inspection.",
    },
}
```

### Run cadence

The helper runs on:
- **every `generate_preview` pass** (catch before the user ever sees bad numbers),
- **every `promote` pass** (last-chance gate before live),
- **any daily cron-regenerated dashboard**.

Findings emit to `/var/log/<project>-display-audit.log`. HALT findings additionally fire `notify.sh` at high priority and raise `DisplayAuditHalt` so the calling pipeline exits non-zero. Auditing is project-local inline — no infra-side daemon.

### When to update the ranges

- **After a WARN fires repeatedly without a real issue** → range is too tight; widen it. Note the widening rationale in `provenance`.
- **After a HALT slips through (bug found post-deployment)** → range was too wide; tighten + add a `LESSONS.md` entry about the miss and how the new bound catches it.
- **When a new deal/entity type enters the universe with legitimately different characteristics** → evaluate whether ranges still apply or need per-segment DISPLAY_RANGES dicts.

### Integration with the halt-fix-rerun loop

Phase 5 findings feed into the same loop as Phases 1-4. The QA agent collects display-audit findings alongside DB-audit findings, halts on the first, the orchestrator groups by root cause (often a single formatter or unit-conversion bug produces many Phase 5 findings across one column), the builder fixes at the upstream compute site, QA reruns. Same severity rubric, same pass criteria.

## Integration

- `SKILLS/parallel-execution.md` — the dispatch primitives. Phase 2 is the canonical use case.
- `SKILLS/root-cause-analysis.md` — every finding's fix follows RCA, never a symptom patch.
- `SKILLS/capacity-monitoring.md` — check before a big fan-out.
- `SKILLS/non-blocking-prompt-intake.md` — user questions during an audit get their own subagents; the audit keeps running.
- `SKILLS/platform-stewardship.md` — patterns discovered during an audit that would prevent *future* classes of error become new CLAUDE.md rules or LESSONS.md entries.
