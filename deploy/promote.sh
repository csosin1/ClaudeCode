#!/bin/bash
# Promote a project's preview to live.
# Usage: promote.sh <landing|games|carvana|car-offers|gym-intelligence|timeshare-surveillance|all>
set -e

usage() {
    echo "Usage: $0 <landing|games|carvana|car-offers|gym-intelligence|timeshare-surveillance|all>" >&2
    exit 1
}

promote_static() {
    local name="$1" dir="$2"
    if [ ! -d "$dir/preview" ]; then
        echo "[$name] no preview dir at $dir/preview — skipping" >&2
        return 0
    fi
    rsync -a --delete "$dir/preview/" "$dir/live/"
    echo "[$name] promoted preview → live"
}

promote_service() {
    # rsync preview → live (code only; preserve live's state files), then restart live service
    local name="$1" preview_dir="$2" live_dir="$3" service="$4"
    shift 4
    local excludes=()
    for ex in "$@"; do excludes+=(--exclude="$ex"); done
    if [ ! -d "$preview_dir" ]; then
        echo "[$name] no preview dir at $preview_dir — skipping" >&2
        return 0
    fi
    rsync -a --delete "${excludes[@]}" "$preview_dir/" "$live_dir/"
    systemctl restart "$service"
    echo "[$name] promoted preview → live ($service restarted)"
}

promote_car_offers() {
    promote_service car-offers /opt/car-offers-preview /opt/car-offers car-offers.service \
        node_modules .env data startup-results.json .patchright_installed .playwright_installed '*.db'
}

promote_gym_intelligence() {
    promote_service gym-intelligence /opt/gym-intelligence-preview /opt/gym-intelligence gym-intelligence.service \
        venv .env '*.db' __pycache__
}

promote_timeshare_surveillance() {
    # Two services per instance — restart both live units after rsync.
    # Excludes preserve live's venv/.env/data (sqlite DB + state files).
    local preview=/opt/timeshare-surveillance-preview
    local live=/opt/timeshare-surveillance-live
    if [ ! -d "$preview" ]; then
        echo "[timeshare-surveillance] no preview dir at $preview — skipping" >&2
        return 0
    fi
    rsync -a --delete \
        --exclude=venv --exclude=.env --exclude=data --exclude=__pycache__ \
        --exclude='*.pyc' --exclude='*.log' --exclude='.deps_installed' \
        "$preview/" "$live/"
    systemctl restart timeshare-surveillance-watcher.service
    systemctl restart timeshare-surveillance-admin.service
    echo "[timeshare-surveillance] promoted preview → live (watcher + admin restarted)"
}

case "${1:-}" in
    landing)                 promote_static landing /var/www/landing ;;
    games)                   promote_static games   /var/www/games ;;
    carvana)                 promote_static carvana /var/www/carvana ;;
    car-offers)              promote_car_offers ;;
    gym-intelligence)        promote_gym_intelligence ;;
    timeshare-surveillance)  promote_timeshare_surveillance ;;
    all)
        promote_static landing /var/www/landing
        promote_static games   /var/www/games
        promote_static carvana /var/www/carvana
        promote_car_offers
        promote_gym_intelligence
        promote_timeshare_surveillance
        ;;
    ""|-h|--help) usage ;;
    *)
        echo "Unknown project: $1" >&2
        usage
        ;;
esac
