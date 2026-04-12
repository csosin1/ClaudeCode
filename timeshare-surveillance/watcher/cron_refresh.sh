#!/bin/bash
# Weekly fallback refresh — belt-and-braces in case the watcher missed a filing.
# Pulls the most recent filings for every ticker, re-merges, re-evaluates flags,
# and sends a weekly-digest email even if nothing changed.
#
# Intended to run via cron: 0 6 * * 0 /opt/timeshare-surveillance-live/watcher/cron_refresh.sh
set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

VENV_PY="$PROJECT_DIR/venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    VENV_PY="$(command -v python3)"
fi

# shellcheck disable=SC1091
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    . "$PROJECT_DIR/.env"
    set +a
fi

LOG_DIR=/var/log/timeshare-surveillance
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/cron_refresh.log"

echo "$(date -Iseconds) cron_refresh starting" >> "$LOG"

"$VENV_PY" pipeline/fetch_and_parse.py --all >> "$LOG" 2>&1 || echo "$(date -Iseconds) fetch_and_parse rc=$?" >> "$LOG"
"$VENV_PY" pipeline/merge.py >> "$LOG" 2>&1 || echo "$(date -Iseconds) merge rc=$?" >> "$LOG"

# Always send weekly digest
set +e
DIFF="$("$VENV_PY" pipeline/red_flag_diff.py --force-email 2>> "$LOG")"
echo "$DIFF" | "$VENV_PY" alerts/email_alert.py --weekly >> "$LOG" 2>&1
EMAIL_RC=$?
set -e
echo "$(date -Iseconds) cron_refresh done (email rc=$EMAIL_RC)" >> "$LOG"
