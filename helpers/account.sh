#!/bin/bash
# Track all third-party accounts / subscriptions the platform uses.
#
# Usage:
#   account.sh add <service> <purpose> <url> <cred-location> [monthly-cost]
#   account.sh list
#   account.sh cancel <service>
#   account.sh show <service>
#
# State file: /var/www/landing/accounts.json (served at /accounts.json)
# Also updates /opt/site-deploy/ACCOUNTS.md (human-readable, versioned in git).
set -e

FILE=/var/www/landing/accounts.json
MD=/opt/site-deploy/ACCOUNTS.md
mkdir -p "$(dirname "$FILE")"
NOW=$(date -Iseconds)
TODAY=$(date +%Y-%m-%d)

if [ ! -s "$FILE" ] || ! jq -e '.accounts' "$FILE" >/dev/null 2>&1; then
    echo '{"updated_at":"'"$NOW"'","accounts":[]}' > "$FILE"
fi

render_md() {
    jq -r '
        "# Accounts & Subscriptions\n\n_Last updated: " + .updated_at + "_\n\n## Active\n\n" +
        (([ .accounts[] | select(.status=="active") ] | if length == 0 then "(none)\n" else
            "| Service | Purpose | URL | Credentials | Monthly Cost | Added |\n" +
            "|---|---|---|---|---|---|\n" +
            (map("| \(.service) | \(.purpose) | \(.url) | `\(.cred_location)` | \(.monthly_cost // "—") | \(.added) |") | join("\n"))
          end)) +
        "\n\n## Cancelled\n\n" +
        (([ .accounts[] | select(.status=="cancelled") ] | if length == 0 then "(none)\n" else
            "| Service | Purpose | Cancelled |\n|---|---|---|\n" +
            (map("| \(.service) | \(.purpose) | \(.cancelled_at // "?") |") | join("\n"))
          end))
    ' "$FILE" > "$MD"
}

case "${1:-}" in
    add)
        SERVICE="${2:?service name required}"
        PURPOSE="${3:?purpose required}"
        URL="${4:?url required}"
        CRED="${5:?credential location required (e.g. 'ANTHROPIC_API_KEY in /opt/timeshare/.env')}"
        COST="${6:-}"
        jq --arg s "$SERVICE" --arg p "$PURPOSE" --arg u "$URL" --arg c "$CRED" \
           --arg cost "$COST" --arg added "$TODAY" --arg ts "$NOW" \
           '.updated_at=$ts |
            .accounts = (.accounts | map(select(.service != $s))) + [
              {"service":$s, "purpose":$p, "url":$u, "cred_location":$c,
               "monthly_cost":$cost, "added":$added, "status":"active"}
            ]' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        render_md
        /usr/local/bin/notify.sh \
            "New account tracked: $SERVICE ($PURPOSE)" "Account registry" default \
            "https://casinv.dev/accounts.html" 2>/dev/null || true
        echo "added: $SERVICE"
        ;;
    list)
        jq -r '.accounts[] |
               "\(.status | ascii_upcase) [\(.service)] \(.purpose)  —  \(.url)\n  creds: \(.cred_location)\n  cost: \(.monthly_cost // "—")  added: \(.added)\n"' \
            "$FILE"
        ;;
    show)
        SERVICE="${2:?service name required}"
        jq -r --arg s "$SERVICE" '.accounts[] | select(.service==$s)' "$FILE"
        ;;
    cancel)
        SERVICE="${2:?service name required}"
        jq --arg s "$SERVICE" --arg ts "$NOW" --arg d "$TODAY" \
           '.updated_at=$ts |
            .accounts = (.accounts | map(if .service==$s then .status="cancelled" | .cancelled_at=$d else . end))' \
           "$FILE" > "$FILE.tmp" && mv "$FILE.tmp" "$FILE"
        render_md
        echo "cancelled: $SERVICE"
        ;;
    *)
        echo "Usage:" >&2
        echo "  $0 add <service> <purpose> <url> <cred-location> [monthly-cost]" >&2
        echo "  $0 list" >&2
        echo "  $0 show <service>" >&2
        echo "  $0 cancel <service>" >&2
        exit 1
        ;;
esac
