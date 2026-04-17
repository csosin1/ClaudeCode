#!/bin/bash
# refresh-docs-ip-allowlist.sh — stub for when Anthropic publishes an authoritative IP range list.
#
# As of 2026-04-17, docs.anthropic.com does not publish an ip-ranges.json (we checked; it 404s
# after the consolidation to platform.claude.com). Access is gated via basic-auth at
# /etc/nginx/docs.htpasswd instead.
#
# When Anthropic starts publishing (watch https://docs.claude.com/ for mentions), this script
# fetches + parses the list, regenerates /etc/nginx/conf.d/docs-ip-allowlist.conf, and reloads
# nginx. The stub fails fast so cron calls visibly noop rather than silently succeeding.
set -e

KNOWN_URL_CANDIDATES=(
    "https://docs.claude.com/ip-ranges.json"
    "https://docs.anthropic.com/ip-ranges.json"
    "https://api.anthropic.com/v1/ip-ranges"
)

for url in "${KNOWN_URL_CANDIDATES[@]}"; do
    STATUS=$(curl -sL -o /dev/null -w '%{http_code}' -m 10 "$url" 2>/dev/null)
    if [ "$STATUS" = "200" ]; then
        echo "IP ranges published at $url — implement parsing below."
        # TODO: curl, jq to extract CIDRs, write nginx conf like:
        #   allow 1.2.3.0/24;
        #   allow 4.5.6.0/16;
        #   deny all;
        # Then: nginx -t && systemctl reload nginx
        # Then: optionally remove auth_basic from the /docs/ block so IP is the sole gate.
        exit 0
    fi
done

# No authoritative source yet. Not an error; basic-auth still gates access.
echo "[$(date -Iseconds)] No Anthropic IP range endpoint available yet; basic-auth remains the gate."
exit 0
