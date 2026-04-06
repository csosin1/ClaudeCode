## Current Task
Name:              Deploy Gym Intelligence Tool to Droplet
CLAUDE.md version: 1.0
Status:            building
Spec approved:     yes
Rollback tag:      (not yet — set before deploy)
Resume hint:       Builder is writing CHANGES.md proposals and app tweaks for droplet deployment. Infrastructure changes need infra chat.

## Spec
Deploy the gym-intelligence Streamlit app to the droplet as a persistent process.
- Accessible at http://159.223.127.125/gym-intelligence/
- Landing page link card
- ANTHROPIC_API_KEY via /setup web page in the app
- systemd + venv on the droplet
- nginx reverse proxy with WebSocket support

## Builder Output
- Modified `gym-intelligence/app.py`: added baseUrlPath docstring, default-to-Setup-page when API key missing
- Appended full infrastructure proposals to `CHANGES.md` covering: deploy script (venv + systemd), nginx (WebSocket proxy), landing page card, QA tests
- All infra changes use lessons learned: absolute paths in systemd, verify-before-flag, fast sync first, lazy deps

## Reviewer Verdict
(pending)

## QA Result
(pending)

## Blockers
None yet

## Cost
(tracking)
