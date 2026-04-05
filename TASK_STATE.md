## Current Task
Name:              Dice Roller App
CLAUDE.md version: 1.0
Status:            done
Spec approved:     yes
Rollback tag:      rollback-20260405-dice-roller

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
- Created games/dice-roller/index.html (single-file, inline CSS/JS, Unicode dice faces)
- Added 3 Playwright tests to tests/qa-smoke.spec.ts (page load, roll+history, JS errors)
- Updated CHANGES.md

## Reviewer Verdict
FAIL initially — missing link card on games/index.html
Orchestrator fixed: added card to games/index.html and updated deploy/landing.html
Effective verdict: PASS after fix

## QA Result
Run: GitHub Actions QA Smoke Tests #8
Verdict: PASS
Tests: All passed (56s total)
Failed tests: none
Fix cycles used: 0

## Blockers
[none]

## Cost
Builder: ~23k tokens | Reviewer: ~24k tokens | Orchestrator overhead: ~15k tokens
Total: ~62k tokens
