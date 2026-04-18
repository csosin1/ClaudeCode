#!/bin/bash
# kickoff-retro.sh — content-triggered spec-vs-reality delta capture.
#
# Fires on ship events (QA-green + user-accepts-live) via post-deploy-qa-hook or the
# project's end-task.sh. NEVER calendar-triggered.
#
# Reads KICKOFF_REPORT.md § Synthesized Spec; walks the project's current state
# (git log since kickoff, diff kickoff-commit..HEAD, current PROJECT_STATE, LESSONS
# entries since kickoff); emits spec-vs-reality deltas; appends to
# SKILLS/kickoff-retros.md with a categorized root-cause tag.
#
# Silent log — NO ntfy. Future-session agents read kickoff-retros.md when writing
# new kickoffs (consulted by kickoff.sh + the Understand/Challenge/Improver peers).
#
# Usage:
#   kickoff-retro.sh --project <name> [--since <ISO-date>] [--dry-run]
#
# Flags:
#   --project  project slug (required)
#   --since    override auto-detected kickoff date (optional; default: parse from KICKOFF_REPORT.md)
#   --dry-run  print the delta that would be appended, without writing
#
# Exit codes:
#   0 — delta appended (or dry-run printed)
#   1 — usage / missing KICKOFF_REPORT.md
#   2 — project dir missing or unreadable

set -eE -o pipefail
trap 'echo "[kickoff-retro] ERROR at line $LINENO (exit=$?)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT=""
SINCE=""
DRY_RUN=0

print_usage() {
    sed -n '1,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --project)   PROJECT="$2"; shift 2 ;;
        --since)     SINCE="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=1; shift ;;
        -h|--help)   print_usage; exit 0 ;;
        *) echo "kickoff-retro.sh: unknown arg '$1'" >&2; print_usage >&2; exit 1 ;;
    esac
done

[ -n "$PROJECT" ] || { echo "kickoff-retro.sh: --project required" >&2; exit 1; }

PROJECT_DIR="/opt/${PROJECT}"
REPORT_PATH="${PROJECT_DIR}/KICKOFF_REPORT.md"
RETROS_PATH="${REPO_ROOT}/SKILLS/kickoff-retros.md"

[ -d "$PROJECT_DIR" ] || { echo "kickoff-retro.sh: $PROJECT_DIR not found" >&2; exit 2; }
[ -f "$REPORT_PATH" ] || { echo "kickoff-retro.sh: $REPORT_PATH not found — no kickoff to retro" >&2; exit 1; }
[ -f "$RETROS_PATH" ] || { echo "kickoff-retro.sh: $RETROS_PATH not found in shared repo" >&2; exit 1; }

# --- Auto-detect kickoff date from the report if not supplied ---------------
if [ -z "$SINCE" ]; then
    SINCE="$(grep -m1 -oE '^# Kickoff Report — .+ — [0-9]{4}-[0-9]{2}-[0-9]{2}' "$REPORT_PATH" \
              | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T?[0-9:]*Z?' | head -1 || true)"
    if [ -z "$SINCE" ]; then
        SINCE="$(grep -m1 -oE '^last_verified:[[:space:]]*[0-9-]+' "$REPORT_PATH" | awk '{print $2}' || true)"
    fi
    [ -n "$SINCE" ] || { echo "kickoff-retro.sh: could not auto-detect kickoff date; pass --since <ISO>" >&2; exit 1; }
fi

TS_TODAY="$(date -u +%Y-%m-%d)"

# --- Gather deltas (code, not LLM — deterministic) --------------------------
DELTA_FILE="$(mktemp)"
trap 'rm -f "$DELTA_FILE"' EXIT

{
    echo "## ${TS_TODAY} — ${PROJECT} — ship retro"
    echo ""
    echo "- **Spec date:** ${SINCE}"
    echo "- **Kickoff report:** ${REPORT_PATH}"
    echo ""

    # Commits in the project-shared repo since kickoff (scoped to /opt/<project>/ if it's git-tracked here).
    if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
        echo "- **Shared-repo commits touching /opt/${PROJECT}/ since ${SINCE}:**"
        git -C "$REPO_ROOT" log --since="${SINCE}" --oneline -- "/opt/${PROJECT}/" 2>/dev/null \
            | sed 's/^/  - /' | head -50 || echo "  (none or repo scope does not include project)"
    fi

    # Commits in the project's own git repo (if it has one).
    if [ -d "${PROJECT_DIR}/.git" ]; then
        echo ""
        echo "- **Project-repo commits since ${SINCE}:**"
        git -C "$PROJECT_DIR" log --since="${SINCE}" --oneline 2>/dev/null \
            | sed 's/^/  - /' | head -50 || echo "  (none)"
    fi

    # PROJECT_STATE.md current head (first ~20 lines).
    if [ -f "${PROJECT_DIR}/PROJECT_STATE.md" ]; then
        echo ""
        echo "- **PROJECT_STATE.md head (current state):**"
        head -20 "${PROJECT_DIR}/PROJECT_STATE.md" | sed 's/^/    /'
    fi

    # LESSONS entries since kickoff (shared LESSONS.md only — per-project LESSONS aren't a convention).
    if [ -f "${REPO_ROOT}/LESSONS.md" ]; then
        echo ""
        echo "- **LESSONS entries since ${SINCE} (shared):**"
        awk -v since="${SINCE}" '
            /^## [0-9]{4}-[0-9]{2}-[0-9]{2}/ {
                # Extract date token
                match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}/)
                d = substr($0, RSTART, 10)
                if (d >= substr(since,1,10)) print "  - " $0
            }
        ' "${REPO_ROOT}/LESSONS.md" | head -20 || echo "  (none)"
    fi

    echo ""
    echo "- **Root-cause tag:** (categorize manually on next touch — research-miss / user-mind-change / spec-ambiguity / platform-drift)"
    echo ""
} > "$DELTA_FILE"

# --- Emit / append ----------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] would prepend the following entry to $RETROS_PATH:"
    echo "--------"
    cat "$DELTA_FILE"
    echo "--------"
    exit 0
fi

# Prepend newest-first: insert the delta after the "## Entries (newest first; ...)" header line.
python3 - "$RETROS_PATH" "$DELTA_FILE" <<'PY'
import pathlib, sys
retros_path = pathlib.Path(sys.argv[1])
delta = pathlib.Path(sys.argv[2]).read_text()
text = retros_path.read_text()
marker = "## Entries (newest first; `kickoff-retro.sh` prepends)"
if marker in text:
    head, tail = text.split(marker, 1)
    new = head + marker + "\n\n" + delta + tail.lstrip("\n")
else:
    # Fallback: append
    new = text.rstrip() + "\n\n" + delta
retros_path.write_text(new)
print(f"prepended delta to {retros_path}")
PY

echo "[kickoff-retro] appended retro for project=${PROJECT} since=${SINCE} (silent; no ntfy)."
exit 0
