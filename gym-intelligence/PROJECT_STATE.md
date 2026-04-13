# gym-intelligence — Project State

_Last updated: 2026-04-13 by gym-intelligence session_

## Current focus
Idle. Last completed work (2026-04-12): added `MIN_LOCATIONS_FOR_CLASSIFICATION = 4` floor to `classify.py` (commit c412728) so refreshes only spend Claude tokens on chains that actually move Basic-Fit's competitive landscape, not the ~31k OSM single-location noise.

## Last decisions
- **Classification floor = 4 locations.** Pre-floor, the classifier matched all ~31k unclassified chains per refresh (~$220, 17+ hrs). Floor of 4 covers ~22% of clubs across 391 chains for ~$3. Set in `classify.py:19`.
- **Flask + vanilla JS, not Streamlit.** Mobile-first single-page dashboard at `/gym-intelligence/`. Streamlit was replaced (commit ee243ee) for fast iPhone loads.
- **Preview-first deploy retrofit.** Live (port 8502) and preview (port 8503) are separate systemd units sharing source from `/opt/site-deploy/gym-intelligence/`; live is only updated via `deploy/promote.sh gym-intelligence`.

## Open questions
- **145 chains with ≥4 locations remain `competitive_classification = 'unknown'`.** Did the prior pass leave them unknown because Claude couldn't decide, or because the run was interrupted? Re-run on these specific IDs would be cheap (<$0.50) before deciding whether to widen the prompt or mark them manually.
- **Preview is drifted from source.** Source `classify.py` (Apr 13, has the floor) hasn't been rsynced to `/opt/gym-intelligence-preview/classify.py` (still Apr 6 content) — no `gym-intelligence.sh` deploy has run since 2026-04-12 19:30 per `/var/log/general-deploy.log`. Looks like an auto-deploy infra issue (deployed `/opt/auto_deploy_general.sh` is older than the repo copy). Out of scope for this project chat to fix; flagged in CHANGES.md.

## Next step
Await user request. If they ask to act on the preview drift, run `REPO_DIR=/opt/site-deploy LOG=/tmp/gym-deploy.log bash /opt/site-deploy/deploy/gym-intelligence.sh` to manually sync preview, then verify  http://159.223.127.125/gym-intelligence/preview/  serves the new code.
