#!/bin/bash
# Promote a project's preview to live (rsync preview/ → live/).
# Usage: promote.sh <project>
#   <project>: landing | games | carvana | all
#
# Services (car-offers, gym-intelligence) are not yet preview-enabled;
# their promotion is handled by their own deploy scripts until retrofitted.
set -e

usage() {
    echo "Usage: $0 <landing|games|carvana|all>" >&2
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

case "${1:-}" in
    landing) promote_static landing /var/www/landing ;;
    games)   promote_static games   /var/www/games ;;
    carvana) promote_static carvana /var/www/carvana ;;
    all)
        promote_static landing /var/www/landing
        promote_static games   /var/www/games
        promote_static carvana /var/www/carvana
        ;;
    ""|-h|--help) usage ;;
    *)
        echo "Unknown project: $1" >&2
        usage
        ;;
esac
