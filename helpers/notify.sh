#!/bin/bash
# Send an iPhone push notification via ntfy.sh.
# Usage: notify.sh "Message" [title] [priority] [click-url]
#   priority: min | low | default | high | urgent
set -e

TOPIC_FILE=/etc/ntfy-topic
TOPIC=$(cat "$TOPIC_FILE" 2>/dev/null || true)
if [ -z "$TOPIC" ]; then
    echo "No ntfy topic configured ($TOPIC_FILE missing or empty)" >&2
    exit 1
fi

MSG="${1:?message required}"
TITLE="${2:-Claude Code}"
PRIO="${3:-default}"
CLICK="${4:-}"

HEADERS=(-H "Title: $TITLE" -H "Priority: $PRIO")
[ -n "$CLICK" ] && HEADERS+=(-H "Click: $CLICK")

curl -sf -X POST "https://ntfy.sh/$TOPIC" "${HEADERS[@]}" -d "$MSG" > /dev/null
