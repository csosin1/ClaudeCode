# Skill: Test Completeness Review

## Guiding Principle

**Tests pass within the space of conditions the test-author imagined.** A green test suite is evidence that the feature behaves correctly *for the inputs the author thought of*. It is not evidence the feature is correct. The gap between those two statements is where bugs ship — and self-review cannot close it because the author cannot see the failure modes they didn't think of.

Test completeness is an **independent review axis**. It runs as a separate agent so a reviewer with no framing-commitment to the test file can ask: "what failure modes are NOT tested?"

## When To Use

- Any PR that adds or modifies tests for runtime behavior.
- Any PR that ships a new spec with testable claims.
- Skip for documentation-only, config-only, or refactor-with-no-behavior-change PRs.

## Why This Exists

The 2026-04-17 Hazard-by-LTV chart bug. Spec: "Chart shows monthly default hazard by LTV band (<80%, 80-99%, 100-119%, 120%+) per issuer tier." Existing tests: `assertTextVisible(\'Hazard by LTV band\'); assertChartRendered();`. Tests passed. But the upstream data pipeline had a unit-scaling bug that collapsed all values into the `<80%` bucket — three of four declared categories were silently empty.

The tests asserted **presence** (the chart mounted, the title is visible), not the **semantic claim** (hazard is shown across all four LTV bands). The test author wrote what they thought of. What they didn't think of — "what if the data is wrong in a way that still renders?" — is exactly what shipped.

A test-completeness reviewer reading spec + tests with the single question "what failure modes are NOT tested?" would have flagged it in under five minutes.

## How To Invoke

One command pattern:

```
Agent(
  subagent_type=test-completeness-reviewer,
  prompt=<spec or CHANGES.md entry or PR description>
         + <path to primary test file(s)>
         + <optional: paths to referenced code files for context>
)
```

Expected output is the rigid JSON schema defined in `.claude/agents/test-completeness-reviewer.md`. Attach it to the PR description or append to `CHANGES.md` under the build entry.

Typical runtime: 2-5 minutes. Reviewer has Read-only tool access.

## How To Read The Output

| Verdict | What it means | What you do |
|---|---|---|
| `tests-sufficient` | No high-severity gaps; findings (if any) are medium/low and non-blocking. | Ship as planned. |
| `add-tests-before-ship` | At least one high-severity failure mode is untested, or an existing test is weak on the primary risk. | Add the suggested tests OR reject each finding with rationale in `CHANGES.md`. Reviewer verifies rationale. |
| `test-rewrite-needed` | Tests don't meaningfully constrain the feature's semantic claim — strengthening individual assertions won't fix it. | Substantial rework before merge. |

**The reviewer is not always right.** Rationale-based rejection is allowed. If a finding is theoretical ("what if the file is 4GB?") for a feature that will never see that input, reject it and say why in `CHANGES.md`. The reviewer should have filtered with `realistic_for_this_feature: false` — but if it missed, you can override.

**Do not rubber-stamp rejection.** If every finding is dismissed without rationale, the infra-reviewer will fail the PR under rule #15(c).

## What This Reviewer Does NOT Catch

Explicit honesty matters so the orchestrator doesn't over-trust a PASS.

- **Broken test infrastructure.** Tests that pass because of a mocking bug or because assertions are silently skipped. This is the `reviewer` agent's job (code correctness) and the `infra-qa` agent's job (evidence-based behavior verification).
- **Performance-under-load failures.** Tests may pass at N=1 and fail at N=10,000. That's the perf-QA axis (`SKILLS/perceived-latency.md`).
- **Data correctness.** Whether the numbers produced are semantically right vs. external ground truth. That's `SKILLS/data-audit-qa.md`.
- **Test quality.** Naming, structure, redundancy, readability. Not in scope — deliberately narrow to avoid scope-drift.

Coverage is multi-axis; this reviewer owns one axis.

## Anti-Pattern Catalog

Seed entries. Append when a new pattern is observed in the wild.

### 1. Test asserts presence, not correctness

**Symptom:** `assertChartRendered()`, `assertComponentMounts()`, `assertNoCrash()`.

**Why bad:** The surface-level assertion passes on a broken output. A chart with all data collapsed into one category still renders. A component with stale state still mounts. A function returning `null` silently still doesn't crash.

**Fix:** Strengthen to assert the **semantic claim** the feature is making. If the spec says "chart shows hazard across four LTV bands," the test asserts four bands each have data. If the spec says "returns user's balance," the test asserts the returned number matches a fixture, not just that *something* was returned.

**Origin incident:** 2026-04-17 Hazard-by-LTV chart bug.

### 2. Tests exhaustive on happy path, silent on error paths

**Symptom:** 20 tests covering "user logs in successfully with valid credentials, navigates to page, sees widget, clicks button, sees result." Zero tests covering "API returns 500," "API times out," "API returns malformed JSON," "user is logged out mid-flow," "rate limit hit."

**Why bad:** Happy paths are the easy half. Every external call is a failure mode worth testing — because every external call *will* fail eventually, and the handling is the part nobody verified.

**Fix:** For each external dependency in the tested code, add at least one failure-path test. Timeout, permission-denied, malformed-response, rate-limit. Use network mocking (MSW, nock, Playwright route interception) to inject the failure deterministically.

## Related Skills

- **`SKILLS/data-audit-qa.md`** — a different kind of coverage. That skill verifies numbers are right against external ground truth; this skill verifies that tests check the right things. Both run for data-heavy features.
- **`SKILLS/perceived-latency.md`** — a different QA axis (functional vs perf vs UX). Test-completeness sits inside "functional."
- **`SKILLS/platform-stewardship.md`** — why we accumulate narrow-scope reviewers. Each one catches a class of structural miss that self-review cannot. infra-reviewer, visual-reviewer, speedup-reviewer, now test-completeness — each is a lens self-review doesn't wear.
- **`.claude/agents/test-completeness-reviewer.md`** — the agent brief this skill dispatches to.
