## Current Task
Name:              Dice Roller App
CLAUDE.md version: 1.0
Status:            deploying
Spec approved:     yes
Rollback tag:      [pending - set before deploy]

## Spec
SPEC: Dice Roller App
What will be built: A simple dice roller game — tap a button to roll 1-6,
  shows the result with a visual die face, and keeps a roll history below.
Success criteria:
  - Page loads at /games/dice-roller/ without JS errors
  - "Roll" button generates a number 1-6 on each click
  - Die face SVG/emoji updates to match the number
  - Roll history shows last 10 rolls
  - Works at 390px mobile viewport
  - All existing tests still pass (no regressions)
File location: games/dice-roller/index.html

## Builder Output
- Created games/dice-roller/index.html (single-file, inline CSS/JS)
- Added Playwright tests to tests/qa-smoke.spec.ts
- Updated CHANGES.md

## Reviewer Verdict
FAIL — missing link card on games/index.html
Orchestrator fixed: added card to games/index.html and updated deploy/landing.html

## QA Result
[pending — deploying now]

## Blockers
[none]

## Cost
Builder: ~23k tokens | Reviewer: ~24k tokens
