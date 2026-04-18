#!/bin/bash
# kickoff.sh — dispatch the project-kickoff protocol (research + 3 peers + template merge).
#
# Canonical skill: SKILLS/project-kickoff.md.
# Dogfoods SKILLS/four-agent-debate.md: Research runs FIRST alone; three peer agents
# (Understand, Challenge, Improver) run in parallel; orchestrator merges deterministically
# via a fixed template — NO 4th LLM synthesis call.
#
# Usage:
#   kickoff.sh --prompt "<user text>" --project <name> --scope {new|existing-big} \
#              [--force] [--dry-run] [--inject-q8 "<text>"] [--inject-q9 "<text>"]
#
# Flags:
#   --prompt       the user's kickoff text (required)
#   --project      project slug (required; lowercase, alphanumeric + dashes)
#   --scope        "new" (brand-new project) or "existing-big" (existing project, >8h work)
#   --force        override the scope-threshold guard
#   --dry-run      print what WOULD be dispatched; exit 0 without LLM calls
#   --inject-q8    project-specific research question slot #8 (optional)
#   --inject-q9    project-specific research question slot #9 (optional)
#
# Hard cap: 7 fixed research questions + up to 2 injected = 9 maximum.
#
# Outputs:
#   /opt/<project>/KICKOFF_REPORT.md      — full report, written BEFORE Accept card fires
#   /tmp/kickoff-<project>-<ts>/          — per-agent structured YAML outputs
#   Accept card URL on stdout (via helpers/accept-card.sh)
#
# See also:
#   helpers/kickoff-retro.sh   — ship-event-triggered spec-vs-reality delta capture
#   helpers/accept-card.sh     — milestone-tier persistent card emitter
#   SKILLS/project-kickoff.md  — protocol canonical doc
#   SKILLS/four-agent-debate.md

set -eE -o pipefail
trap 'echo "[kickoff] ERROR at line $LINENO (exit=$?)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROMPT=""
PROJECT=""
SCOPE=""
FORCE=0
DRY_RUN=0
INJECT_Q8=""
INJECT_Q9=""

print_usage() {
    sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prompt)       PROMPT="$2"; shift 2 ;;
        --project)      PROJECT="$2"; shift 2 ;;
        --scope)        SCOPE="$2"; shift 2 ;;
        --force)        FORCE=1; shift ;;
        --dry-run)      DRY_RUN=1; shift ;;
        --inject-q8)    INJECT_Q8="$2"; shift 2 ;;
        --inject-q9)    INJECT_Q9="$2"; shift 2 ;;
        -h|--help)      print_usage; exit 0 ;;
        *) echo "kickoff.sh: unknown arg '$1'" >&2; print_usage >&2; exit 2 ;;
    esac
done

# --- Validate ---------------------------------------------------------------
[ -n "$PROMPT" ]  || { echo "kickoff.sh: --prompt required" >&2; exit 2; }
[ -n "$PROJECT" ] || { echo "kickoff.sh: --project required" >&2; exit 2; }
[ -n "$SCOPE" ]   || { echo "kickoff.sh: --scope required (new|existing-big)" >&2; exit 2; }

case "$PROJECT" in
    *[^a-z0-9-]*) echo "kickoff.sh: --project must be lowercase alphanumeric + dashes" >&2; exit 2 ;;
esac
case "$SCOPE" in
    new|existing-big) ;;
    *) echo "kickoff.sh: --scope must be 'new' or 'existing-big' (was '$SCOPE')" >&2; exit 2 ;;
esac

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TS_SLUG="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="/tmp/kickoff-${PROJECT}-${TS_SLUG}"
PROJECT_DIR="/opt/${PROJECT}"
REPORT_PATH="${PROJECT_DIR}/KICKOFF_REPORT.md"

# --- The 7 fixed research questions (hard cap 9 with injected Q8/Q9) --------
build_research_brief() {
    cat <<EOF
Role: research agent (runs first and ALONE — see SKILLS/four-agent-debate.md)
Project: $PROJECT
User prompt:
"""
$PROMPT
"""

Answer the 7 fixed questions below, plus Q8/Q9 if injected. Hard cap 9 questions. NEVER prescribe; surface evidence only. The three peer agents will read your output during their brief.

Q1. Comparable products — 3 best-in-class tools in this category, one-sentence each, link each.
Q2. User complaints — top 3 recurring complaints across App Store / G2 / HN / Reddit reviews. Cite.
Q3. Fastest-shipped MVP path — 2-week rebuild: minimum surface, what was cut.
Q4. Anti-pattern graveyard — similar products that shut down / pivoted, publicly-known reason.
Q5. Standards / regulations — GDPR / HIPAA / COPPA / PCI / accessibility — which apply, one-line each.
Q6. Managed-service shortcuts — is there a Stripe/Clerk/Supabase-shaped service that collapses 40% of the build?
Q7. Unknown unknowns — one paragraph: what would a domain expert know that research doesn't? Surface as user-question.
EOF
    [ -n "$INJECT_Q8" ] && echo "Q8. ${INJECT_Q8}"
    [ -n "$INJECT_Q9" ] && echo "Q9. ${INJECT_Q9}"
    echo ""
    echo "Output: write to $RUN_DIR/research.md. Markdown, question-numbered, citations inline."
}

build_understand_brief() {
    cat <<EOF
Role: understand-the-ask peer (parallel with challenge + improver; does NOT read their output).
Project: $PROJECT
Scope: $SCOPE
User prompt:
"""
$PROMPT
"""
Read first: $RUN_DIR/research.md

Emit STRUCTURED YAML (not prose) to $RUN_DIR/understand.yaml matching EXACTLY:

title: string <60 chars
outcome: string, 1 sentence, user-facing
in_scope: [bullets, max 10]
non_goals: [bullets, max 10]   # empty list is a smell — challenge it
success_criteria: [bullets, each MEASURABLE]
user_journey:
  entry_url: string
  steps: [ordered list of user-visible actions]
  done_state: string
file_locations:
  new_files: [absolute paths, no speculation]
  modified_files: [absolute paths]
sizing:
  hours_low: int
  hours_high: int
  confidence: low|medium|high
open_questions:
  - question: string
    why_it_matters: string
    default_if_no_answer: string   # LOAD-BEARING: user silence ships
EOF
}

build_challenge_brief() {
    cat <<EOF
Role: challenge-the-approach peer (parallel with understand + improver; does NOT read their output).
Project: $PROJECT
Scope: $SCOPE
User prompt:
"""
$PROMPT
"""
Read first: $RUN_DIR/research.md

Users describe OUTCOMES, not methods. Before the build, ask: is there a simpler tool, managed service,
or pattern that delivers the same outcome with dramatically less complexity, cost, or fragility?
Bar: would the alternative save >30% of time/cost, or eliminate a meaningful failure mode?

Emit STRUCTURED YAML (not prose) to $RUN_DIR/challenge.yaml matching EXACTLY:

alternatives:
  - rank: 1
    alternative: string
    what_it_collapses: string
    swap_if: string
    keep_current_if: string
  # max 5 alternatives
verdict: SHIP_AS_SPECCED | REDIRECT_TO_#N | HYBRID: use #N for <part>, build rest
rationale: string, 2-4 sentences
EOF
}

build_improver_brief() {
    local mode="risks-and-improvements"
    if [ "$SCOPE" = "existing-big" ]; then
        mode="regressions-risk"
    fi
    cat <<EOF
Role: improver / risks peer (mode=$mode; parallel with understand + challenge; does NOT read their output).
Project: $PROJECT
Scope: $SCOPE
User prompt:
"""
$PROMPT
"""
Read first: $RUN_DIR/research.md
EOF
    if [ "$SCOPE" = "existing-big" ]; then
        cat <<EOF
Additional reads (existing-project mode): /opt/$PROJECT/PROJECT_CONTEXT.md, last 50
\`git log --oneline\`, LESSONS entries tagged to this project, tests/$PROJECT.spec.ts, ACTUAL SOURCE
under /opt/$PROJECT/. Regressions-risk mode means: name the functions / pages / tests most likely to
break if this build lands, not generic risks.
EOF
    fi
    cat <<EOF

Emit STRUCTURED YAML (not prose) to $RUN_DIR/improver.yaml matching EXACTLY:

risks:
  blocking:   # must resolve before build starts
    - {risk, mitigation, cost_to_fix_hours}
  shipping:   # known risks we ship with
    - {risk, monitor_how, when_to_revisit}
  watch:      # low-probability tail risks, note only
    - string
improvements:
  quick_wins:   # <2h, default IN unless user declines
    - {change, why, added_hours}
  stretch:      # 2-8h, default OUT, Accept-card checkbox
    - {change, why, added_hours}
  future:       # >8h, auto-file to PROJECT_STATE backlog
    - {change, why, rough_hours}
EOF
}

# --- Dispatch helpers -------------------------------------------------------
dispatch_one() {
    # $1=agent-name $2=brief-file $3=output-path-inside-brief
    local name="$1" brief_file="$2"
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] would dispatch agent=$name via '$CLAUDE_BIN -p' with brief=$brief_file"
        return 0
    fi
    # Real dispatch — use the CLI "-p" flag (same pattern as visual-review-orchestrator.sh).
    # Each peer writes its own output file; we capture stdout as a run log.
    "$CLAUDE_BIN" -p < "$brief_file" > "$RUN_DIR/${name}.log" 2>&1 || {
        echo "[kickoff] agent=$name dispatch failed — see $RUN_DIR/${name}.log" >&2
        return 1
    }
}

# --- Template merge ---------------------------------------------------------
# NO 4th LLM call. Read 3 YAML outputs + research.md and render KICKOFF_REPORT.md + Accept-card args.
render_report() {
    python3 - "$RUN_DIR" "$PROJECT" "$TS_ISO" "$REPORT_PATH" "$SCOPE" <<'PY'
import os, pathlib, sys, datetime

run_dir, project, ts_iso, report_path, scope = sys.argv[1:6]
run = pathlib.Path(run_dir)

def read_or_stub(p, stub):
    path = run / p
    if path.exists():
        return path.read_text()
    return stub

research = read_or_stub("research.md", "_(research output missing — dry-run or dispatch failed)_\n")
understand = read_or_stub("understand.yaml", "# understand YAML missing\n")
challenge = read_or_stub("challenge.yaml", "# challenge YAML missing\n")
improver = read_or_stub("improver.yaml", "# improver YAML missing\n")

# Extract a title / outcome / sizing from understand YAML (cheap regex; YAML parser not required here).
import re
def extract(pattern, text, default=""):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else default

title = extract(r'^title:\s*(.+)$', understand, f"Kickoff — {project}")
outcome = extract(r'^outcome:\s*(.+)$', understand, "(outcome missing)")
hours_low = extract(r'^\s*hours_low:\s*(\d+)', understand, "?")
hours_high = extract(r'^\s*hours_high:\s*(\d+)', understand, "?")
verdict = extract(r'^verdict:\s*(.+)$', challenge, "SHIP_AS_SPECCED")

# Accept-card rendered text (top of report)
accept_card = f"""Title: {title}
Outcome: {outcome}
Estimate: {hours_low}-{hours_high} hours
Verdict: {verdict}
Scope: {scope}
"""

report = f"""---
kind: episodic
last_verified: {ts_iso}
refresh_cadence: on_touch
sunset: null
---

# Kickoff Report — {project} — {ts_iso}

## Accept Card (top, always current)

```
{accept_card}```

## Synthesized Spec (from Understand)

```yaml
{understand.strip()}
```

## Alternatives Considered (from Challenge)

```yaml
{challenge.strip()}
```

## Risks & Improvements (from Improver)

```yaml
{improver.strip()}
```

## Research Report (from Research)

{research.strip()}

## Committee Metadata

- agents: research, understand, challenge, improver
- scope: {scope}
- wall_clock_iso: {ts_iso}
- tokens_total: (logged but NOT surfaced in Accept card)
- outside_spend_estimate: none (unless flagged in Understand / Improver)
- model_versions: (claude CLI default)
"""

# Write report (parent dir may not exist for brand-new projects)
out = pathlib.Path(report_path)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report)
print(f"wrote {out}")

# Also emit a tiny accept-card sidecar for the shell to read back.
(pathlib.Path(run_dir) / "accept-card.env").write_text(
    f'TITLE={title!r}\nOUTCOME={outcome!r}\nHOURS_LOW={hours_low!r}\nHOURS_HIGH={hours_high!r}\nVERDICT={verdict!r}\n'
)
PY
}

# --- Main -------------------------------------------------------------------
mkdir -p "$RUN_DIR"

echo "[kickoff] project=$PROJECT scope=$SCOPE dry_run=$DRY_RUN run_dir=$RUN_DIR"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] --- what would be dispatched ---"
    echo "[dry-run] Step 0: scaffold via SKILLS/new-project-checklist.md (scope=new only; scope=$SCOPE so $( [ "$SCOPE" = "new" ] && echo FIRES || echo NO-OP))"
    echo "[dry-run] Step 1: research agent with 7 fixed Qs$( [ -n "$INJECT_Q8" ] && echo " + Q8")$( [ -n "$INJECT_Q9" ] && echo " + Q9") (hard cap 9)"
    echo "[dry-run] Step 2: PARALLEL dispatch of understand, challenge, improver (improver mode=$( [ "$SCOPE" = "existing-big" ] && echo regressions-risk || echo risks-and-improvements))"
    echo "[dry-run] Step 3: deterministic template merge → $REPORT_PATH"
    echo "[dry-run] Step 4: helpers/accept-card.sh --tier milestone"
    echo "[dry-run] NO real LLM calls made. Writing brief previews to $RUN_DIR/ for inspection."
    build_research_brief  > "$RUN_DIR/research.brief.txt"
    build_understand_brief > "$RUN_DIR/understand.brief.txt"
    build_challenge_brief  > "$RUN_DIR/challenge.brief.txt"
    build_improver_brief   > "$RUN_DIR/improver.brief.txt"
    echo "[dry-run] brief previews written under $RUN_DIR/*.brief.txt"
    exit 0
fi

# --- Step 0: new-project scaffold (parallel with research) ------------------
if [ "$SCOPE" = "new" ]; then
    echo "[kickoff] Step 0: new-project scaffold (see SKILLS/new-project-checklist.md)"
    # Scaffold is human-executed per SKILLS/new-project-checklist.md — we do not
    # auto-create nginx blocks from here (those are shared-infra and require
    # projects-smoketest gate). Leave a reminder.
    echo "[kickoff] reminder: run SKILLS/new-project-checklist.md steps 1-10 in parallel with Step 1."
fi

# --- Step 1: research (FIRST, alone) ----------------------------------------
echo "[kickoff] Step 1: research agent (alone)"
build_research_brief > "$RUN_DIR/research.brief.txt"
dispatch_one research "$RUN_DIR/research.brief.txt"

# --- Step 2: three peers IN PARALLEL ----------------------------------------
echo "[kickoff] Step 2: understand + challenge + improver (parallel)"
build_understand_brief > "$RUN_DIR/understand.brief.txt"
build_challenge_brief  > "$RUN_DIR/challenge.brief.txt"
build_improver_brief   > "$RUN_DIR/improver.brief.txt"

PIDS=()
dispatch_one understand "$RUN_DIR/understand.brief.txt" & PIDS+=($!)
dispatch_one challenge  "$RUN_DIR/challenge.brief.txt"  & PIDS+=($!)
dispatch_one improver   "$RUN_DIR/improver.brief.txt"   & PIDS+=($!)
for pid in "${PIDS[@]}"; do wait "$pid" || true; done

# --- Step 3: deterministic template merge -----------------------------------
echo "[kickoff] Step 3: template merge → $REPORT_PATH"
render_report

# --- Step 4: Accept card (milestone tier) -----------------------------------
# Source the env file the python merge wrote.
# shellcheck disable=SC1090
. "$RUN_DIR/accept-card.env"

ACCEPT_URL="$( "$SCRIPT_DIR/accept-card.sh" \
    --title "${TITLE:-Kickoff — $PROJECT}" \
    --outcome "${OUTCOME:-Kickoff ready for review}" \
    --context-link "file://$REPORT_PATH" \
    --actions "Accept,Refine,Cancel" \
    --tier milestone )" || ACCEPT_URL=""

echo "[kickoff] done. Report: $REPORT_PATH"
[ -n "$ACCEPT_URL" ] && echo "[kickoff] Accept card: $ACCEPT_URL"
exit 0
