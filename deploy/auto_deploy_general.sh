#!/bin/bash
# General auto-deploy: watches main branch, syncs static files to the droplet.
# Webhook triggers instant deploy; 5-min timer as fallback.
#
# RULE 1: Update THIS SCRIPT first after git reset — breaks deadlock if old version is stuck.
# RULE 2: Static file sync next (2-3s). Heavy setup (npm, apt-get) runs last and never blocks.
# RULE 3: Project deploy scripts live in deploy/<project>.sh — owned by project chats.
# RULE 4: 2026-04-17 — set -eE + ERR trap fires urgent ntfy on deploy failure.
#         Most existing commands already have `|| true` or `|| echo WARNING` suffixes;
#         those remain non-fatal under set -e. Intentionally-fatal commands (git
#         reset, rsync, systemctl daemon-reload) abort + fire the trap.

set -eE -o pipefail

REPO_DIR="/opt/site-deploy"
LOG="/var/log/general-deploy.log"

# Failure trap — fires once, writes context + urgent notify, then exits.
# Recursion guard via _DEPLOY_FAIL_FIRED prevents re-entry if notify.sh itself errors.
_DEPLOY_FAIL_FIRED=0
on_deploy_fail() {
    local rc="$1" line="$2"
    [ "$_DEPLOY_FAIL_FIRED" = "1" ] && exit "$rc"
    _DEPLOY_FAIL_FIRED=1
    local sha
    sha="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    local last_log
    last_log="$(tail -3 "$LOG" 2>/dev/null | tr '\n' '|' || echo '')"
    echo "$(date): Deploy FAILED at line $line (rc=$rc). SHA=$sha. Last log: $last_log" >> "$LOG"
    if [ -x /usr/local/bin/notify.sh ]; then
        /usr/local/bin/notify.sh \
            "Deploy FAILED on dev at line $line (rc=$rc). SHA $sha. Last: $last_log" \
            "Deploy FAILED (SHA $sha)" \
            urgent \
            "https://casinv.dev/projects.html" >> "$LOG" 2>&1 || true
    fi
    exit "$rc"
}
trap 'on_deploy_fail $? $LINENO' ERR

# Find Node.js — may be installed via nvm, nodesource, or snap
NODE_BIN=""
for candidate in /usr/local/bin/node /usr/bin/node /snap/bin/node "$HOME/.nvm/versions/node/*/bin/node"; do
    if [ -x "$candidate" ]; then
        NODE_BIN="$candidate"
        break
    fi
done
if [ -z "$NODE_BIN" ]; then
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" 2>/dev/null
    NODE_BIN="$(command -v node 2>/dev/null || true)"
fi
if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN" ]; then
    echo "$(date): Node.js not found, installing via nodesource..." >> "$LOG"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >> "$LOG" 2>&1
    apt-get install -y nodejs >> "$LOG" 2>&1
    NODE_BIN="$(command -v node 2>/dev/null || echo /usr/bin/node)"
fi

NPM_BIN="$(dirname "$NODE_BIN")/npm"
NPX_BIN="$(dirname "$NODE_BIN")/npx"
export PATH="$(dirname "$NODE_BIN"):$PATH"

cd "$REPO_DIR" || exit 1

# Fetch latest from main. Transient network failure must NOT fire the failure trap;
# the next invocation (webhook or 5-min timer) will retry. Silent no-op on fail.
git fetch origin main 2>/dev/null || true

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New code on main, deploying..." >> "$LOG"
    git reset --hard origin/main

    # === STEP 0: UPDATE THIS SCRIPT FIRST (breaks deadlock) ===
    cp "$REPO_DIR/deploy/auto_deploy_general.sh" /opt/auto_deploy_general.sh 2>/dev/null || true

    # === STEP 1: NGINX CONFIG (if version changed) ===
    if [ -f "$REPO_DIR/deploy/NGINX_VERSION" ]; then
        NEED=$(cat "$REPO_DIR/deploy/NGINX_VERSION")
        HAVE=$(cat /opt/.nginx_version 2>/dev/null || echo "none")
        if [ "$NEED" != "$HAVE" ]; then
            echo "$(date): Updating nginx config (v$NEED)..." >> "$LOG"
            mkdir -p /var/www/landing/live /var/www/landing/preview
            bash "$REPO_DIR/deploy/update_nginx.sh" >> "$LOG" 2>&1 || true
            echo "$NEED" > /opt/.nginx_version
        fi
    fi

    # === STEP 2: FAST STATIC SYNC — writes to preview/ only ===
    # Live is only updated via deploy/promote.sh after user acceptance.

    mkdir -p /var/www/landing/live /var/www/landing/preview
    cp "$REPO_DIR/deploy/landing.html" /var/www/landing/preview/index.html 2>/dev/null || true
    # Bootstrap: seed live if this is a fresh install
    [ -s /var/www/landing/live/index.html ] || cp "$REPO_DIR/deploy/landing.html" /var/www/landing/live/index.html 2>/dev/null || true

    if [ -d "$REPO_DIR/games" ]; then
        mkdir -p /var/www/games/live /var/www/games/preview
        rsync -a --delete "$REPO_DIR/games/" /var/www/games/preview/
        # Bootstrap live if empty
        [ -z "$(ls -A /var/www/games/live 2>/dev/null)" ] && rsync -a "$REPO_DIR/games/" /var/www/games/live/ || true
    fi

    if [ -d "$REPO_DIR/carvana" ]; then
        mkdir -p /var/www/carvana/live /var/www/carvana/preview
        rsync -a --delete "$REPO_DIR/carvana/" /var/www/carvana/preview/
        [ -z "$(ls -A /var/www/carvana/live 2>/dev/null)" ] && rsync -a "$REPO_DIR/carvana/" /var/www/carvana/live/ || true
    fi

    # Dashboard page (live + preview)
    if [ -f "$REPO_DIR/deploy/projects.html" ]; then
        cp "$REPO_DIR/deploy/projects.html" /var/www/landing/preview/projects.html
        [ -s /var/www/landing/live/projects.html ] || cp "$REPO_DIR/deploy/projects.html" /var/www/landing/live/projects.html
    fi

    # Kickoff entry + status pages (copied to /var/www/landing/ directly — served by root location)
    for h in new-project.html kickoff-status.html; do
        if [ -f "$REPO_DIR/deploy/$h" ]; then
            cp "$REPO_DIR/deploy/$h" "/var/www/landing/$h"
        fi
    done

    # Kickoff CGI endpoints (served by fcgiwrap via nginx /cgi-bin/ location)
    if [ -d "$REPO_DIR/helpers/cgi-bin" ]; then
        mkdir -p /var/www/landing/cgi-bin
        for f in "$REPO_DIR/helpers/cgi-bin"/kickoff-*; do
            [ -f "$f" ] && install -m 755 "$f" "/var/www/landing/cgi-bin/$(basename "$f")"
        done
    fi

    # Kickoff builder-dispatch watcher (systemd path + service units)
    for u in kickoff-builder-watcher.path kickoff-builder-watcher.service; do
        if [ -f "$REPO_DIR/helpers/$u" ] && ! cmp -s "$REPO_DIR/helpers/$u" "/etc/systemd/system/$u" 2>/dev/null; then
            cp "$REPO_DIR/helpers/$u" "/etc/systemd/system/$u"
            systemctl daemon-reload
            [ "$u" = "kickoff-builder-watcher.path" ] && systemctl enable --now kickoff-builder-watcher.path 2>/dev/null || true
        fi
    done

    # Per-droplet helper scripts (keep /usr/local/bin copy in sync with repo)
    if [ -d "$REPO_DIR/helpers" ]; then
        for s in claude-project.sh end-project.sh task-status.sh notify.sh start-claude.sh post-deploy-qa-hook.sh; do
            if [ -f "$REPO_DIR/helpers/$s" ]; then
                install -m 755 "$REPO_DIR/helpers/$s" /usr/local/bin/$s 2>/dev/null || true
            fi
        done
        # Sync post-deploy-qa conf (version-controlled mirror → /etc). Only
        # copy when the repo copy differs, so operators can edit /etc/ for a
        # quick ad-hoc change and have it survive until the mirror catches up.
        if [ -f "$REPO_DIR/helpers/post-deploy-qa.conf" ] && \
           ! cmp -s "$REPO_DIR/helpers/post-deploy-qa.conf" /etc/post-deploy-qa.conf 2>/dev/null; then
            install -m 644 "$REPO_DIR/helpers/post-deploy-qa.conf" /etc/post-deploy-qa.conf 2>/dev/null || true
        fi
        # start-claude.sh goes to /root as well
        [ -f "$REPO_DIR/helpers/start-claude.sh" ] && install -m 755 "$REPO_DIR/helpers/start-claude.sh" /root/start-claude.sh
        # systemd unit for claude-tmux
        if [ -f "$REPO_DIR/helpers/claude-tmux.service" ] && ! cmp -s "$REPO_DIR/helpers/claude-tmux.service" /etc/systemd/system/claude-tmux.service 2>/dev/null; then
            cp "$REPO_DIR/helpers/claude-tmux.service" /etc/systemd/system/claude-tmux.service
            systemctl daemon-reload
        fi
    fi

    echo "$(date): Static files deployed to preview (live unchanged; promote via deploy/promote.sh)." >> "$LOG"

    # === STEP 3: SERVER-SIDE PROJECTS (each project sources its own deploy script) ===
    # Per-project live-URL map — used by the post-deploy QA hook (Gap 3 fix,
    # 2026-04-17 Hazard-by-LTV incident). Add a row when a new project opts
    # in to post-deploy QA by writing an entry in /etc/post-deploy-qa.conf.
    # Project name is derived from the deploy/<project>.sh filename stem.
    declare -A PROJECT_LIVE_URL=(
        [abs-dashboard]="https://casinv.dev/CarvanaLoanDashBoard/"
        [carvana-abs]="https://casinv.dev/CarvanaLoanDashBoard/"
        [car-offers]="https://casinv.dev/car-offers/"
        [gym-intelligence]="https://casinv.dev/gym-intelligence/"
        [timeshare-surveillance]="https://casinv.dev/timeshare-surveillance/"
    )

    for deploy_script in "$REPO_DIR"/deploy/*.sh; do
        script_name="$(basename "$deploy_script")"
        # Skip infrastructure scripts
        case "$script_name" in
            auto_deploy_general.sh|update_nginx.sh|setup_*.sh) continue ;;
        esac
        project_name="${script_name%.sh}"

        # Freeze gate: if the post-deploy QA hook previously failed with
        # --freeze-on-fail, skip this project's regen until an operator
        # clears /var/run/auto-deploy-frozen-<project>. Notify once per
        # skipped cycle so the user knows work is blocked.
        if [ -f "/var/run/auto-deploy-frozen-$project_name" ]; then
            echo "$(date): SKIP deploy/$script_name — frozen by post-deploy QA (rm /var/run/auto-deploy-frozen-$project_name to unfreeze)." >> "$LOG"
            if [ -x /usr/local/bin/notify.sh ]; then
                /usr/local/bin/notify.sh \
                    "Auto-deploy SKIPPED $project_name — frozen by post-deploy QA. Investigate, then rm /var/run/auto-deploy-frozen-$project_name." \
                    "Auto-deploy frozen: $project_name" \
                    urgent \
                    "https://casinv.dev/projects.html" >> "$LOG" 2>&1 || true
            fi
            continue
        fi

        echo "$(date): Running deploy/$script_name..." >> "$LOG"
        (
            cd "$REPO_DIR" || exit 1
            source "$deploy_script"
        ) >> "$LOG" 2>&1 || echo "$(date): WARNING — deploy/$script_name failed." >> "$LOG"

        # Post-deploy QA gate. Runs the project's @post-deploy-tagged tests
        # against the live URL after regen. Opt-in via a row in
        # /etc/post-deploy-qa.conf; absence = silent skip. Failure notifies
        # and (if configured) writes a freeze sentinel consulted above.
        if [ -f /etc/post-deploy-qa.conf ] && [ -x /usr/local/bin/post-deploy-qa-hook.sh ]; then
            if grep -qE "^${project_name}[[:space:]]" /etc/post-deploy-qa.conf; then
                live_url="${PROJECT_LIVE_URL[$project_name]:-}"
                if [ -n "$live_url" ]; then
                    /usr/local/bin/post-deploy-qa-hook.sh "$project_name" "$live_url" \
                        >> /var/log/post-deploy-qa.log 2>&1 || \
                        echo "$(date): post-deploy QA failed for $project_name; see /var/log/post-deploy-qa.log" >> "$LOG"
                else
                    echo "$(date): WARNING — $project_name has a post-deploy-qa.conf row but no live URL mapped in auto_deploy_general.sh; skipping hook." >> "$LOG"
                fi
            fi
        fi
    done

    # === STEP 4: STATUS PAGE + DIAGNOSTICS ===
    mkdir -p /var/www/landing

    # debug.json — lightweight health check for QA tests
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"node_version\": \"$("$NODE_BIN" --version 2>&1 || echo 'NOT_FOUND')\","
        echo "  \"car_offers_status\": \"$(systemctl is-active car-offers 2>&1)\","
        echo "  \"port_3100\": $(ss -tlnp | grep -q ':3100' && echo true || echo false),"
        echo "  \"gym_intelligence_status\": \"$(systemctl is-active gym-intelligence 2>&1)\","
        echo "  \"port_8502\": $(ss -tlnp | grep -q ':8502' && echo true || echo false)"
        echo "}"
    } > /var/www/landing/debug.json

    # status.json — rich diagnostics for project chats to read via /status.json
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -Iseconds)\","
        echo "  \"uptime\": \"$(uptime -p 2>/dev/null || echo 'unknown')\","
        echo "  \"deploy_commit\": \"$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null)\","
        echo "  \"deploy_message\": $(git -C "$REPO_DIR" log -1 --pretty=format:'"%s"' 2>/dev/null || echo '""'),"

        echo "  \"services\": {"
        # Enumerate all project services
        FIRST_SVC=true
        for svc in car-offers gym-intelligence; do
            $FIRST_SVC || echo ","
            FIRST_SVC=false
            SVC_STATUS="$(systemctl is-active "$svc" 2>&1)"
            SVC_ENABLED="$(systemctl is-enabled "$svc" 2>&1)"
            SVC_LOG=""
            # Get last 3 log lines, JSON-escaped
            if [ -f "/var/log/$svc/error.log" ] || [ -f "/var/log/$svc/app.log" ]; then
                LOG_FILE="/var/log/$svc/error.log"
                [ -f "/var/log/$svc/app.log" ] && LOG_FILE="/var/log/$svc/app.log"
                SVC_LOG=$(tail -3 "$LOG_FILE" 2>/dev/null | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')
            fi
            [ -z "$SVC_LOG" ] && SVC_LOG='""'
            echo "    \"$svc\": {"
            echo "      \"status\": \"$SVC_STATUS\","
            echo "      \"enabled\": \"$SVC_ENABLED\","
            echo "      \"recent_log\": $SVC_LOG"
            echo "    }"
        done
        echo "  },"

        echo "  \"ports\": {"
        echo "    \"3100\": $(ss -tlnp | grep -q ':3100' && echo true || echo false),"
        echo "    \"8502\": $(ss -tlnp | grep -q ':8502' && echo true || echo false),"
        echo "    \"9000\": $(ss -tlnp | grep -q ':9000' && echo true || echo false)"
        echo "  },"

        echo "  \"disk\": \"$(df -h / | awk 'NR==2{print $5}' 2>/dev/null || echo 'unknown')\","
        echo "  \"memory_free\": \"$(free -h | awk '/^Mem:/{print $4}' 2>/dev/null || echo 'unknown')\","
        echo "  \"deploy_log_tail\": $(tail -10 "$LOG" 2>/dev/null | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')"
        echo "}"
    } > /var/www/landing/status.json

    echo "$(date): Deploy complete." >> "$LOG"

    # Mirror migrated projects to prod droplet (Option B migration).
    # Reads /etc/deploy-to-prod.conf; no-op if nothing configured.
    # Non-blocking: any failure is logged + notified, does not break auto-deploy.
    if [ -x /usr/local/bin/post-deploy-rsync.sh ]; then
        /usr/local/bin/post-deploy-rsync.sh >> "$LOG" 2>&1 &
    fi

    # --- Push notifications disabled by user. Re-enable by uncommenting below. ---
    # if [ -x /usr/local/bin/notify.sh ]; then
    #     SHORT_SHA=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "")
    #     /usr/local/bin/notify.sh \
    #         "Preview updated ($SHORT_SHA). Tap to review; reply 'ship it' to promote to live." \
    #         "Preview ready" \
    #         default \
    #         "https://casinv.dev/preview/" >> "$LOG" 2>&1 || true
    # fi
else
    : # No changes — silent
fi
