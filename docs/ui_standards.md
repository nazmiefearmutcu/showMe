# showMe — UI Standards

Living document. Every Round adds rules, never silently relaxes them.

## 1. Window chrome

* Custom titlebar — `titleBarStyle: "Overlay"`, `hiddenTitle: true`.
* Traffic lights at `(14, 18)` logical px.
* `app-region: drag` on the entire titlebar; everything interactive
  (buttons, palette trigger, status pills) opts out via `.interactive`.
* `windowEffects: ["sidebar", "underWindowBackground"]` for vibrancy.

## 2. Color tokens

Defined in `src-ui/src/styles/tokens.css`. Components read via Tailwind
indirection, never hardcoded hex.

| Token              | Dark      | Use                                        |
| ------------------ | --------- | ------------------------------------------ |
| `--bg-base`        | `#07080a` | window background under vibrancy           |
| `--bg-elev-1`      | `#0f1115` | panel surface                              |
| `--bg-elev-2`      | `#161922` | card / hover                               |
| `--bg-elev-3`      | `#1d2230` | active / pressed                           |
| `--accent`         | `#ff7a00` | Bloomberg orange — sparingly               |
| `--positive`       | `#00d183` | gain                                       |
| `--negative`       | `#ff3b58` | loss / error                               |
| `--neutral`        | `#a0a4ab` | flat / muted state                         |
| `--text-primary`   | `#f0f2f5` | body                                       |
| `--text-secondary` | `#8e94a0` | label                                      |
| `--text-mute`      | `#5a6070` | hint                                       |

Light mode mirrors this set. Default is dark.

## 3. Typography

* UI: SF Pro Text / SF Pro Display (system default).
* Numerics & code: JetBrains Mono / SF Mono. Never proportional digits.
* Sizes: 11 / 13 / 15 / 17 / 22 / 28 px. **No** sub-10 px text in panes.
* `font-variant-numeric: tabular-nums` on every cell that holds money.

## 4. Motion

| Surface                      | Duration | Curve                          |
| ---------------------------- | -------- | ------------------------------ |
| Pane swap, modal open/close  | 180 ms   | `cubic-bezier(0.2,0.8,0.2,1)`  |
| Hover, focus ring            | 80 ms    | same                           |
| Streaming value flash        | 220 ms   | ease-out                       |

No bounce, no spring. A trader app never overshoots.

## 5. Sound

* `NSSound` system file for alerts (Airbus tone preserved from ShowMe).
* Position close → short blip.
* Error → `NSAlert` default ding.
* Settings toggle: master mute + per-channel mute.

## 6. Forbidden list (zero tolerance)

* Browser default scrollbar.
* Default `<select>` chrome.
* `outline: auto` focus ring.
* `alert()` / `confirm()`.
* Browser context menu — `contextmenu` event prevented in `main.tsx`.

## 7. Component recipes

* **Status pill** — uppercase 10 px / letter-spacing 0.08em / 18 px tall /
  small dot with currentColor + box-shadow glow.
* **Button** — `--bg-elev-2` default, `--bg-elev-3` hover, accent variant
  for primary CTA only.
* **Keyboard hint** — `<span class="kbd">⌘K</span>` — 10 px mono in
  `--bg-elev-2` chip with strong border.

## 8. Round-by-round addenda

* **Round 12** (current) — design tokens locked, titlebar / sidebar /
  statusbar / palette shipped, sidecar status pill convention introduced.
* **Round 13** — design-system primitives (`Card`, `Toolbar`, `Pane`,
  `Tabs`, `Crumb`).
* **Round 14** — first 5 function panes (DES / FA / GP/TECH / EQS / PORT)
  applied + screenshot-pinned in `docs/round_notes/14.md`.
* **Round 15** — GoldenLayout multi-pane standard.
