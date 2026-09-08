# DESIGN BRIEF — ShowMe "Desk Instrument" pass (FN design wave, 2026-09-08)

Read this FIRST. It is the binding aesthetic contract for all four design
lanes. The goal: the terminal should feel like a **precision trading-desk
instrument** — denser, flatter, sharper, numerically disciplined — without
becoming a generic SaaS dashboard or an AI-slop landing page.

## Identity (what ShowMe is)

A Bloomberg-style professional market terminal: 142 function panes, dense
data tables, live quotes, multi-monitor users who stare at it for hours.
The user is a trader/quant, not a consumer. Beauty here = **legibility,
density, stability, speed** — decoration is negative value.

## The seven laws (all lanes obey)

1. **Numbers first.** Every numeric cell/quote/stat renders with
   `font-variant-numeric: tabular-nums` and the mono stack
   (`var(--font-mono)`) so columns align. Units and labels dim
   (`--text-mute`/`--text-faint`), values stay full-contrast.
2. **Flat + hairline.** No soft box-shadows, no glows on containers. Depth =
   the existing surface ladder (`--surface/--surface-2-hex/--surface-3-hex`)
   plus 1px hairlines (`--line-thin/--line/--line-strong`). A card is a
   surface + hairline border, nothing else.
3. **Crisp geometry.** Data surfaces: `var(--radius-sm)` (4px) max.
   Controls: 2–4px. The only round things: pills (fully rounded) and the
   OrbitMark logo. Kill any radius > 8px in your zone.
4. **Accent discipline.** `--accent` = interactive, focus, selection ONLY.
   Data color = `--positive-hex`/`--negative-hex`. If a gradient exists on a
   container that is not a chart, delete it.
5. **Motion is feedback, not decoration.** 90ms (micro: hover/press) and
   140ms (panel/expand) ease-out transitions on STATE CHANGE only. No
   entrance/fade-in/slide-up animations anywhere. Wrap all new transitions
   in `@media (prefers-reduced-motion: no-preference)`.
6. **Density is a feature.** Tighten one space-step: pane headers
   `--space-5`→`--space-4` padding where safe, row heights 28px→24–26px,
   titlebar/panels trimmed. Never below 24px interactive hit targets.
7. **A11y floor (non-negotiable).** Visible `:focus-visible` ring (accent,
   2px, 2px offset) on EVERY interactive element in your zone; WCAG AA
   contrast on all six presets; `aria-label`s preserved — never remove
   existing accessibility to make something prettier.

## Anti-slop checklist (all forbidden in your zone)

- soft `rgba(0,0,0,.1)` shadows; gradient washes on containers
- entrance animations, hover lift-and-shadow combos
- ALL-CAPS eyebrow labels added above content
- decorative em-dashes / middle dots joining meta strings (existing data
  metadata keeps its format)
- rounded-everything (one radius per hierarchy level, from the scale)
- new colors outside the token system

## Mechanics

- Your zone's CSS additions go in YOUR new stylesheet only
  (`shell.css` / `components.css` / `workspace.css` / tokens.css+`motion.css`).
  NEVER edit `index.css` or another lane's files.
- Consume EXISTING tokens; if you need a missing token, note it in your
  progress file instead of inventing one (Lane C owns token additions).
- TSX changes: class hooks, density (token paddings), aria fixes, tabular
  numerics — do NOT rename exports/props or restructure component APIs.
- Tests: visual-only changes should not break them. If a test pins a
  visual detail you intentionally changed, update it minimally and list it.
- Gates: `npx tsc --noEmit` 0 (your files), `npx eslint <your files>
  --ext ts,tsx --max-warnings 0` 0, scoped vitest green.
