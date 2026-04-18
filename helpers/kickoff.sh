#!/bin/bash
# kickoff.sh — dispatch the project-kickoff protocol and drive the refinement loop.
#
# Canonical skill: SKILLS/project-kickoff.md.
# Dogfoods SKILLS/four-agent-debate.md: Research runs FIRST alone; three peer agents
# (Understand, Challenge, Improver) run in parallel; orchestrator merges deterministically
# via a fixed template — NO 4th LLM synthesis call. Disagreements between peers are
# surfaced as first-class Draft-Plan-card elements (see feedback_committee_collaborative.md).
#
# ---------- USAGE ----------
#
# Initial dispatch (round 1):
#   kickoff.sh --prompt "<user text>" --project <name> --scope {new|existing-big} \
#              [--force] [--dry-run] [--inject-q8 "..."] [--inject-q9 "..."]
#
# Refinement subcommands (iterate round N → N+1):
#   kickoff.sh ask       --project X --agent {understand|challenge|improver} --question "..."
#   kickoff.sh pushback  --project X --on <id> --text "..."
#   kickoff.sh constrain --project X --text "..."
#   kickoff.sh answer    --project X --question <oq-id> --text "..."
#   kickoff.sh refine    --project X                 # re-render card only; no LLM
#
# Terminal actions:
#   kickoff.sh finalize  --project X                 # stamp, seed state, dispatch builder
#   kickoff.sh cancel    --project X                 # scaffold rollback + graveyard move
#   kickoff.sh accept    --project X                 # deprecated shim → finalize
#
# Every refinement subcommand supports --dry-run (prints routing plan, no LLM calls).
#
# Hard cap: 7 fixed research questions + up to 2 injected = 9 maximum.
#
# Outputs:
#   /opt/<project>/KICKOFF_REPORT.md                 — full report, draft | finalized
#   /opt/<project>/.kickoff-state/                   — latest per-agent YAML + round log
#   /tmp/kickoff-<project>-<ts>/                     — per-round dispatch scratch
#   /var/www/landing/accept-cards/kickoff-<project>-r<N>.html   — Draft Plan card per round
#   Card URL on stdout.
#
# See also:
#   helpers/kickoff-retro.sh   — ship-event-triggered spec-vs-reality delta capture
#   helpers/accept-card.sh     — milestone-tier persistent card emitter (--kind draft-plan)
#   SKILLS/project-kickoff.md  — protocol canonical doc
#   SKILLS/four-agent-debate.md

set -eE -o pipefail
trap 'echo "[kickoff] ERROR at line $LINENO (exit=$?)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

print_usage() {
    sed -n '1,40p' "$0" | sed 's/^# \{0,1\}//'
}

CLAUDE_BIN="${CLAUDE_BIN:-claude}"

# --- shared helpers ---------------------------------------------------------

project_dir()     { echo "/opt/$1"; }
state_dir()       { echo "/opt/$1/.kickoff-state"; }
report_path()     { echo "/opt/$1/KICKOFF_REPORT.md"; }
round_log_path()  { echo "/opt/$1/.kickoff-state/round.log"; }

validate_project() {
    case "$1" in
        *[^a-z0-9-]*|"") echo "kickoff.sh: --project must be lowercase alphanumeric + dashes (got '$1')" >&2; exit 2 ;;
    esac
}

ensure_state() {
    mkdir -p "$(state_dir "$1")"
}

next_round() {
    # Returns the next round number (1-based). Reads round.log for the highest r<N>.
    local log; log="$(round_log_path "$1")"
    [ -f "$log" ] || { echo 1; return; }
    awk -F'|' '/^r[0-9]+/ {gsub(/^r/,"",$1); if($1+0>max) max=$1+0} END {print (max?max+1:1)}' "$log"
}

append_round() {
    # $1=project $2=action $3=agents-re-ran(csv or "-") $4=summary
    local proj="$1" action="$2" agents="$3" summary="$4"
    local log; log="$(round_log_path "$proj")"
    local rn; rn="$(next_round "$proj")"
    local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'r%d|%s|%s|%s|%s\n' "$rn" "$ts" "$action" "$agents" "$summary" >> "$log"
    echo "$rn"
}

current_round() {
    local log; log="$(round_log_path "$1")"
    [ -f "$log" ] || { echo 0; return; }
    awk -F'|' '/^r[0-9]+/ {gsub(/^r/,"",$1); if($1+0>max) max=$1+0} END {print max+0}' "$log"
}

# --- Brief builders (round-1 initial dispatch) ------------------------------

build_research_brief() {
    local prompt="$1" project="$2" run_dir="$3" q8="$4" q9="$5"
    cat <<EOF
Role: research agent (runs first and ALONE — see SKILLS/four-agent-debate.md)
Project: $project
User prompt:
"""
$prompt
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
    [ -n "$q8" ] && echo "Q8. ${q8}"
    [ -n "$q9" ] && echo "Q9. ${q9}"
    echo ""
    echo "Output: write to $run_dir/research.md. Markdown, question-numbered, citations inline."
}

_disagreements_block() {
    cat <<'EOF'

You MUST emit a disagreements_with_others block at the bottom of your YAML. Each entry:
  - other_agent: understand | challenge | improver
    my_position: string
    their_position: string
    tradeoff: string
    my_recommendation: keep_mine | defer_to_them | hybrid
    rationale: string

You have NOT seen the other peers' output during this run — emit entries against the positions
you anticipate they will take based on their archetype. Empty list is legitimate ONLY if you
genuinely concur with both. See SKILLS/four-agent-debate.md "Disagreements must be user-visible".
EOF
}

build_understand_brief() {
    local prompt="$1" project="$2" scope="$3" run_dir="$4" constraint_preamble="$5"
    [ -n "$constraint_preamble" ] && printf '%s\n\n' "$constraint_preamble"
    cat <<EOF
Role: understand-the-ask peer (parallel with challenge + improver; does NOT read their output).
Project: $project
Scope: $scope
User prompt:
"""
$prompt
"""
Read first: $run_dir/research.md

Emit STRUCTURED YAML (not prose) to $run_dir/understand.yaml matching EXACTLY:

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
  - id: oq1            # stable id for user-answer routing
    question: string
    why_it_matters: string
    default_if_no_answer: string   # LOAD-BEARING: user silence ships
EOF
    _disagreements_block
}

build_challenge_brief() {
    local prompt="$1" project="$2" scope="$3" run_dir="$4" constraint_preamble="$5"
    [ -n "$constraint_preamble" ] && printf '%s\n\n' "$constraint_preamble"
    cat <<EOF
Role: challenge-the-approach peer (parallel with understand + improver; does NOT read their output).
Project: $project
Scope: $scope
User prompt:
"""
$prompt
"""
Read first: $run_dir/research.md

Users describe OUTCOMES, not methods. Before the build, ask: is there a simpler tool, managed service,
or pattern that delivers the same outcome with dramatically less complexity, cost, or fragility?
Bar: would the alternative save >30% of time/cost, or eliminate a meaningful failure mode?

Emit STRUCTURED YAML (not prose) to $run_dir/challenge.yaml matching EXACTLY:

alternatives:
  - id: alt1           # stable id for user-pushback routing
    rank: 1
    alternative: string
    what_it_collapses: string
    swap_if: string
    keep_current_if: string
  # max 5 alternatives
verdict: SHIP_AS_SPECCED | REDIRECT_TO_#N | HYBRID: use #N for <part>, build rest
rationale: string, 2-4 sentences
EOF
    _disagreements_block
}

build_improver_brief() {
    local prompt="$1" project="$2" scope="$3" run_dir="$4" constraint_preamble="$5"
    local mode="risks-and-improvements"
    [ "$scope" = "existing-big" ] && mode="regressions-risk"
    [ -n "$constraint_preamble" ] && printf '%s\n\n' "$constraint_preamble"
    cat <<EOF
Role: improver / risks peer (mode=$mode; parallel with understand + challenge; does NOT read their output).
Project: $project
Scope: $scope
User prompt:
"""
$prompt
"""
Read first: $run_dir/research.md
EOF
    if [ "$scope" = "existing-big" ]; then
        cat <<EOF
Additional reads (existing-project mode): /opt/$project/PROJECT_CONTEXT.md, last 50
\`git log --oneline\`, LESSONS entries tagged to this project, tests/$project.spec.ts, ACTUAL SOURCE
under /opt/$project/. Regressions-risk mode means: name the functions / pages / tests most likely to
break if this build lands, not generic risks.
EOF
    fi
    cat <<EOF

Emit STRUCTURED YAML (not prose) to $run_dir/improver.yaml matching EXACTLY:

risks:
  blocking:   # must resolve before build starts
    - {id: blk1, risk, mitigation, cost_to_fix_hours}
  shipping:   # known risks we ship with
    - {id: shp1, risk, monitor_how, when_to_revisit}
  watch:      # low-probability tail risks, note only
    - string
improvements:
  quick_wins:   # <2h, default IN unless user declines
    - {id: qw1, change, why, added_hours}
  stretch:      # 2-8h, default OUT, Draft-Plan-card checkbox
    - {id: st1, change, why, added_hours}
  future:       # >8h, auto-file to PROJECT_STATE backlog
    - {id: ft1, change, why, rough_hours}
EOF
    _disagreements_block
}

# --- Dispatch helpers -------------------------------------------------------

dispatch_one() {
    # $1=agent-name $2=brief-file $3=run-dir $4=dry-run-flag
    local name="$1" brief_file="$2" run_dir="$3" dry="$4"
    if [ "$dry" = "1" ]; then
        echo "[dry-run] would dispatch agent=$name via '$CLAUDE_BIN -p' with brief=$brief_file"
        return 0
    fi
    "$CLAUDE_BIN" -p < "$brief_file" > "$run_dir/${name}.log" 2>&1 || {
        echo "[kickoff] agent=$name dispatch failed — see $run_dir/${name}.log" >&2
        return 1
    }
}

# --- Render report + card ---------------------------------------------------
#
# render_report reads the CURRENT persisted YAML under <state>/ (not run_dir)
# because refinement subcommands mutate state without a full re-dispatch. The
# run_dir only matters for the initial dispatch in round 1.

render_report() {
    local project="$1" scope="$2" round="$3"
    local state; state="$(state_dir "$project")"
    local rep; rep="$(report_path "$project")"
    local log; log="$(round_log_path "$project")"
    local ts_iso; ts_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    python3 - "$state" "$project" "$ts_iso" "$rep" "$scope" "$round" "$log" <<'PY'
import os, pathlib, sys, re

state_dir, project, ts_iso, report_path, scope, round_n, log_path = sys.argv[1:8]
state = pathlib.Path(state_dir)

def read_or_stub(name, stub):
    p = state / name
    return p.read_text() if p.exists() else stub

research   = read_or_stub("research.md",    "_(research output missing)_\n")
understand = read_or_stub("understand.yaml","# understand YAML missing\n")
challenge  = read_or_stub("challenge.yaml", "# challenge YAML missing\n")
improver   = read_or_stub("improver.yaml",  "# improver YAML missing\n")

def extract(pattern, text, default=""):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else default

title      = extract(r'^title:\s*(.+)$',       understand, f"Kickoff — {project}")
outcome    = extract(r'^outcome:\s*(.+)$',     understand, "(outcome missing)")
hours_low  = extract(r'^\s*hours_low:\s*(\d+)', understand, "?")
hours_high = extract(r'^\s*hours_high:\s*(\d+)',understand, "?")
verdict    = extract(r'^verdict:\s*(.+)$',     challenge,  "SHIP_AS_SPECCED")

# Status = draft unless a FINALIZED sentinel file is present.
status = "finalized" if (state / "FINALIZED").exists() else "draft"

# Round-history markdown from round.log
round_history_md = ""
if pathlib.Path(log_path).exists():
    for line in pathlib.Path(log_path).read_text().splitlines():
        if not line.strip(): continue
        parts = line.split("|", 4)
        if len(parts) < 5: continue
        rn, ts, action, agents, summary = parts
        link = f"/accept-cards/kickoff-{project}-{rn}.html"
        round_history_md += f"- {rn} {ts} **{action}** [agents: {agents}] {summary} — [card]({link})\n"
if not round_history_md:
    round_history_md = "- (none yet)\n"

draft_plan = f"""Round r{round_n} — {project}
Title: {title}
Outcome: {outcome}
Estimate: {hours_low}-{hours_high} hours
Verdict: {verdict}
Scope: {scope}
Status: {status}
"""

report = f"""---
kind: episodic
last_verified: {ts_iso}
refresh_cadence: on_touch
sunset: null
status: {status}
---

# Kickoff Report — {project} — {ts_iso}

## Draft Plan (top, always current)

```
{draft_plan}```

## Round History

{round_history_md}

## Synthesized Spec (from Understand, latest YAML)

```yaml
{understand.strip()}
```

## Alternatives Considered (from Challenge, latest YAML)

```yaml
{challenge.strip()}
```

## Risks & Improvements (from Improver, latest YAML)

```yaml
{improver.strip()}
```

## Research Report (from Research, immutable after Step 1)

{research.strip()}

## Committee Metadata

- agents: research, understand, challenge, improver
- scope: {scope}
- rounds: {round_n}
- wall_clock_iso_latest: {ts_iso}
- outside_spend_estimate: none (unless flagged in Understand / Improver)
- model_versions: (claude CLI default)
"""

out = pathlib.Path(report_path)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report)

# Emit env sidecar for the shell to source when calling accept-card.sh.
(state / "card.env").write_text(
    f'TITLE={title!r}\n'
    f'OUTCOME={outcome!r}\n'
    f'HOURS_LOW={hours_low!r}\n'
    f'HOURS_HIGH={hours_high!r}\n'
    f'VERDICT={verdict!r}\n'
    f'STATUS={status!r}\n'
)
print(f"wrote {out}")
PY
}

emit_draft_plan_card() {
    # $1=project $2=round
    local project="$1" round="$2"
    local state; state="$(state_dir "$project")"
    # shellcheck disable=SC1090
    . "$state/card.env"
    local card_id="kickoff-${project}-r${round}"
    "$SCRIPT_DIR/accept-card.sh" \
        --kind draft-plan \
        --id "$card_id" \
        --title "${TITLE:-Kickoff — $project}" \
        --outcome "${OUTCOME:-Draft plan ready for review}" \
        --context-link "file://$(report_path "$project")" \
        --actions "Finalize,Cancel" \
        --tier milestone \
        --draft-state-dir "$state" \
        --round "$round" 2>/dev/null || true
    echo "https://casinv.dev/accept-cards/${card_id}.html"
}

# ----------------------------------------------------------------------------
# Round-1 initial dispatch (when no subcommand is given but --prompt is).
# ----------------------------------------------------------------------------

cmd_initial() {
    local PROMPT="" PROJECT="" SCOPE="" FORCE=0 DRY_RUN=0 Q8="" Q9=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --prompt)       PROMPT="$2"; shift 2 ;;
            --project)      PROJECT="$2"; shift 2 ;;
            --scope)        SCOPE="$2"; shift 2 ;;
            --force)        FORCE=1; shift ;;
            --dry-run)      DRY_RUN=1; shift ;;
            --inject-q8)    Q8="$2"; shift 2 ;;
            --inject-q9)    Q9="$2"; shift 2 ;;
            -h|--help)      print_usage; exit 0 ;;
            *) echo "kickoff.sh: unknown arg '$1'" >&2; print_usage >&2; exit 2 ;;
        esac
    done

    [ -n "$PROMPT" ]  || { echo "kickoff.sh: --prompt required" >&2; exit 2; }
    [ -n "$PROJECT" ] || { echo "kickoff.sh: --project required" >&2; exit 2; }
    [ -n "$SCOPE" ]   || { echo "kickoff.sh: --scope required (new|existing-big)" >&2; exit 2; }
    validate_project "$PROJECT"
    case "$SCOPE" in new|existing-big) ;; *) echo "kickoff.sh: --scope must be 'new' or 'existing-big'" >&2; exit 2 ;; esac

    local TS_SLUG; TS_SLUG="$(date -u +%Y%m%dT%H%M%SZ)"
    local RUN_DIR="/tmp/kickoff-${PROJECT}-${TS_SLUG}"
    mkdir -p "$RUN_DIR"
    ensure_state "$PROJECT"

    echo "[kickoff] project=$PROJECT scope=$SCOPE dry_run=$DRY_RUN run_dir=$RUN_DIR"

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] --- what would be dispatched ---"
        echo "[dry-run] Step 0: scaffold (scope=$SCOPE → $( [ "$SCOPE" = "new" ] && echo FIRES || echo NO-OP))"
        echo "[dry-run] Step 1: research agent with 7 fixed Qs$( [ -n "$Q8" ] && echo " + Q8")$( [ -n "$Q9" ] && echo " + Q9") (hard cap 9)"
        echo "[dry-run] Step 2: PARALLEL dispatch of understand, challenge, improver (mode=$( [ "$SCOPE" = "existing-big" ] && echo regressions-risk || echo risks-and-improvements))"
        echo "[dry-run] Step 3: deterministic template merge → $(report_path "$PROJECT")"
        echo "[dry-run] Step 4: emit Draft Plan card at /var/www/landing/accept-cards/kickoff-${PROJECT}-r1.html"
        echo "[dry-run] Step 5: refinement loop awaits user (ask|pushback|constrain|answer → re-render; finalize|cancel → terminal)"
        build_research_brief   "$PROMPT" "$PROJECT" "$RUN_DIR" "$Q8" "$Q9" > "$RUN_DIR/research.brief.txt"
        build_understand_brief "$PROMPT" "$PROJECT" "$SCOPE"   "$RUN_DIR" "" > "$RUN_DIR/understand.brief.txt"
        build_challenge_brief  "$PROMPT" "$PROJECT" "$SCOPE"   "$RUN_DIR" "" > "$RUN_DIR/challenge.brief.txt"
        build_improver_brief   "$PROMPT" "$PROJECT" "$SCOPE"   "$RUN_DIR" "" > "$RUN_DIR/improver.brief.txt"
        echo "[dry-run] brief previews written under $RUN_DIR/*.brief.txt"
        exit 0
    fi

    # --- Step 1 ---
    echo "[kickoff] Step 1: research agent (alone)"
    build_research_brief "$PROMPT" "$PROJECT" "$RUN_DIR" "$Q8" "$Q9" > "$RUN_DIR/research.brief.txt"
    dispatch_one research "$RUN_DIR/research.brief.txt" "$RUN_DIR" 0

    # --- Step 2 ---
    echo "[kickoff] Step 2: understand + challenge + improver (parallel)"
    build_understand_brief "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "" > "$RUN_DIR/understand.brief.txt"
    build_challenge_brief  "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "" > "$RUN_DIR/challenge.brief.txt"
    build_improver_brief   "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "" > "$RUN_DIR/improver.brief.txt"

    local PIDS=()
    dispatch_one understand "$RUN_DIR/understand.brief.txt" "$RUN_DIR" 0 & PIDS+=($!)
    dispatch_one challenge  "$RUN_DIR/challenge.brief.txt"  "$RUN_DIR" 0 & PIDS+=($!)
    dispatch_one improver   "$RUN_DIR/improver.brief.txt"   "$RUN_DIR" 0 & PIDS+=($!)
    for pid in "${PIDS[@]}"; do wait "$pid" || true; done

    # Persist to state_dir so refinement subcommands can mutate incrementally.
    local STATE; STATE="$(state_dir "$PROJECT")"
    cp "$RUN_DIR/research.md"     "$STATE/research.md"     2>/dev/null || true
    cp "$RUN_DIR/understand.yaml" "$STATE/understand.yaml" 2>/dev/null || true
    cp "$RUN_DIR/challenge.yaml"  "$STATE/challenge.yaml"  2>/dev/null || true
    cp "$RUN_DIR/improver.yaml"   "$STATE/improver.yaml"   2>/dev/null || true
    echo "$PROMPT" > "$STATE/prompt.txt"
    echo "$SCOPE"  > "$STATE/scope.txt"

    local RN; RN="$(append_round "$PROJECT" "initial-dispatch" "research,understand,challenge,improver" "round 1: committee dispatch")"

    # --- Step 3 ---
    render_report "$PROJECT" "$SCOPE" "$RN"

    # --- Step 4 ---
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[kickoff] done. Report: $(report_path "$PROJECT")"
    echo "[kickoff] Draft Plan card (round $RN): $URL"
}

# ----------------------------------------------------------------------------
# Refinement subcommands
# ----------------------------------------------------------------------------

cmd_ask() {
    local PROJECT="" AGENT="" QUESTION="" DRY_RUN=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --project)  PROJECT="$2"; shift 2 ;;
            --agent)    AGENT="$2"; shift 2 ;;
            --question) QUESTION="$2"; shift 2 ;;
            --dry-run)  DRY_RUN=1; shift ;;
            *) echo "ask: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] && [ -n "$AGENT" ] && [ -n "$QUESTION" ] || { echo "ask: --project --agent --question all required" >&2; exit 2; }
    validate_project "$PROJECT"
    case "$AGENT" in understand|challenge|improver) ;; *) echo "ask: --agent must be one of understand|challenge|improver" >&2; exit 2 ;; esac
    ensure_state "$PROJECT"

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ROUTING: ask --agent=$AGENT --question=\"$QUESTION\""
        echo "[dry-run] single-agent LLM call to $AGENT archetype; prior YAML loaded as context"
        echo "[dry-run] response will be appended to state/answers.md and surfaced on next Draft Plan card"
        echo "[dry-run] NO merge re-run required; NO full dispatch"
        exit 0
    fi

    local STATE; STATE="$(state_dir "$PROJECT")"
    local PRIOR="$STATE/${AGENT}.yaml"
    [ -f "$PRIOR" ] || { echo "ask: no prior $AGENT YAML at $PRIOR — run round-1 dispatch first" >&2; exit 1; }

    local BRIEF="$STATE/ask-${AGENT}.brief.txt"
    {
      echo "Role: $AGENT peer (answering a user Ask — single-agent, inline response)."
      echo "Project: $PROJECT"
      echo ""
      echo "Your prior YAML output:"
      echo "-----"
      cat "$PRIOR"
      echo "-----"
      echo ""
      echo "User's question: $QUESTION"
      echo ""
      echo "Answer in <=200 words. Plain prose. Cite which section of your prior YAML the answer refines."
      echo "Do NOT rewrite your YAML."
      echo "Output: write to $STATE/answer-${AGENT}.md"
    } > "$BRIEF"
    "$CLAUDE_BIN" -p < "$BRIEF" > "$STATE/ask-${AGENT}.log" 2>&1 || { echo "ask: dispatch failed — see $STATE/ask-${AGENT}.log" >&2; exit 1; }

    # Append to answers.md
    {
        echo ""
        echo "### [$(date -u +%Y-%m-%dT%H:%M:%SZ)] Ask to $AGENT: $QUESTION"
        [ -f "$STATE/answer-${AGENT}.md" ] && cat "$STATE/answer-${AGENT}.md"
    } >> "$STATE/answers.md"

    local SCOPE; SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"
    local SUMMARY; SUMMARY="asked $AGENT: ${QUESTION:0:60}"
    local RN; RN="$(append_round "$PROJECT" "ask" "$AGENT" "$SUMMARY")"
    render_report "$PROJECT" "$SCOPE" "$RN"
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[ask] round $RN card: $URL"
}

cmd_pushback() {
    local PROJECT="" ON="" TEXT="" DRY_RUN=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --project) PROJECT="$2"; shift 2 ;;
            --on)      ON="$2"; shift 2 ;;
            --text)    TEXT="$2"; shift 2 ;;
            --dry-run) DRY_RUN=1; shift ;;
            *) echo "pushback: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] && [ -n "$ON" ] && [ -n "$TEXT" ] || { echo "pushback: --project --on --text all required" >&2; exit 2; }
    validate_project "$PROJECT"
    ensure_state "$PROJECT"

    # Derive which agent owns this id. Convention: alt* → challenge, oq* → understand,
    # blk*/shp*/qw*/st*/ft* → improver. Disagreement ids prefixed "dis-<agent>-" route by agent.
    local AGENT=""
    case "$ON" in
        alt*)    AGENT="challenge" ;;
        oq*)     AGENT="understand" ;;
        blk*|shp*|qw*|st*|ft*) AGENT="improver" ;;
        dis-understand-*) AGENT="understand" ;;
        dis-challenge-*)  AGENT="challenge" ;;
        dis-improver-*)   AGENT="improver" ;;
        *) echo "pushback: cannot infer agent from id '$ON' (expected alt*/oq*/blk*/shp*/qw*/st*/ft*/dis-<agent>-*)" >&2; exit 2 ;;
    esac

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ROUTING: pushback on id=$ON (owner=$AGENT)"
        echo "[dry-run] single-agent re-dispatch of $AGENT with prior YAML + contested-id highlighted + user text"
        echo "[dry-run] merge re-runs over updated $AGENT.yaml; other 2 peers untouched"
        exit 0
    fi

    local STATE; STATE="$(state_dir "$PROJECT")"
    local PRIOR="$STATE/${AGENT}.yaml"
    [ -f "$PRIOR" ] || { echo "pushback: no prior $AGENT YAML" >&2; exit 1; }

    local BRIEF="$STATE/pushback-${AGENT}.brief.txt"
    {
      echo "Role: $AGENT peer (RECONSIDER — user pushed back on item '$ON')."
      echo "Project: $PROJECT"
      echo ""
      echo "Your prior YAML:"
      echo "-----"
      cat "$PRIOR"
      echo "-----"
      echo ""
      echo "User's pushback on item id '$ON': $TEXT"
      echo ""
      echo "Revise the item (and only related items). Preserve all other content."
      echo "Output: write the full revised YAML to $STATE/${AGENT}.yaml.new"
    } > "$BRIEF"
    "$CLAUDE_BIN" -p < "$BRIEF" > "$STATE/pushback-${AGENT}.log" 2>&1 || { echo "pushback: dispatch failed" >&2; exit 1; }
    if [ -f "$STATE/${AGENT}.yaml.new" ]; then
        mv "$STATE/${AGENT}.yaml" "$STATE/${AGENT}.yaml.prev"
        mv "$STATE/${AGENT}.yaml.new" "$STATE/${AGENT}.yaml"
    fi

    local SCOPE; SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"
    local SUMMARY; SUMMARY="pushback on $ON: ${TEXT:0:60}"
    local RN; RN="$(append_round "$PROJECT" "pushback" "$AGENT" "$SUMMARY")"
    render_report "$PROJECT" "$SCOPE" "$RN"
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[pushback] round $RN card: $URL"
}

cmd_constrain() {
    local PROJECT="" TEXT="" DRY_RUN=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --project) PROJECT="$2"; shift 2 ;;
            --text)    TEXT="$2"; shift 2 ;;
            --dry-run) DRY_RUN=1; shift ;;
            *) echo "constrain: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] && [ -n "$TEXT" ] || { echo "constrain: --project --text required" >&2; exit 2; }
    validate_project "$PROJECT"
    ensure_state "$PROJECT"

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ROUTING: constrain --text=\"$TEXT\""
        echo "[dry-run] all 3 peers (understand,challenge,improver) re-run IN PARALLEL with constraint preamble"
        echo "[dry-run] research output reused as-is (not re-run)"
        echo "[dry-run] merge re-runs over updated YAMLs"
        exit 0
    fi

    local STATE; STATE="$(state_dir "$PROJECT")"
    local PROMPT; PROMPT="$(cat "$STATE/prompt.txt" 2>/dev/null || echo "(prompt missing)")"
    local SCOPE;  SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"

    # Append constraint to accumulated constraints file so multiple constraints stack.
    echo "- [$(date -u +%Y-%m-%dT%H:%M:%SZ)] $TEXT" >> "$STATE/constraints.md"
    local PREAMBLE="ADDITIONAL CONSTRAINTS (user-supplied, accumulated over rounds):"$'\n'"$(cat "$STATE/constraints.md")"

    local TS_SLUG; TS_SLUG="$(date -u +%Y%m%dT%H%M%SZ)"
    local RUN_DIR="/tmp/kickoff-${PROJECT}-r-${TS_SLUG}"
    mkdir -p "$RUN_DIR"
    cp "$STATE/research.md" "$RUN_DIR/research.md" 2>/dev/null || true

    build_understand_brief "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "$PREAMBLE" > "$RUN_DIR/understand.brief.txt"
    build_challenge_brief  "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "$PREAMBLE" > "$RUN_DIR/challenge.brief.txt"
    build_improver_brief   "$PROMPT" "$PROJECT" "$SCOPE" "$RUN_DIR" "$PREAMBLE" > "$RUN_DIR/improver.brief.txt"

    local PIDS=()
    dispatch_one understand "$RUN_DIR/understand.brief.txt" "$RUN_DIR" 0 & PIDS+=($!)
    dispatch_one challenge  "$RUN_DIR/challenge.brief.txt"  "$RUN_DIR" 0 & PIDS+=($!)
    dispatch_one improver   "$RUN_DIR/improver.brief.txt"   "$RUN_DIR" 0 & PIDS+=($!)
    for pid in "${PIDS[@]}"; do wait "$pid" || true; done

    for y in understand.yaml challenge.yaml improver.yaml; do
        [ -f "$RUN_DIR/$y" ] && cp "$RUN_DIR/$y" "$STATE/$y"
    done

    local SUMMARY; SUMMARY="added constraint: ${TEXT:0:60}"
    local RN; RN="$(append_round "$PROJECT" "constrain" "understand,challenge,improver" "$SUMMARY")"
    render_report "$PROJECT" "$SCOPE" "$RN"
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[constrain] round $RN card: $URL"
}

cmd_answer() {
    local PROJECT="" QID="" TEXT="" DRY_RUN=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --project)  PROJECT="$2"; shift 2 ;;
            --question) QID="$2"; shift 2 ;;
            --text)     TEXT="$2"; shift 2 ;;
            --dry-run)  DRY_RUN=1; shift ;;
            *) echo "answer: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] && [ -n "$QID" ] && [ -n "$TEXT" ] || { echo "answer: --project --question --text required" >&2; exit 2; }
    validate_project "$PROJECT"
    ensure_state "$PROJECT"

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ROUTING: answer --question=$QID --text=\"$TEXT\""
        echo "[dry-run] updates Understand's default_if_no_answer for $QID (promotes default → answered)"
        echo "[dry-run] merge re-runs; other 2 peers untouched"
        exit 0
    fi

    local STATE; STATE="$(state_dir "$PROJECT")"
    # Persist answer in answers.yaml index; Understand YAML also patched.
    echo "$QID: $(printf '%s' "$TEXT" | sed 's/"/\\"/g')" >> "$STATE/answered-questions.log"

    # Patch understand.yaml — replace the default_if_no_answer under matching id.
    python3 - "$STATE/understand.yaml" "$QID" "$TEXT" <<'PY'
import sys, re, pathlib
p, qid, text = sys.argv[1], sys.argv[2], sys.argv[3]
src = pathlib.Path(p).read_text() if pathlib.Path(p).exists() else ""
# Find the block:  - id: <qid>\n    question: ...\n    why_it_matters: ...\n    default_if_no_answer: ...
pat = re.compile(r'(-\s+id:\s*' + re.escape(qid) + r'\b[\s\S]*?default_if_no_answer:)\s*.*', re.M)
if pat.search(src):
    new = pat.sub(r'\1 ' + text.replace('\\', '\\\\'), src)
else:
    # No matching id — append an "answered" note at the bottom.
    new = src.rstrip() + f"\n# answered (not matched): {qid} -> {text}\n"
pathlib.Path(p).write_text(new)
PY

    local SCOPE; SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"
    local SUMMARY; SUMMARY="answered $QID: ${TEXT:0:60}"
    local RN; RN="$(append_round "$PROJECT" "answer" "understand" "$SUMMARY")"
    render_report "$PROJECT" "$SCOPE" "$RN"
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[answer] round $RN card: $URL"
}

cmd_refine() {
    local PROJECT=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --project) PROJECT="$2"; shift 2 ;;
            *) echo "refine: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] || { echo "refine: --project required" >&2; exit 2; }
    validate_project "$PROJECT"
    ensure_state "$PROJECT"
    local STATE; STATE="$(state_dir "$PROJECT")"
    local SCOPE; SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"
    local RN; RN="$(append_round "$PROJECT" "refine" "-" "re-render card from current state")"
    render_report "$PROJECT" "$SCOPE" "$RN"
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[refine] round $RN card: $URL"
}

cmd_finalize() {
    local PROJECT="" VIA_SHIM="${VIA_SHIM:-false}"
    while [ $# -gt 0 ]; do
        case "$1" in
            --project)   PROJECT="$2"; shift 2 ;;
            --via-shim)  VIA_SHIM=true; shift ;;
            *) echo "finalize: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] || { echo "finalize: --project required" >&2; exit 2; }
    validate_project "$PROJECT"
    ensure_state "$PROJECT"
    local STATE; STATE="$(state_dir "$PROJECT")"
    local SCOPE; SCOPE="$(cat "$STATE/scope.txt" 2>/dev/null || echo existing-big)"
    local REPORT; REPORT="$(report_path "$PROJECT")"

    touch "$STATE/FINALIZED"
    local SUMMARY="status=finalized"
    [ "$VIA_SHIM" = "true" ] && SUMMARY="status=finalized (via_shim=true — called via deprecated 'accept')"
    local RN; RN="$(append_round "$PROJECT" "finalize" "-" "$SUMMARY")"
    render_report "$PROJECT" "$SCOPE" "$RN"

    # Seed PROJECT_STATE.md + PROJECT_CONTEXT.md if absent (idempotent).
    local PROJ_DIR; PROJ_DIR="$(project_dir "$PROJECT")"
    mkdir -p "$PROJ_DIR"
    if [ ! -f "$PROJ_DIR/PROJECT_STATE.md" ]; then
        {
          echo "# $PROJECT — Project State"
          echo ""
          echo "Seeded by kickoff.sh finalize at $(date -u +%Y-%m-%dT%H:%M:%SZ)."
          echo "Source: $REPORT"
          echo ""
          echo "## Milestones"
          echo "## Open Work"
          echo "## Recent Decisions"
          echo "## Risks"
        } > "$PROJ_DIR/PROJECT_STATE.md"
    fi
    if [ ! -f "$PROJ_DIR/PROJECT_CONTEXT.md" ]; then
        {
          echo "# $PROJECT — Project Context"
          echo ""
          echo "Seeded by kickoff.sh finalize. See KICKOFF_REPORT.md for the finalized spec."
        } > "$PROJ_DIR/PROJECT_CONTEXT.md"
    fi

    # Fire milestone-tier ntfy via accept-card (terminal Final card).
    local URL; URL="$(emit_draft_plan_card "$PROJECT" "$RN")"
    echo "[finalize] status=finalized  report=$REPORT  card=$URL"

    # Builder dispatch — intentionally leaves this as a log marker; orchestrator / main thread
    # reads it and spawns the first builder subagent. We do NOT block on a claude invocation
    # here because finalize should be fast and idempotent.
    echo "[finalize] builder-dispatch marker written to $STATE/BUILDER_READY"
    touch "$STATE/BUILDER_READY"
}

cmd_cancel() {
    local PROJECT=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --project) PROJECT="$2"; shift 2 ;;
            *) echo "cancel: unknown arg '$1'" >&2; exit 2 ;;
        esac
    done
    [ -n "$PROJECT" ] || { echo "cancel: --project required" >&2; exit 2; }
    validate_project "$PROJECT"
    local REPORT; REPORT="$(report_path "$PROJECT")"
    local GRAVE="/opt/site-deploy/graveyard"
    mkdir -p "$GRAVE"
    if [ -f "$REPORT" ]; then
        local TS; TS="$(date -u +%Y%m%dT%H%M%SZ)"
        mv "$REPORT" "$GRAVE/kickoff-${PROJECT}-${TS}.md"
        echo "[cancel] moved report to $GRAVE/kickoff-${PROJECT}-${TS}.md"
    fi
    # Scaffold rollback: safe because kickoff.sh itself does not create shared-infra
    # artefacts (nginx / systemd) — those are created by SKILLS/new-project-checklist.md.
    # We only own the .kickoff-state dir.
    rm -rf "$(state_dir "$PROJECT")"
    echo "[cancel] cleared $(state_dir "$PROJECT")"
}

cmd_accept_shim() {
    # Backward-compat: accept → finalize with via_shim=true log marker.
    VIA_SHIM=true cmd_finalize "$@"
}

# ----------------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------------

if [ "$#" -eq 0 ]; then
    print_usage
    exit 0
fi

case "$1" in
    -h|--help)  print_usage; exit 0 ;;
    ask)        shift; cmd_ask "$@" ;;
    pushback)   shift; cmd_pushback "$@" ;;
    constrain)  shift; cmd_constrain "$@" ;;
    answer)     shift; cmd_answer "$@" ;;
    refine)     shift; cmd_refine "$@" ;;
    finalize)   shift; cmd_finalize "$@" ;;
    cancel)     shift; cmd_cancel "$@" ;;
    accept)     shift; cmd_accept_shim "$@" ;;
    --*)        cmd_initial "$@" ;;
    *)          echo "kickoff.sh: unknown subcommand '$1'" >&2; print_usage >&2; exit 2 ;;
esac
