#!/bin/bash
# Send an iPhone push notification via ntfy.sh.
#
# Preferred (tiered) form:
#   notify.sh "Message" "Title" --tier critical|milestone|heartbeat [--click <url>]
#
# Legacy positional form (still supported for back-compat):
#   notify.sh "Message" [title] [priority] [click-url]
#     priority: min | low | default | high | urgent
#
# The three tiers map to ntfy priority as follows (see SKILLS/notification-tiers.md):
#   critical  → priority 5 (vibrate — blocker or irreversible-action pause)
#   milestone → priority 3 (default push — deliverable ready for Accept)
#   heartbeat → priority 1 (silent — long-running work pulse)
#
# --tier always wins over a positional priority if both are supplied.
set -e

TOPIC_FILE=/etc/ntfy-topic
TOPIC=$(cat "$TOPIC_FILE" 2>/dev/null || true)
if [ -z "$TOPIC" ]; then
    echo "No ntfy topic configured ($TOPIC_FILE missing or empty)" >&2
    exit 1
fi

# --- Parse args --------------------------------------------------------------
# Pull --tier and --click out of the arg list, leave positionals in "$@".
TIER=""
CLICK_FLAG=""
POSITIONAL=()
while [ $# -gt 0 ]; do
    case "$1" in
        --tier)
            TIER="${2:-}"
            shift 2
            ;;
        --tier=*)
            TIER="${1#--tier=}"
            shift
            ;;
        --click)
            CLICK_FLAG="${2:-}"
            shift 2
            ;;
        --click=*)
            CLICK_FLAG="${1#--click=}"
            shift
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done
set -- "${POSITIONAL[@]}"

MSG="${1:?message required}"
TITLE="${2:-Claude Code}"
PRIO_POS="${3:-default}"
CLICK_POS="${4:-}"

# --- Tier → priority mapping -------------------------------------------------
case "$TIER" in
    critical)  PRIO="5" ;;
    milestone) PRIO="3" ;;
    heartbeat) PRIO="1" ;;
    "")        PRIO="$PRIO_POS" ;;
    *)
        echo "notify.sh: unknown --tier '$TIER' (expected critical|milestone|heartbeat)" >&2
        exit 2
        ;;
esac

CLICK="${CLICK_FLAG:-$CLICK_POS}"

HEADERS=(-H "Title: $TITLE" -H "Priority: $PRIO")
[ -n "$CLICK" ] && HEADERS+=(-H "Click: $CLICK")

# Tag tier for retrospective filtering if used
[ -n "$TIER" ] && HEADERS+=(-H "Tags: tier-$TIER")

curl -sf -X POST "https://ntfy.sh/$TOPIC" "${HEADERS[@]}" -d "$MSG" > /dev/null
