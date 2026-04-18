#!/bin/bash
# Auto-deploy: checks GitHub every 30s, deploys if there are changes.
cd /opt/abs-dashboard

# Fetch latest from GitHub
git fetch origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/claude/carvana-loan-dashboard-4QMPM)

# Bootstrap general auto-deploy (one-time: installs timer for main branch)
if [ -f /opt/abs-dashboard/deploy/setup_general_deploy.sh ] && [ ! -f /opt/.general_deploy_setup ]; then
    echo "$(date): Installing general auto-deploy for main branch..."
    bash /opt/abs-dashboard/deploy/setup_general_deploy.sh >> /var/log/auto-deploy.log 2>&1 || true
    touch /opt/.general_deploy_setup
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): New changes detected, deploying..."
    git reset --hard origin/claude/carvana-loan-dashboard-4QMPM

    # Check if a reingest is needed (flag file in repo signals this)
    if [ -f /opt/abs-dashboard/deploy/REINGEST_VERSION ]; then
        NEED_VERSION=$(cat /opt/abs-dashboard/deploy/REINGEST_VERSION)
        HAVE_VERSION=$(cat /opt/.reingest_done 2>/dev/null || echo "none")
        if [ "$NEED_VERSION" != "$HAVE_VERSION" ]; then
            echo "$(date): Reingest needed (v$NEED_VERSION)..."
            /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/reingest_pool.py >> /var/log/auto-deploy.log 2>&1 || true
            /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/rebuild_summaries.py >> /var/log/auto-deploy.log 2>&1 || true
            echo "$NEED_VERSION" > /opt/.reingest_done
        fi
    fi

    # Install any new dependencies
    /opt/abs-venv/bin/pip install -q -r /opt/abs-dashboard/carvana_abs/requirements.txt >> /var/log/auto-deploy.log 2>&1 || true

    # Install weasyprint system dependencies (one-time)
    if [ ! -f /opt/.weasyprint_deps_installed ]; then
        echo "$(date): Installing weasyprint system dependencies..."
        apt-get update -qq >> /var/log/auto-deploy.log 2>&1 || true
        apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libcairo2 libffi-dev >> /var/log/auto-deploy.log 2>&1 || true
        touch /opt/.weasyprint_deps_installed
    fi

    # Always export dashboard DB, run model, and regenerate preview on code changes.
    # generate_pdfs.py removed — Documents tab now links straight to EDGAR.
    #
    # Methodology-rebuild guard: if compute_methodology.py is currently
    # rebuilding analytics.json (lock at /opt/.methodology_rebuild.lock),
    # defer the regen. Otherwise we ship a dashboard built against a stale
    # analytics cache (e.g. empty heatmap / FICO×LTV grid mid-rebuild).
    # Stale locks (PID no longer alive) are cleared, then we proceed.
    LOCK=/opt/.methodology_rebuild.lock
    if [ -f "$LOCK" ]; then
        LOCK_PID=$(awk -F'|' '{print $1}' "$LOCK" 2>/dev/null)
        if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
            echo "$(date): methodology rebuild in progress (pid=$LOCK_PID); deferring regen — auto-deploy will retry next cycle" >> /var/log/auto-deploy.log
            exit 0
        else
            echo "$(date): clearing stale methodology rebuild lock (pid=$LOCK_PID not running)" >> /var/log/auto-deploy.log
            rm -f "$LOCK"
        fi
    fi
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/export_dashboard_db.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/default_model.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py >> /var/log/auto-deploy.log 2>&1 || true

    # Run data validation and check the generated HTML
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/validate_data.py >> /var/log/auto-deploy.log 2>&1 || true
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/validate_dashboard.py > /opt/abs-dashboard/deploy/LAST_VALIDATION.txt 2>&1
    cat /opt/abs-dashboard/deploy/LAST_VALIDATION.txt >> /var/log/auto-deploy.log
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/deploy_status.py >> /var/log/auto-deploy.log 2>&1 || true

    # Write status and push to GitHub so it can be read remotely
    /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/deploy_status.py > /opt/abs-dashboard/deploy/LAST_STATUS.json 2>&1 || true
    cd /opt/abs-dashboard
    git add deploy/LAST_STATUS.json deploy/LAST_VALIDATION.txt deploy/LAST_DATA_CHECK.txt 2>/dev/null
    git commit -m "Auto-deploy status update" --allow-empty 2>/dev/null || true
    # Pull-rebase before push to avoid non-fast-forward rejection
    git pull --rebase origin claude/carvana-loan-dashboard-4QMPM 2>/dev/null || true
    git push origin claude/carvana-loan-dashboard-4QMPM 2>>/var/log/auto-deploy.log || echo "$(date): git push failed" >> /var/log/auto-deploy.log

    # Run any one-time setup scripts
    if [ -f /opt/abs-dashboard/deploy/setup_preview.sh ] && [ ! -f /opt/.preview_setup ]; then
        bash /opt/abs-dashboard/deploy/setup_preview.sh
        touch /opt/.preview_setup
    fi

    # Auto-promote if PROMOTE flag exists
    if [ -f /opt/abs-dashboard/deploy/PROMOTE ]; then
        /opt/abs-venv/bin/python /opt/abs-dashboard/carvana_abs/generate_preview.py promote >> /var/log/auto-deploy.log 2>&1 || true
        echo "$(date): Promoted preview to live."
    fi

    # One-time: install weekly new-deal-discovery cron.
    # Re-runs if the source file content changes (hash-gated).
    if [ -f /opt/abs-dashboard/deploy/cron.d/abs-discover-deals ]; then
        WANT=$(sha256sum /opt/abs-dashboard/deploy/cron.d/abs-discover-deals | awk '{print $1}')
        HAVE=$(cat /opt/.abs_discover_cron_hash 2>/dev/null || echo "none")
        if [ "$WANT" != "$HAVE" ]; then
            echo "$(date): Installing /etc/cron.d/abs-discover-deals (hash $WANT)..."
            mkdir -p /var/log/abs-dashboard
            cp /opt/abs-dashboard/deploy/cron.d/abs-discover-deals /etc/cron.d/abs-discover-deals
            chmod 644 /etc/cron.d/abs-discover-deals
            chown root:root /etc/cron.d/abs-discover-deals
            echo "$WANT" > /opt/.abs_discover_cron_hash
        fi
    fi

    # Update the running copy of this script
    cp /opt/abs-dashboard/deploy/auto_deploy.sh /opt/auto_deploy.sh 2>/dev/null || true

    # TODO(post-deploy-qa): wire in the post-deploy QA hook once infra publishes
    # the required artefacts. Per the 2026-04-18 infra entry in
    # /opt/site-deploy/CHANGES.md ("infra: post-deploy QA hook"), this deploy
    # script should invoke a post-deploy hook against the live URL immediately
    # after regen completes — with --freeze-on-fail so a bad regen halts
    # subsequent auto-deploys rather than silently overwriting a good live
    # build. Blocked: as of 2026-04-18 the following paths do NOT exist on
    # prod (verified via `test -e`):
    #   - /usr/local/bin/post-deploy-qa-hook.sh  (MISSING)
    #   - /etc/post-deploy-qa.conf               (MISSING)
    # A request to publish them is filed in /opt/site-deploy/CHANGES.md under
    # "2026-04-18 — request from abs-dashboard chat: publish post-deploy QA
    # hook artefacts". Once published, replace this TODO block with:
    #
    #   if [ -x /usr/local/bin/post-deploy-qa-hook.sh ]; then
    #       /usr/local/bin/post-deploy-qa-hook.sh abs-dashboard --freeze-on-fail \
    #           >> /var/log/auto-deploy.log 2>&1 || \
    #           echo "$(date): post-deploy QA hook reported failure (see /var/log/post-deploy-qa.log)" \
    #               >> /var/log/auto-deploy.log
    #   fi
    #
    # Do NOT add a stub of the hook locally — running a no-op hook would
    # masquerade as coverage where none exists.

    echo "$(date): Deploy complete. Preview updated."
else
    echo "$(date): No changes."
fi
