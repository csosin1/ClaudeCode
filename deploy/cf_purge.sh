#!/bin/bash
# Cloudflare cache purge for the Carvana ABS dashboard.
# Called from the promote step so end-users see fresh content immediately
# after a preview→live promotion (no need for ?v=N cache-bust hacks or 4h
# TTL waits).
#
# Required (sourced from /opt/abs-dashboard/.env or the environment):
#   CF_API_TOKEN=<scoped token with Zone:Cache Purge permission>
#   CF_ZONE_ID=<casinv.dev zone id>
#
# Without those, this script no-ops with a warning so the promote still
# succeeds.

set -u
ENV_FILE=/opt/abs-dashboard/.env
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

if [ -z "${CF_API_TOKEN:-}" ] || [ -z "${CF_ZONE_ID:-}" ]; then
    echo "$(date -u): cf_purge skipped — set CF_API_TOKEN and CF_ZONE_ID in $ENV_FILE to enable"
    exit 0
fi

# Purge only this project's URL prefix; leaves other casinv.dev paths cached.
RESPONSE=$(curl -sS -X POST \
    "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data '{"prefixes":["casinv.dev/CarvanaLoanDashBoard/"]}')

if echo "$RESPONSE" | grep -q '"success":true'; then
    echo "$(date -u): cf_purge OK"
else
    echo "$(date -u): cf_purge FAILED: $RESPONSE"
    exit 1
fi
