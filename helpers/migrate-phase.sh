#!/bin/bash
# Track multi-droplet migration phase transitions.
# Writes a timeline to /var/www/landing/migration-status.json and fires an ntfy push.
# Consumed by /var/www/landing/migration.html.
#
# Usage:
#   migrate-phase.sh start <phase> "<description>"
#   migrate-phase.sh done  <phase> "<summary>"
#   migrate-phase.sh fail  <phase> "<reason>"
set -e

FILE=/var/www/landing/migration-status.json
CLICK_URL="https://casinv.dev/migration.html"
NOW=$(date -Iseconds)

mkdir -p /var/www/landing
if [ ! -s "$FILE" ] || ! jq -e '.phases' "$FILE" >/dev/null 2>&1; then
    echo '{"last_updated":"'"$NOW"'","phases":[]}' > "$FILE"
fi

CMD="${1:-}"
PHASE="${2:-}"
MSG="${3:-}"

if [ -z "$CMD" ] || [ -z "$PHASE" ]; then
    echo "Usage:" >&2
    echo "  $0 start <phase> \"<description>\"" >&2
    echo "  $0 done  <phase> \"<summary>\"" >&2
    echo "  $0 fail  <phase> \"<reason>\"" >&2
    exit 1
fi

append_event() {
    # $1=status $2=message
    local status="$1"
    local note="$2"
    local ts_field
    if [ "$status" = "in_progress" ]; then
        ts_field='start_time:$t'
    else
        ts_field='end_time:$t'
    fi
    jq --arg u "$NOW" --arg t "$NOW" --arg p "$PHASE" --arg s "$status" --arg n "$note" \
       '.last_updated=$u
        | .phases += [{phase:$p, status:$s, '"$ts_field"', notes:$n, recorded_at:$u}]' \
       "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
}

case "$CMD" in
    start)
        append_event "in_progress" "$MSG"
        /usr/local/bin/notify.sh \
            "${MSG:-$PHASE migration begins.}" \
            "Migration: $PHASE starting" \
            default \
            "$CLICK_URL" || true
        ;;
    done)
        append_event "complete" "$MSG"
        /usr/local/bin/notify.sh \
            "${MSG:-$PHASE complete.}" \
            "Migration: $PHASE complete" \
            high \
            "$CLICK_URL" || true
        ;;
    fail)
        append_event "failed" "$MSG"
        /usr/local/bin/notify.sh \
            "${MSG:-$PHASE failed.} See $CLICK_URL for details." \
            "Migration: $PHASE FAILED" \
            urgent \
            "$CLICK_URL" || true
        ;;
    *)
        echo "Unknown subcommand: $CMD" >&2
        exit 1
        ;;
esac

echo "[migrate-phase] $CMD $PHASE logged at $NOW"
