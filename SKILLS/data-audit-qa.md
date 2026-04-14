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

## The Change Queue (how findings become fixes)

**Checking is parallel. Fixing is orchestrated.** A parallel agent finding an error does NOT fix it — that creates race conditions and untraceable changes. Instead:

Each finding appends one entry to `AUDIT_FINDINGS.md` at the project root:

```markdown
## F-<nnn> — <one-line symptom>
- **Location:** <file / dashboard tab / dataset field>
- **Observed:** <reported value>
- **Expected:** <your re-derived value, with calculation>
- **Source chain:** <trace>
- **Stopping condition:** <if verification couldn't reach primary source>
- **Severity:** critical / high / medium / low
- **Flagged by:** <agent id / date>
- **Status:** open
```

Severity rubric:
- **Critical**: headline number wrong, or the error changes a user's decision.
- **High**: non-headline number materially off (> 1% error on a $-denominated field).
- **Medium**: cosmetic but noticeable (off-by-cent rounding, slightly wrong timestamp).
- **Low**: audit noise, self-consistent minor quirk.

Once checking completes, the **orchestrator** (the chat running the audit, not a subagent) walks the queue and plans the fix pass:

1. Group findings by root cause — many findings often trace to one upstream defect.
2. For each root cause, spawn one Builder subagent (per `SKILLS/parallel-execution.md`) to fix at the source — not patch the output. Per `SKILLS/root-cause-analysis.md`, never suppress the symptom.
3. After the fix lands, **re-run the audit against the previously-failed data points only** — the change queue's `F-*` entries get marked `verified` (with date) or `failed-after-fix` (which escalates severity and files an RCA task).
4. Sync the `AUDIT_FINDINGS.md` to append a `## Resolution` block under each fixed finding with commit SHA + verification result.

Only when every critical and high finding is `verified` is the audit considered passing.

## Parallelization Mechanics

- **Phase 1** is mostly one agent per dataset / chart — the outlier math itself is fast.
- **Phase 2** fans out aggressively. Batch ~10-50 checks per agent (each check has overhead; too-fine batching wastes tokens). Dispatch all batches in one orchestrator message with multiple `Agent` tool-use blocks.
- Each agent's brief must be self-contained: which rows it owns, what the expected schema is, which external source to trace to, which columns need re-derived calculation, what output format to return.
- Returning agents append directly to `AUDIT_FINDINGS.md` — no merge step needed beyond deduplication.

Before fan-out, the orchestrator checks `/capacity.json`. If warn/urgent, cap concurrency to stay within RAM headroom.

## Output Artifact

At the end of the audit, the project's `AUDIT_FINDINGS.md` is the canonical record, and a one-page summary goes into the user-facing response:

```
Audit: <project>
Date: <YYYY-MM-DD>
Scope: <what was in scope>
Sample: <total points> checked against <population>
Pass rate: <N> verified / <M> sampled
Findings: <critical> critical, <high> high, <medium> medium, <low> low
Unreachable sources: <count> (verification stopped before primary source)
Status: PASS | PASS-WITH-ISSUES | FAIL
Next: <what the orchestrator is doing about the findings>
```

The full finding list lives in `AUDIT_FINDINGS.md` with URLs/line refs.

## Anti-Patterns

- **Trusting the code.** Reading the implementation and saying "looks right" is not an audit. Re-derive from first principles using the domain, not the code.
- **Verifying against the ingestion layer instead of the source.** If we ingested SEC filings into our own DB and you verify against the DB, you've verified nothing — you've confirmed the DB matches itself. Always go one hop further back.
- **Fixing in parallel.** Parallel agents making code changes collide and corrupt each other's output. Find in parallel, fix serially under orchestrator control.
- **Glossing over stopping conditions.** "Couldn't find the filing, moving on" is a finding, not a pass. Record where verification stopped and why.
- **Uniform sampling on non-uniform risk.** If a user looks at 5 headline numbers on a dashboard, those 5 should get near-100% coverage regardless of the overall sample rate.
- **Auditing once and calling it done.** Data changes; re-audit on a cadence. Quarterly is typical for live pipelines.

## Integration

- `SKILLS/parallel-execution.md` — the dispatch primitives. Phase 2 is the canonical use case.
- `SKILLS/root-cause-analysis.md` — every finding's fix follows RCA, never a symptom patch.
- `SKILLS/capacity-monitoring.md` — check before a big fan-out.
- `SKILLS/non-blocking-prompt-intake.md` — user questions during an audit get their own subagents; the audit keeps running.
- `SKILLS/platform-stewardship.md` — patterns discovered during an audit that would prevent *future* classes of error become new CLAUDE.md rules or LESSONS.md entries.
