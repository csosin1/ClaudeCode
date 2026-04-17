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
    # Stateful DB files: post-migration, prod is the authoritative writer
    # for SQLite state (gyms.db, offers.db, dashboard.db, etc.). rsync's
    # default "source wins when mtime/content differs" would let a stale
    # dev copy clobber a freshly-written prod DB. Exclude all SQLite
    # variants + their WAL/shared-memory sidecars. Audit discovered
    # 2026-04-17 in response to "make sure writes land in the right place."
    --exclude='*.db'
    --exclude='*.db-wal'
    --exclude='*.db-journal'
    --exclude='*.db-shm'
    --exclude='*.sqlite'
    --exclude='*.sqlite-wal'
    --exclude='*.sqlite-journal'
    --exclude='*.sqlite-shm'
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

    # rsync with bounded timeouts. --stats output gates POST_CMD firing —
    # running `systemctl try-restart` on every cron cycle kills long-sleeping
    # services. Concrete failure 2026-04-17: timeshare-surveillance-watcher
    # sleeps 900s between EDGAR cycles, got killed every 5 min by the
    # unconditional try-restart here, combined.json went 4 days stale.
    RSYNC_TMP=$(mktemp)
    rsync -az --delete --stats \
        -e 'ssh -o ConnectTimeout=10 -o ServerAliveInterval=10' \
        "${EXCLUDES[@]}" \
        --timeout=60 \
        "$LOCAL"/ "$HOST":"$REMOTE"/ > "$RSYNC_TMP" 2>&1
    RC=$?
    cat "$RSYNC_TMP" >> "$LOG"

    if [ "$RC" -eq 0 ]; then
        SYNCED=$((SYNCED+1))
        # Count files actually transferred. rsync --stats emits exactly one
        # "Number of regular files transferred: N" line. Missing defaults 0.
        TRANSFERRED=$(awk -F': ' '/^Number of regular files transferred:/ {gsub(/,/,"",$2); print $2; exit}' "$RSYNC_TMP")
        TRANSFERRED=${TRANSFERRED:-0}
        if [ -n "$POST_CMD" ] && [ "$TRANSFERRED" -gt 0 ]; then
            echo "$(date): $TRANSFERRED file(s) changed on $HOST:$REMOTE — running POST_CMD" >> "$LOG"
            ssh -o ConnectTimeout=10 "$HOST" "$POST_CMD" >> "$LOG" 2>&1 || echo "$(date): post-cmd nonzero on $HOST: $POST_CMD" >> "$LOG"
        fi
    fi
    rm -f "$RSYNC_TMP"

    if [ "$RC" -ne 0 ]; then
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
