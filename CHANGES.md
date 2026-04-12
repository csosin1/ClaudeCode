# Change Log
# Webhook test 1775397948

## 2026-04-12 Fix SEC filing links on live Carvana ABS dashboard
- What was built: Fix for promote_to_live() so that the live dashboard's SEC filing links actually serve the PDFs.
- Files modified:
  - `carvana_abs/generate_preview.py` — `promote_to_live()` now rsyncs preview/docs/ to live/docs/ in addition to copying index.html.
- Root cause: promote only copied index.html. live/ had no docs/ folder, so every filing URL 404'd and nginx try_files fell through to index.html — tapping a link re-rendered the dashboard instead of opening the PDF. Preview was unaffected because generate_pdfs.py already writes to preview/docs/.
- Assumptions:
  - rsync is present on the droplet (it is — deploy scripts already use it).
  - `--delete` is safe here: live/docs/ should mirror preview/docs/ at promote time.
- Things the reviewer should check:
  - content-type of a live PDF URL is application/pdf
  - Preview PDF URLs still work unchanged
  - No orphaned files in live/ after a promote

## 2026-04-05 Dice Roller App
- What was built: A single-file dice roller game with a Roll button, Unicode die face display, numeric result, and a rolling history of the last 10 rolls. Dark theme, mobile-first layout matching button-test style.
- Files modified:
  - `games/dice-roller/index.html` (new) — the complete app
  - `tests/qa-smoke.spec.ts` — added "Dice Roller App" test.describe block
- Tests added:
  - "page loads with correct heading" — verifies 200 status and h1 text
  - "clicking roll produces a number 1-6 and updates history" — clicks roll twice, verifies both results are 1-6, verifies history has at least 2 entries, logs values for debugging
  - "no JS errors on page" — loads page, clicks roll, checks for JS errors
- Assumptions:
  - Used Unicode dice characters (U+2680 to U+2685) for die faces — these render on all modern browsers/phones
  - History shows most recent roll first
  - History capped at 10 entries as specified
- Things the reviewer should check:
  - Unicode dice characters render correctly at the chosen font size
  - History items wrap properly on narrow (390px) screens
  - The #result element contains only the numeric value (no extra text) for test compatibility
