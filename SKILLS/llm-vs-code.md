# Skill: LLMs for Judgment, Code for Computation

## Guiding Principle

**A deterministic step inside a prompt is a tax. An LLM call inside a deterministic pipeline is a fragility.** Pick the right tool for the work. If the operation has a precise specification, write code. If it requires contextual judgment, use an LLM.

## The Decision Test

Ask two questions:

1. **Can I write a spec for this that produces the same output every time given the same input?**
   - Yes → code.
   - No → LLM.

2. **Does this require understanding nuance, context, or ambiguity that I can't enumerate?**
   - Yes → LLM.
   - No → code.

When both answers agree, the call is obvious. When they disagree, the tie-breaker is cost and reliability — code wins by default because it's cheaper, faster, and traceable; LLM is the exception that must justify itself.

## What Belongs Where

### Code (deterministic)

- Arithmetic, aggregation, joins, filters on exact values.
- Parsing well-specified formats: JSON, CSV, XML with schema, Protobuf, known-shape HTML tables.
- Known API calls with known parameters.
- File operations: copy, move, compress, checksum, diff.
- Protocol handling: HTTP, SQL, SMTP.
- Formula evaluation with defined variables.
- Statistical outlier detection (z-score, IQR bounds, monotonicity checks).
- Regex on known-format strings.
- Deploy / CI / ops automation.
- Any step where non-determinism would corrupt a data pipeline.

### LLM (subjective)

- Classification with fuzzy edges ("is this chain a gym competitor?" when competitiveness is contextual).
- Extraction from unstructured narrative (management commentary, risk-factor sections, freeform customer notes).
- Judgment calls under ambiguity ("which of these findings cluster under the same root cause?").
- Novel-strategy decisions (how to approach a new scraping target whose flow isn't known).
- Writing, summarizing, translating, explaining.
- Code review / spec review where the judgment itself is the output.
- Tie-breaking between implementation approaches when tradeoffs aren't numerical.
- Resolving ambiguity in a user's request.

## Transition Moments

LLMs discover patterns; code exploits them. Once an LLM has mapped out how a task works, migrate to code:

- **After N successful runs of the same LLM task, pattern-mine it.** If Claude has navigated a site's checkout flow 5 times with consistent steps, write the deterministic wizard from the mined pattern. See `car-offers/lib/carmax.js` for the working example — LLM-nav discovered the flow, the deterministic wizard shipped it, and the per-run cost dropped from minutes of tokens to ~45 seconds of headless Chrome.
- **After the schema stabilizes, code the parser.** If Claude has extracted the same fields from the same filing type 10 times, write the XBRL / regex parser. See the `carvana_abs` parser — label-anchored, handles all historical format variants, no LLM in the loop.
- **After the decision criterion stabilizes, code the classifier.** If the same 4 classification categories get the same LLM verdicts consistently, promote the rules to code with the LLM as a tiebreaker / fallback.

The meta-rule: **any time an LLM does the same well-defined thing twice, consider migrating.** Not every LLM use migrates — some tasks are irreducibly judgment-y — but unexamined LLM reliance accumulates cost and non-determinism.

## Anti-Patterns From Our Platform

- **Using Claude to sum a column.** Happened in an early audit iteration. A deterministic re-derivation would have taken 3 lines of Python and zero tokens.
- **Using Claude to format a timestamp.** `strftime` exists and costs nothing.
- **Using Claude to classify with a hard rule embedded in the prompt.** If the prompt says "classify as X if column A > 100 else Y," the LLM is just executing the rule — write the rule as code.
- **Writing a deterministic pipeline and then "having Claude double-check."** If the code is right, the LLM check is noise. If the code is wrong, fix the code. Don't use an LLM as a trust fallback; use unit tests.
- **Calling an LLM to parse error messages into categories.** Error categorization with a known enum is a dictionary lookup, not a prompt.

## Cost Math (Why This Matters)

Rough ballpark for our platform:

- **Deterministic Python function call:** ~1 ms, $0 (compute is paid per-hour anyway).
- **Claude Sonnet call with ~1k input / 500 output tokens:** ~2-5 seconds, ~$0.01.
- **Claude Opus call with 10k context:** ~10-30 seconds, ~$0.15.

A pipeline that runs an LLM call per row on a 10k-row dataset costs ~$100+ and takes ~10 hours. A deterministic equivalent costs ~$0 and takes seconds. This is where "why are we burning so much on this task" comes from.

## When LLMs Add Real Value

- **Bootstrapping.** You don't yet know the pattern; the LLM discovers it. Then migrate.
- **Long tail.** 95% of cases are captured by code; the 5% weird edge cases go to the LLM.
- **Human-facing text.** Summaries, explanations, error messages for non-technical users.
- **Judgment calls that genuinely lack a specification.** "Does this PR look risky?" "Is this customer's complaint legitimate?" "Which of these three phrasings reads more trustworthy?"

## Integration

- `SKILLS/data-audit-qa.md` — calculations are re-derived from first principles **in code, never copied from the implementation or re-asked of an LLM**. The audit is the canonical example of "deterministic verification over subjective re-check."
- `SKILLS/platform-stewardship.md` — migrating LLM → code after pattern stability is a stewardship move. Log it.
- `SKILLS/root-cause-analysis.md` — "the LLM got it wrong this time" is rarely the real root cause. Usually the task didn't belong on an LLM in the first place.
