#!/bin/bash
# Update /var/www/landing/tasks.json per-project.
# The projects.html dashboard reads this file.
#
# Usage:
#   task-status.sh set   <project> <task_name> <stage> [detail]
#   task-status.sh done  <project> <task_name> <summary> [preview_url]
#   task-status.sh clear <project>
set -e

FILE=/var/www/landing/tasks.json
mkdir -p /var/www/landing
NOW=$(date -Iseconds)

# Initialize file if missing or not multi-project shaped
if [ ! -s "$FILE" ] || ! jq -e '.projects' "$FILE" >/dev/null 2>&1; then
    echo '{"last_updated":"'"$NOW"'","projects":{}}' > "$FILE"
fi

CMD="${1:-}"
PROJECT="${2:-}"

case "$CMD" in
    set)
        NAME="${3:-unnamed}"
        STAGE="${4:-building}"
        DETAIL="${5:-}"
        jq --arg p "$PROJECT" --arg u "$NOW" --arg n "$NAME" --arg s "$STAGE" --arg d "$DETAIL" \
           '.last_updated=$u | .projects[$p]={current_task:{name:$n, stage:$s, detail:$d, started:$u}, last_done:(.projects[$p].last_done // null)}' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        ;;
    done)
        NAME="${3:-unnamed}"
        SUMMARY="${4:-}"
        URL="${5:-}"
        jq --arg p "$PROJECT" --arg u "$NOW" --arg n "$NAME" --arg s "$SUMMARY" --arg url "$URL" \
           '.last_updated=$u | .projects[$p]={current_task:null, last_done:{name:$n, summary:$s, preview_url:$url, completed_at:$u}}' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        ;;
    clear)
        jq --arg p "$PROJECT" --arg u "$NOW" '.last_updated=$u | del(.projects[$p])' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        ;;
    *)
        echo "Usage:" >&2
        echo "  $0 set   <project> <task_name> <stage> [detail]" >&2
        echo "  $0 done  <project> <task_name> <summary> [preview_url]" >&2
        echo "  $0 clear <project>" >&2
        exit 1
        ;;
esac
