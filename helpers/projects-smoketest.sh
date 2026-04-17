#!/bin/bash
# projects-smoketest.sh — hit every project's live + preview URLs, assert 200.
# Runs after any shared-infra change (/etc/nginx, /etc/systemd, /etc/cron*, /var/www)
# to catch regressions that only manifest in specific projects.
#
# Modes:
#   report        default. Prints status of every URL; exit 0 regardless (for baselining).
#   gate          exit non-zero if any URL fails. Use as pre-commit guard for shared infra.
#   --quiet       no output when all pass (for cron).
#
# Output: /var/www/landing/smoketest.json with per-URL status + timestamp.
set -u

MODE="${1:-report}"
QUIET=0
[ "${2:-}" = "--quiet" ] && QUIET=1

OUT=/var/www/landing/smoketest.json
mkdir -p "$(dirname "$OUT")"
NOW=$(date -Iseconds)
TMP=$(mktemp)

# URL list. Add rows here when new projects ship.
# Format: <label>|<url>|<optional-grep-string-that-must-appear>
URLS='
landing|https://casinv.dev/|
projects|https://casinv.dev/projects.html|Projects
todo|https://casinv.dev/todo.html|
capacity|https://casinv.dev/capacity.html|Droplet Capacity
accounts|https://casinv.dev/accounts.html|
telemetry|https://casinv.dev/telemetry.html|
timeshare-surveillance-live|https://casinv.dev/timeshare-surveillance/|Timeshare
timeshare-surveillance-preview|https://casinv.dev/timeshare-surveillance/preview/|
carvana-abs-live|https://casinv.dev/CarvanaLoanDashBoard/|
carvana-abs-preview|https://casinv.dev/CarvanaLoanDashBoard/preview/|
car-offers-live|https://casinv.dev/car-offers/|
car-offers-preview|https://casinv.dev/car-offers/preview/|
gym-intelligence-live|https://casinv.dev/gym-intelligence/|Gym
gym-intelligence-preview|https://casinv.dev/gym-intelligence/preview/|
games|https://casinv.dev/games/|Games
liveness-json|https://casinv.dev/liveness.json|projects
tokens-json|https://casinv.dev/tokens.json|
'

FAIL=0
PASS=0
FIRST_FAIL_LABEL=""
echo '{"updated_at":"'"$NOW"'","results":[' > "$TMP"
FIRST=1

while IFS='|' read -r label url grep_check; do
    [ -z "$label" ] && continue
    [ -z "$url" ] && continue
    STATUS=$(curl -s -o /tmp/smoketest-$$.body -w '%{http_code}' --max-time 10 "$url")
    OK=0
    REASON=""
    if [ "$STATUS" = "200" ]; then
        if [ -n "$grep_check" ]; then
            if grep -q "$grep_check" /tmp/smoketest-$$.body 2>/dev/null; then
                OK=1
            else
                REASON="200 but missing expected content: $grep_check"
            fi
        else
            OK=1
        fi
    else
        REASON="HTTP $STATUS"
    fi
    rm -f /tmp/smoketest-$$.body

    if [ "$OK" = "1" ]; then
        PASS=$((PASS+1))
        [ "$QUIET" = "0" ] && echo "PASS  $label  ($url)"
    else
        FAIL=$((FAIL+1))
        [ -z "$FIRST_FAIL_LABEL" ] && FIRST_FAIL_LABEL="$label"
        echo "FAIL  $label  ($url) — $REASON" >&2
    fi

    [ "$FIRST" = "1" ] || echo "," >> "$TMP"
    FIRST=0
    printf '  {"label":"%s","url":"%s","status":"%s","ok":%s,"reason":"%s"}' \
        "$label" "$url" "$STATUS" "$([ "$OK" = "1" ] && echo true || echo false)" "$REASON" >> "$TMP"
done <<< "$URLS"

echo '' >> "$TMP"
echo '],"summary":{"pass":'"$PASS"',"fail":'"$FAIL"'}}' >> "$TMP"
mv "$TMP" "$OUT"

echo ""
echo "Summary: $PASS passed, $FAIL failed"
[ "$MODE" = "gate" ] && [ "$FAIL" -gt 0 ] && exit 1

# Notify on regression / recovery. Only in report mode (gate mode is a
# pre-commit guard — it already blocks the ship; paging the user there
# would be noise). Tracked via /var/run/claude-sessions/smoketest-last-state.
# Format: "<fail_count> <epoch_last_notify>".  Debounce: 60 min while sustained.
if [ "$MODE" = "report" ] && [ -x /usr/local/bin/notify.sh ]; then
    STATE_DIR=/var/run/claude-sessions
    STATE_FILE="$STATE_DIR/smoketest-last-state"
    mkdir -p "$STATE_DIR"
    PRIOR_FAIL=0
    PRIOR_TS=0
    if [ -r "$STATE_FILE" ]; then
        read -r PRIOR_FAIL PRIOR_TS < "$STATE_FILE" || true
        PRIOR_FAIL="${PRIOR_FAIL:-0}"
        PRIOR_TS="${PRIOR_TS:-0}"
    fi
    NOW_TS=$(date +%s)
    DEBOUNCE=3600  # 60 min
    NEW_TS="$PRIOR_TS"
    CLICK="https://casinv.dev/smoketest.json"

    if [ "$PRIOR_FAIL" -eq 0 ] && [ "$FAIL" -gt 0 ]; then
        # New regression.
        /usr/local/bin/notify.sh \
            "Smoketest regression: $FAIL URL(s) failing. Last failure: $FIRST_FAIL_LABEL. See /smoketest.json" \
            "Smoketest regression" urgent "$CLICK" || true
        NEW_TS="$NOW_TS"
    elif [ "$PRIOR_FAIL" -gt 0 ] && [ "$FAIL" -gt 0 ]; then
        # Sustained outage. Debounce to once per hour; escalate to urgent if worsened.
        if [ "$FAIL" -gt "$PRIOR_FAIL" ]; then
            /usr/local/bin/notify.sh \
                "Smoketest worsened: $FAIL URL(s) failing (was $PRIOR_FAIL). Last failure: $FIRST_FAIL_LABEL." \
                "Smoketest regression" urgent "$CLICK" || true
            NEW_TS="$NOW_TS"
        elif [ "$((NOW_TS - PRIOR_TS))" -ge "$DEBOUNCE" ]; then
            /usr/local/bin/notify.sh \
                "Smoketest still failing: $FAIL URL(s) down. Last failure: $FIRST_FAIL_LABEL." \
                "Smoketest regression" default "$CLICK" || true
            NEW_TS="$NOW_TS"
        fi
    elif [ "$PRIOR_FAIL" -gt 0 ] && [ "$FAIL" -eq 0 ]; then
        # Recovery.
        /usr/local/bin/notify.sh \
            "Smoketest recovered: all $PASS URL(s) passing." \
            "Smoketest recovered" default "$CLICK" || true
        NEW_TS="$NOW_TS"
    fi
    # prior == 0 && current == 0 → silent, no-op.
    echo "$FAIL $NEW_TS" > "$STATE_FILE"
fi

exit 0
