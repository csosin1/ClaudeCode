#!/bin/bash
# dev-python-guard.sh — installed as /opt/abs-venv/bin/python3 on dev droplet.
#
# Refuses to run heavy Python compute on the dev droplet post-migration.
# The abs-dashboard Python venv is preserved on dev only as a rollback copy;
# running anything real through it is wasted compute + pollutes the rollback
# state. Apps belong on prod (casinv-prod).
#
# Override for emergency/debug: ALLOW_DEV_COMPUTE=1 python ...
#
# History: 2026-04-17/18 — three separate incidents of heavy compute landing
# on dev after migration. tmux directives + CLAUDE.md updates weren't enough.
# This is the durable enforcement layer. See LESSONS 2026-04-18.

set -u

DEV_HOSTNAME="Cliffsfirstdroplet"
PROD_SSH_ALIAS="prod-private"

if [ "$(hostname)" = "$DEV_HOSTNAME" ] && [ "${ALLOW_DEV_COMPUTE:-}" != "1" ]; then
    cat >&2 <<EOF

-----------------------------------------------------------------------
  REFUSING TO RUN: /opt/abs-venv python on DEV droplet.
-----------------------------------------------------------------------

  Post-migration, /opt/abs-dashboard + /opt/abs-venv on this dev box
  are a ROLLBACK-ONLY copy (deleted at Phase 5 cleanup). Running
  compute here wastes CPU/RAM and writes to a dying directory.

  CORRECT: ssh $PROD_SSH_ALIAS /opt/abs-venv/bin/python $*
  OR:      ssh $PROD_SSH_ALIAS bash -lc "cd /opt/abs-dashboard && /opt/abs-venv/bin/python $*"

  If you genuinely need to run here (emergency debugging, testing
  the rollback copy), prefix with an override:
      ALLOW_DEV_COMPUTE=1 /opt/abs-venv/bin/python $*

  Logged to /var/log/heavy-dev-compute.log. Infra is notified.

-----------------------------------------------------------------------

EOF
    # Log the attempt so infra can see patterns
    {
        echo "[$(date -Iseconds)] REFUSED dev-python call"
        echo "  caller=$(ps -o comm= -p $PPID 2>/dev/null) pid=$PPID"
        echo "  args: $*"
        echo "  user: $(whoami) cwd: $(pwd)"
    } >> /var/log/heavy-dev-compute.log 2>&1
    exit 1
fi

# Allowed: either we're on prod (via a future copy) or override is set. Pass
# through to the real interpreter, preserving argv[0] so Python venv
# detection (pyvenv.cfg lookup) still works.
exec -a "$0" /usr/bin/python3 "$@"
