#!/bin/bash
# Track pending user actions (sign-ups, manual console work, credential pasting, etc.)
# so asks don't get buried in chat context and assumed-done.
#
# Usage:
#   user-action.sh add <project> "<title>" "<steps>" "<verify-by>"
#   user-action.sh list
#   user-action.sh done <id>      # agent must verify first; marks complete
#   user-action.sh cancel <id>    # no longer needed
#   user-action.sh remind         # prints pending list for the chat
#
# State file: /var/www/landing/pending-actions.json (served at /pending-actions.json)
# Every add/done fires a notify.sh so the user sees it on their phone.
set -e

FILE=/var/www/landing/pending-actions.json
mkdir -p "$(dirname "$FILE")"
NOW=$(date -Iseconds)
NOW_EPOCH=$(date +%s)

if [ ! -s "$FILE" ] || ! jq -e '.actions' "$FILE" >/dev/null 2>&1; then
    echo '{"updated_at":"'"$NOW"'","actions":[]}' > "$FILE"
fi

CMD="${1:-}"

case "$CMD" in
    add)
        PROJECT="${2:?project required}"
        TITLE="${3:?title required}"
        STEPS="${4:?steps required}"
        VERIFY="${5:?verify-by required}"
        ID="ua-$(printf '%04x' $((RANDOM * 32768 + RANDOM)))"
        jq --arg id "$ID" --arg p "$PROJECT" --arg t "$TITLE" --arg s "$STEPS" \
           --arg v "$VERIFY" --arg u "$NOW" \
           '.updated_at=$u |
            .actions += [{"id":$id, "project":$p, "title":$t, "steps":$s,
                          "verify_by":$v, "status":"pending", "created_at":$u}]' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        /usr/local/bin/notify.sh \
            "[$PROJECT] $TITLE" "Action needed from you" default \
            "https://casinv.dev/todo.html" 2>/dev/null || true
        echo "$ID"
        ;;
    list)
        jq -r '.actions[] | select(.status=="pending") |
               "[\(.id)] \(.project) — \(.title)\n  Steps: \(.steps)\n  Verify: \(.verify_by)\n  Added: \(.created_at)\n"' \
            "$FILE"
        ;;
    remind)
        # Terse form for the chat
        N=$(jq '.actions | map(select(.status=="pending")) | length' "$FILE")
        echo "$N pending user action(s):"
        jq -r '.actions[] | select(.status=="pending") | "  [\(.id)] \(.project): \(.title)"' "$FILE"
        ;;
    done)
        ID="${2:?action id required}"
        jq --arg id "$ID" --arg u "$NOW" \
           '.updated_at=$u |
            .actions = (.actions | map(if .id==$id then .status="done" | .completed_at=$u else . end))' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        TITLE=$(jq -r --arg id "$ID" '.actions[] | select(.id==$id) | .title' "$FILE")
        /usr/local/bin/notify.sh \
            "Verified: $TITLE" "Action complete" default \
            "https://casinv.dev/todo.html" 2>/dev/null || true
        echo "marked done: $ID"
        ;;
    cancel)
        ID="${2:?action id required}"
        jq --arg id "$ID" --arg u "$NOW" \
           '.updated_at=$u |
            .actions = (.actions | map(if .id==$id then .status="cancelled" | .cancelled_at=$u else . end))' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        echo "cancelled: $ID"
        ;;
    prune)
        # Remove entries that are done/cancelled > 7 days old
        jq --argjson cutoff $((NOW_EPOCH - 7*86400)) \
           '.actions = (.actions | map(
              if (.status=="done" or .status=="cancelled") and
                 ((.completed_at // .cancelled_at // "1970-01-01") | fromdateiso8601) < $cutoff
              then empty else . end))' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        ;;
    *)
        echo "Usage:" >&2
        echo "  $0 add <project> \"<title>\" \"<steps>\" \"<verify-by>\"" >&2
        echo "  $0 list                    # full details" >&2
        echo "  $0 remind                  # terse, for chats" >&2
        echo "  $0 done <id>               # mark verified complete" >&2
        echo "  $0 cancel <id>             # no longer needed" >&2
        echo "  $0 prune                   # drop entries >7 days old" >&2
        exit 1
        ;;
esac
