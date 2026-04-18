---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Dual-Surface Parity — mobile-first AND desktop

## When to use

Any time you design, build, or review a user-facing surface — dashboards, Accept cards, landing pages, forms, project UIs. Mobile-first is the stated priority, but desktop is not a degraded fallback; both surfaces are first-class and both must render cleanly. This is a design-time requirement, not just a test-time check: `SKILLS/visual-lint.md` + the visual-reviewer agent already enforce at test time, but catching a surface that was never designed for desktop at review time is much cheaper than at QA time.

## The two surfaces

### Mobile (390px — iPhone default)

- Thumb-reachable primary actions. Accept / Ship / Cancel buttons sit in the bottom half of the viewport, not the top nav.
- Tap targets ≥44px square (Apple HIG). Buttons packed too tight mis-fire.
- **URLs plain in message text**, never wrapped in markdown or backticks — iOS URL detection grabs surrounding characters and produces 404s. This is also a CLAUDE.md rule; reinforcing because it shows up constantly on the mobile surface.
- No hover-only affordances. Tooltips, hover-to-reveal menus, and "hover for details" patterns are invisible on touch.
- Horizontal scroll is a failure mode. Use `overflow-x: hidden` on the root where appropriate; never rely on the user to scroll sideways to find a button.

### Desktop (1280px — typical MacBook)

- Keyboard equivalents for every primary action. `Enter` → Accept, `Esc` → Cancel, single-key shortcuts where sensible. A desktop user should never need the mouse for the common path.
- Wider layouts where it adds information density. Don't artificially squeeze content into a 390px column on a 1280px screen — use the space for side-by-side comparisons, multi-column summaries, or expanded detail.
- Accept-card-style pages render the full context without abbreviation; mobile compresses context into an expandable detail block, desktop shows it inline.
- No mobile-only font sizing (14px-everywhere locks desktop readability down unnecessarily).

## Accept cards specifically

Emitted by `helpers/accept-card.sh`, rendered at `https://casinv.dev/accept-cards/<id>.html`. The card is the most-common dual-surface artifact, so it sets the bar:

- **Mobile**: title + outcome readable without scroll; Accept / Retry / Cancel buttons in the bottom third; tap targets ≥44px; context_link opens full diff in-app.
- **Desktop**: same card, wider (max-width ~720px), keyboard-navigable (Tab through buttons, Enter = Accept, Esc = Cancel), context inlined where it fits.
- **Both**: no hover-only affordances; no markdown-wrapped URLs in rendered text; page persists so a dormant user can return days later and still act.

## Enforcement

- **Design review.** Any PR introducing a new user-facing surface must explicitly state how it renders at 390px AND 1280px. A surface that only has a mobile screenshot, or only a desktop screenshot, is incomplete.
- **Visual-lint tests.** `SKILLS/visual-lint.md` runs Playwright at both viewports; regressions count as QA failures. This is the test-time backstop.
- **Visual-reviewer agent.** Reads screenshots at both viewports; catches "desktop squeeze" and "mobile overflow" as the two recurring anti-patterns.

## Anti-patterns

- **Mobile squeeze on desktop.** Content locked to a 390px column on a 1280px viewport with vast white margins. Use the space.
- **Desktop-first with mobile afterthought.** Design that only works above some min-width and falls apart on iPhone. Flip the build order — mobile first.
- **Hover-only affordances.** Info-on-hover is invisible to touch. Make it tap-visible or inline.
- **URLs in markdown on mobile.** iOS tap target grabs `**` or backticks and produces 404s. Always plain URLs with whitespace on either side.

## Related

- `SKILLS/visual-lint.md` — the Playwright + axe dual-viewport check.
- `SKILLS/acceptance-rehearsal.md` — narrative walk-through consumer of user journeys.
- `SKILLS/walkaway-invariants.md` — why Accept cards must persist on both surfaces.
- `SKILLS/notification-tiers.md` — the ntfy tier that points users at a rendered card.
- `helpers/accept-card.sh` — the emitter.
