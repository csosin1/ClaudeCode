#!/bin/bash
# Deploy script for Carvana ABS Dashboard.
# Runs the generation pipeline (ingest → model → HTML/PDFs) on every push to main.
# Nginx serves from /opt/abs-dashboard/carvana_abs/static_site/{live,preview}/.
#
# Replaces the standalone /opt/auto_deploy.sh + auto-deploy.timer setup.
# Available variables from parent: $REPO_DIR, $LOG

PROJECT="carvana-abs"
SRC="/opt/abs-dashboard/carvana_abs"   # nginx aliases here; keep path stable
VENV="/opt/abs-venv"

# If source dir doesn't exist, nothing to do
if [ ! -d "$SRC" ]; then
    return 0 2>/dev/null || exit 0
fi

# If venv doesn't exist, deploy can't run — skip
if [ ! -x "$VENV/bin/python" ]; then
    echo "$(date): [carvana-abs] venv missing at $VENV — skipping" >> "$LOG"
    return 0 2>/dev/null || exit 0
fi

# weasyprint system deps (one-time)
if [ ! -f /opt/.weasyprint_deps_installed ]; then
    echo "$(date): [carvana-abs] Installing weasyprint system deps..." >> "$LOG"
    apt-get update -qq >> "$LOG" 2>&1 || true
    apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libcairo2 libffi-dev >> "$LOG" 2>&1 || true
    touch /opt/.weasyprint_deps_installed
fi

# Python deps if requirements changed
if [ "$SRC/requirements.txt" -nt /opt/.carvana_abs_deps ] 2>/dev/null; then
    "$VENV/bin/pip" install -q -r "$SRC/requirements.txt" >> "$LOG" 2>&1 || true
    touch /opt/.carvana_abs_deps
fi

# REINGEST (expensive — only when explicitly requested via deploy/REINGEST_VERSION)
if [ -f "$REPO_DIR/deploy/REINGEST_VERSION" ]; then
    NEED=$(cat "$REPO_DIR/deploy/REINGEST_VERSION")
    HAVE=$(cat /opt/.reingest_done 2>/dev/null || echo "none")
    if [ "$NEED" != "$HAVE" ]; then
        echo "$(date): [carvana-abs] Reingest v$NEED starting..." >> "$LOG"
        "$VENV/bin/python" "$SRC/reingest_pool.py" >> "$LOG" 2>&1 || true
        "$VENV/bin/python" "$SRC/rebuild_summaries.py" >> "$LOG" 2>&1 || true
        echo "$NEED" > /opt/.reingest_done
    fi
fi

# Generation pipeline (idempotent; always runs but typically fast)
"$VENV/bin/python" "$SRC/export_dashboard_db.py"   >> "$LOG" 2>&1 || true
"$VENV/bin/python" "$SRC/default_model.py"         >> "$LOG" 2>&1 || true
"$VENV/bin/python" "$SRC/generate_pdfs.py"         >> "$LOG" 2>&1 || true
"$VENV/bin/python" "$SRC/generate_preview.py"      >> "$LOG" 2>&1 || true

# Promote preview → live if flag present
if [ -f "$REPO_DIR/deploy/PROMOTE" ]; then
    "$VENV/bin/python" "$SRC/generate_preview.py" promote >> "$LOG" 2>&1 || true
    echo "$(date): [carvana-abs] promote flag honored." >> "$LOG"
fi

echo "$(date): [carvana-abs] deploy block done." >> "$LOG"
