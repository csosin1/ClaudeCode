#!/bin/bash
# post-deploy-qa-hook.sh — run a project's @post-deploy-tagged tests against its
# live URL immediately after auto-deploy regenerates output. Closes the gap where
# a mid-rebuild stale-cache regen ships a bug that PR-time QA already passed.
#
# Originating incident: 2026-04-17 Hazard-by-LTV heatmap shipped live on
# abs-dashboard because auto-deploy's regen bypassed qa.yml (which only runs
# against preview on PRs). Post-deploy hook closes Gap 3 from that design pass.
#
# Usage:
#   post-deploy-qa-hook.sh <project> <live_url> [--freeze-on-fail]
#   post-deploy-qa-hook.sh --project <name> --dry-run
#
# --dry-run parses /etc/post-deploy-qa.conf and prints the resolved plan
# (test command template, timeout, freeze-on-fail) without executing. Used
# by operators + pre-commit gates to validate config changes. No LIVE_URL
# is required for --dry-run; {LIVE_URL} placeholders are shown verbatim.
#
# Reads /etc/post-deploy-qa.conf for the per-project test command template.
# Config format (TAB-separated):
#   <project>\t<cmd_template_with_{LIVE_URL}>\t<timeout_sec>\t[--freeze-on-fail]
#
# On pass: append to /var/log/post-deploy-qa.log and exit 0.
# On fail:
#   - append stderr + exit code to /var/log/post-deploy-qa.log
#   - fire notify.sh urgent (project, URL, failure summary)
#   - if --freeze-on-fail set (CLI flag OR conf column 4): write
#     /var/run/auto-deploy-frozen-<project> sentinel; auto-deploy skips
#     the project's regen until the sentinel is removed manually.
#   - exit 1
#
# Single-flighting: flock on /var/run/post-deploy-qa-<project>.lock so concurrent
# regens do not pile up competing test runs.

set -eE -o pipefail

# Recursion guard for the ERR trap; fire once, never re-enter.
_QA_FAIL_FIRED=0
on_hook_fail() {
    local rc="$1" line="$2"
    [ "$_QA_FAIL_FIRED" = "1" ] && exit "$rc"
    _QA_FAIL_FIRED=1
    echo "$(date -Iseconds) hook-internal-error project=${PROJECT:-?} line=$line rc=$rc" >> "$LOG"
    # Hook internals failing is distinct from tests failing — notify but do
    # not freeze. A broken hook must not pile up freezes.
    if [ -x /usr/local/bin/notify.sh ]; then
        /usr/local/bin/notify.sh \
            "post-deploy-qa-hook internal error for ${PROJECT:-?} (rc=$rc line=$line). See $LOG." \
            "post-deploy QA hook broken" \
            urgent \
            "" 2>/dev/null || true
    fi
    exit "$rc"
}
trap 'on_hook_fail $? $LINENO' ERR

# --- Argument parsing -------------------------------------------------------
# Two supported calling conventions:
#   1. Positional (auto_deploy_general.sh, historical callers):
#        post-deploy-qa-hook.sh <project> <live_url> [--freeze-on-fail]
#   2. Long-flag (operators, dry-run validation):
#        post-deploy-qa-hook.sh --project <name> [--dry-run] [--freeze-on-fail]
# Dry-run mode skips execution and prints the resolved plan; LIVE_URL optional.
PROJECT=""
LIVE_URL=""
CLI_FREEZE=""
DRY_RUN=0
POSITIONAL=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --project)
            PROJECT="${2:?--project requires a value}"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --freeze-on-fail)
            CLI_FREEZE="--freeze-on-fail"
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "usage: post-deploy-qa-hook.sh <project> <live_url> [--freeze-on-fail]" >&2
            echo "   or: post-deploy-qa-hook.sh --project <name> [--dry-run] [--freeze-on-fail]" >&2
            exit 2
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done
# Fill positional slots if long-flag didn't already set them.
if [ -z "$PROJECT" ] && [ "${#POSITIONAL[@]}" -ge 1 ]; then
    PROJECT="${POSITIONAL[0]}"
fi
if [ -z "$LIVE_URL" ] && [ "${#POSITIONAL[@]}" -ge 2 ]; then
    LIVE_URL="${POSITIONAL[1]}"
fi
if [ -z "$CLI_FREEZE" ] && [ "${#POSITIONAL[@]}" -ge 3 ]; then
    CLI_FREEZE="${POSITIONAL[2]}"
fi

if [ -z "$PROJECT" ]; then
    echo "usage: post-deploy-qa-hook.sh <project> <live_url> [--freeze-on-fail]" >&2
    echo "   or: post-deploy-qa-hook.sh --project <name> [--dry-run] [--freeze-on-fail]" >&2
    exit 2
fi
# LIVE_URL is only required outside dry-run.
if [ -z "$LIVE_URL" ] && [ "$DRY_RUN" != "1" ]; then
    echo "post-deploy-qa-hook: missing <live_url> (required unless --dry-run)" >&2
    exit 2
fi

CONF=/etc/post-deploy-qa.conf
LOG=/var/log/post-deploy-qa.log
LOCK=/var/run/post-deploy-qa-${PROJECT}.lock
FREEZE_SENTINEL=/var/run/auto-deploy-frozen-${PROJECT}
DEFAULT_TIMEOUT=300

mkdir -p "$(dirname "$LOG")" "$(dirname "$LOCK")" 2>/dev/null || true

# Project name sanity — used in filenames + greps.
case "$PROJECT" in
    *[^a-zA-Z0-9_-]*)
        echo "$(date -Iseconds) $PROJECT invalid-project-name" >> "$LOG"
        exit 2
        ;;
esac

# Config file presence. Absence is benign: projects opt in by adding an entry.
if [ ! -f "$CONF" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "plan: project=$PROJECT conf=$CONF missing; would skip (no-conf-file)"
        exit 0
    fi
    echo "$(date -Iseconds) $PROJECT skip no-conf-file" >> "$LOG"
    exit 0
fi

# Look up the project's row. Lines may be comments (#) or blank. TAB-separated.
# awk is more robust than grep for TSV parsing + column extraction.
ROW=$(awk -F'\t' -v p="$PROJECT" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    $1 == p { print; exit }
' "$CONF")

if [ -z "$ROW" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "plan: project=$PROJECT conf=$CONF has no row for this project; would skip (no-conf-entry)"
        exit 0
    fi
    echo "$(date -Iseconds) $PROJECT skip no-conf-entry" >> "$LOG"
    exit 0
fi

CMD_TEMPLATE=$(printf '%s' "$ROW" | awk -F'\t' '{print $2}')
CONF_TIMEOUT=$(printf '%s' "$ROW"  | awk -F'\t' '{print $3}')
CONF_OPTIONS=$(printf '%s' "$ROW"  | awk -F'\t' '{print $4}')

TIMEOUT="${CONF_TIMEOUT:-$DEFAULT_TIMEOUT}"
case "$TIMEOUT" in
    ''|*[!0-9]*) TIMEOUT=$DEFAULT_TIMEOUT ;;
esac

# Freeze-on-fail: either CLI flag or conf column 4.
FREEZE_ON_FAIL=0
[ "$CLI_FREEZE" = "--freeze-on-fail" ] && FREEZE_ON_FAIL=1
[ "$CONF_OPTIONS" = "--freeze-on-fail" ] && FREEZE_ON_FAIL=1

if [ -z "$CMD_TEMPLATE" ]; then
    echo "$(date -Iseconds) $PROJECT skip empty-cmd-template" >> "$LOG"
    exit 0
fi

# Substitute {LIVE_URL} placeholder. Use bash parameter expansion (no shell
# interpretation of the URL beyond literal substitution).
CMD="${CMD_TEMPLATE//\{LIVE_URL\}/$LIVE_URL}"

# Dry-run: emit the resolved plan and exit 0 without executing. No lock, no
# log file writes, no ntfy, no freeze sentinel. Used by operators and the
# pre-commit gate to validate config changes.
if [ "$DRY_RUN" = "1" ]; then
    if [ -n "$LIVE_URL" ]; then
        RESOLVED_CMD_DISPLAY="$CMD"
    else
        RESOLVED_CMD_DISPLAY="(LIVE_URL not provided — template shown verbatim)"
    fi
    cat <<EOF
plan for project: $PROJECT
  conf file:       $CONF
  cmd template:    $CMD_TEMPLATE
  resolved cmd:    $RESOLVED_CMD_DISPLAY
  live url:        ${LIVE_URL:-<not provided>}
  timeout:         ${TIMEOUT}s
  freeze on fail:  $([ "$FREEZE_ON_FAIL" = "1" ] && echo "YES (sentinel: $FREEZE_SENTINEL)" || echo "no (notify-only)")
  log file:        $LOG
  lock file:       $LOCK
EOF
    exit 0
fi

# Single-flight. If another run holds the lock, we skip rather than queue —
# the next regen will re-trigger us anyway. A lock file that we just created
# is fine; flock's exclusive mode serialises regardless.
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date -Iseconds) $PROJECT skip lock-held" >> "$LOG"
    exit 0
fi

# Pre-run log line so operators can see attempts even if the test hangs.
echo "$(date -Iseconds) $PROJECT start url=$LIVE_URL timeout=${TIMEOUT}s freeze=$FREEZE_ON_FAIL" >> "$LOG"

# Run the test command. `timeout` with explicit signals + kill-after gives
# hung Playwright a chance to clean up before we nuke it.
TEST_OUT=$(mktemp)
# Around the test run itself: a non-zero exit is an EXPECTED outcome path
# (test failed), not a hook-internal error. Bash's ERR trap fires on any
# non-zero command regardless of `set -e` state, so we must clear the trap
# (not just toggle -e) to prevent the failure-path from being misrouted to
# on_hook_fail. Re-install the trap after capturing the exit code.
trap - ERR
set +e
set +o pipefail
timeout --signal=TERM --kill-after=10s "$TIMEOUT" bash -c "$CMD" > "$TEST_OUT" 2>&1
RC=$?
set -eE
set -o pipefail
trap 'on_hook_fail $? $LINENO' ERR

if [ "$RC" -eq 0 ]; then
    echo "$(date -Iseconds) $PROJECT pass url=$LIVE_URL" >> "$LOG"
    rm -f "$TEST_OUT"
    exit 0
fi

# --- Failure path ---
# Preserve verbatim test output + exit code in the log.
{
    echo "$(date -Iseconds) $PROJECT FAIL url=$LIVE_URL rc=$RC (timeout=${TIMEOUT}s)"
    echo "--- test output (verbatim) ---"
    cat "$TEST_OUT"
    echo "--- end test output ---"
} >> "$LOG"

# Short summary for the notification body — last few non-empty lines of output.
# Disable -e/pipefail around this: `grep -v` returns rc=1 on empty input (no
# matches), which with pipefail would fire the ERR trap on a failing test that
# happened to produce no output. We're doing best-effort string shaping here.
set +eE
set +o pipefail
SUMMARY=$(grep -v '^[[:space:]]*$' "$TEST_OUT" 2>/dev/null | tail -5 | tr '\n' ' ' | cut -c1-400)
set -eE
set -o pipefail
[ -z "$SUMMARY" ] && SUMMARY="(no output captured)"

if [ -x /usr/local/bin/notify.sh ]; then
    /usr/local/bin/notify.sh \
        "Post-deploy QA FAILED for $PROJECT at $LIVE_URL (rc=$RC). Last: $SUMMARY" \
        "post-deploy QA fail: $PROJECT" \
        urgent \
        "$LIVE_URL" 2>/dev/null || true
fi

if [ "$FREEZE_ON_FAIL" = "1" ]; then
    {
        echo "project=$PROJECT"
        echo "live_url=$LIVE_URL"
        echo "frozen_at=$(date -Iseconds)"
        echo "reason=post-deploy QA failed (rc=$RC)"
        echo "clear_with=rm $FREEZE_SENTINEL"
    } > "$FREEZE_SENTINEL"
    echo "$(date -Iseconds) $PROJECT FROZEN sentinel=$FREEZE_SENTINEL" >> "$LOG"
fi

rm -f "$TEST_OUT"
exit 1
