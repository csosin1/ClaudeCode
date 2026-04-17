#!/bin/bash
# post-deploy-rsync.sh — mirror migrated projects from dev to prod after auto-deploy
# writes local files. Called at the end of auto_deploy_general.sh and as a cron
# safety-net every 5 min.
#
# Reads /etc/deploy-to-prod.conf for per-project source→destination mappings.
#
# Design decisions:
# - Excludes venv/, .env, __pycache__, *.pyc, data/. Project data is authoritative
#   on prod post-migration; dev's copy drifts and shouldn't overwrite.
# - --delete applied (dev's file tree is the source of truth for code);
#   exclusions protect data + secrets + generated artifacts.
# - Timeouts + ConnectTimeout prevent a stuck prod from hanging auto-deploy.
# - Exit code is always 0 — rsync failure should not break auto-deploy pipeline.
#   (Failure fires a notify.sh instead.)
set +e

CONF=/etc/deploy-to-prod.conf
LOG=/var/log/post-deploy-rsync.log
LOCK=/var/run/post-deploy-rsync.lock

# Single-flighting to avoid overlapping runs (cron + hook both call this).
exec 9>"$LOCK"
flock -n 9 || { echo "$(date): another run in progress, skipping" >> "$LOG"; exit 0; }

[ -f "$CONF" ] || exit 0

EXCLUDES=(
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='venv/'
    --exclude='.env'
    --exclude='data/'
    --exclude='.git/'
    --exclude='.claude/'
    --exclude='node_modules/'
    --exclude='.chrome-profile*/'
    --exclude='*.log'
)

NOW=$(date -Iseconds)
FAILED=0
SYNCED=0

while IFS= read -r line <&3 || [ -n "$line" ]; do
    line="${line%%#*}"                                # strip trailing comments
    line="$(echo "$line" | xargs 2>/dev/null || true)"  # trim whitespace
    [ -z "$line" ] && continue

    # Parse: LOCAL  HOST:REMOTE  [POST_CMD...]
    LOCAL="${line%% *}"
    rest="${line#"$LOCAL"}"
    rest="${rest# }"
    HOST_REMOTE="${rest%% *}"
    POST_CMD="${rest#"$HOST_REMOTE"}"
    POST_CMD="${POST_CMD# }"

    HOST="${HOST_REMOTE%%:*}"
    REMOTE="${HOST_REMOTE#*:}"

    [ -d "$LOCAL" ] || { echo "$(date): skip missing $LOCAL" >> "$LOG"; continue; }

    # rsync with bounded timeouts
    rsync -az --delete \
        -e 'ssh -o ConnectTimeout=10 -o ServerAliveInterval=10' \
        "${EXCLUDES[@]}" \
        --timeout=60 \
        "$LOCAL"/ "$HOST":"$REMOTE"/ >> "$LOG" 2>&1
    RC=$?

    if [ "$RC" -eq 0 ]; then
        SYNCED=$((SYNCED+1))
        if [ -n "$POST_CMD" ]; then
            ssh -o ConnectTimeout=10 "$HOST" "$POST_CMD" >> "$LOG" 2>&1 || echo "$(date): post-cmd nonzero on $HOST: $POST_CMD" >> "$LOG"
        fi
    else
        FAILED=$((FAILED+1))
        echo "$(date): rsync failed rc=$RC for $LOCAL → $HOST:$REMOTE" >> "$LOG"
        /usr/local/bin/notify.sh \
            "post-deploy rsync failed for $LOCAL → $HOST (rc=$RC). See $LOG." \
            "Deploy mirror failed" \
            urgent \
            "" 2>/dev/null || true
    fi
done 3< "$CONF"

echo "$(date): post-deploy-rsync done: synced=$SYNCED failed=$FAILED" >> "$LOG"
exit 0
