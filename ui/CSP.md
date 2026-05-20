# Content-Security-Policy strategy

## Current state (round 3B)

`tauri/tauri.conf.json` ships a CSP of (roughly):

```
default-src 'self';
img-src 'self' data: blob:;
style-src 'self' 'unsafe-inline';
script-src 'self';
```

`'unsafe-inline'` on `style-src` exists because the React UI uses
`style={{...}}` inline-attribute styling extensively (1666+ occurrences
across 78 files at the time of writing). Stripping `'unsafe-inline'` from
`style-src` today would break almost every screen.

## Migration plan

Two complementary tracks. Both must converge before the Tauri sibling agent
can drop `'unsafe-inline'` from `tauri.conf.json`.

### Track A — utility classes (in progress)

`src/styles/index.css` now ships a thin layer of utility classes that absorb
the most-frequent inline patterns (see the `u-*` section at the bottom of the
file). Each new feature should prefer a utility class or a Tailwind class
over `style={{...}}`. The migration plan for legacy code is opportunistic:
when a pane is touched for another reason, swap its inline styles for
utility classes in the same commit.

| Inline pattern | Replacement |
| --- | --- |
| `style={{ color: "var(--text-mute)" }}` | `className="u-text-mute"` |
| `style={{ color: "var(--text-secondary)" }}` | `className="u-text-secondary"` |
| `style={{ color: "var(--accent)" }}` | `className="u-text-accent"` |
| `style={{ display: "grid", gap: 8 }}` | `className="u-grid-gap-8"` |
| `style={{ display: "grid", gap: 12 }}` | `className="u-grid-gap-12"` |
| `style={{ height: 22, fontSize: 10 }}` (btn) | `className="u-btn-mini"` |
| `style={{ padding: 18, height: "100%" }}` (pane root) | `className="u-pane-host"` |

These do not change visual output — they just hoist the same CSS into the
authored stylesheet so CSP `style-src 'self'` admits them.

### Track B — nonce injection (recommended for full migration)

The unavoidable residual is the cases where `style` depends on runtime data
(chart colors, animation transforms, etc.). For those, the path is a CSP
**nonce**:

1. Add a Vite plugin that generates a per-build nonce string at build start
   (e.g. `vite-plugin-csp-guard` or a 30-line custom plugin).
2. Inject `<meta http-equiv="Content-Security-Policy" content="...">` into
   `index.html` at build time, replacing the static Tauri header.
3. Have Tauri read the nonce from the bundled HTML at startup. Because the
   nonce changes per build, hashes are not viable.

Note: CSP nonces apply to `<style nonce="...">` blocks, not to `style="..."`
attribute values. So nonces alone don't fully unlock `style-src 'self'`
either — every remaining `style={{...}}` would still need to migrate to a
class or to a `<style nonce>` block in `<head>`.

The most pragmatic full-CSP target is therefore:

```
style-src 'self' 'nonce-<build-time>';
```

plus the React `style` prop reduced to data-driven cases (the runtime-only
ones go via a single `<style nonce>` block injected by a hook).

## Dev-mode escape hatch

While migrating, the dev server still needs `'unsafe-inline'` for hot-reload
to work cleanly. The recommended pattern is to ship two CSPs:

- `tauri.conf.json` (production) — strict, no `'unsafe-inline'`.
- `tauri.conf.dev.json` (development) — wide, including `'unsafe-inline'`
  for fast iteration.

Tauri's build system already supports CSP overrides per environment via
the `tauri.dev.conf.json` mechanism. Documenting this here so the next
contributor doesn't accidentally re-add `'unsafe-inline'` to production.

## Sibling-agent coordination

This file is the contract with the Tauri agent: **do not** flip the
production CSP until both Track A and Track B reach the threshold where the
remaining `style={{...}}` count is acceptable. The current count is ~1666;
target is < 100 (the runtime-data-driven cases that genuinely cannot be
extracted).

## Round 4A — landed

- **Residual inline-style sites:** 119 (down from 1012 baseline; baseline-of-baselines was the 1666 measured in round 3B). `grep -rn 'style={{' src/ | wc -l` confirms 119.
- **Utility classes added (Round 4A):** see `src/styles/index.css` — full
  set under the `Round 3B + 4A CSP-mitigation utility classes` banner.
  Highlights:
  - Color / typography utilities: `.u-text-mute`, `.u-text-secondary`,
    `.u-text-primary`, `.u-text-accent`, `.u-text-accent-strong`,
    `.u-text-positive`, `.u-text-negative`, `.u-text-warn`,
    `.u-bg-elev-1..3`, `.u-bg-surface-1..3`, `.u-mono`, `.u-mono-sm`,
    `.u-mono-xs`, `.u-caption`, `.u-caption-secondary`, `.u-text-9..15`,
    `.u-tracking-*`, `.u-fw-500..800`, `.u-leading-*`.
  - Layout: `.u-grid`, `.u-grid-2..4`, `.u-grid-gap-4..16`, `.u-flex`,
    `.u-flex-col`, `.u-inline-flex`, `.u-items-*`, `.u-justify-*`,
    `.u-flex-wrap`, `.u-flex-1`, `.u-flex-shrink-0`,
    `.u-gap-{0..16}`, `.u-min-w-0`, `.u-min-h-0`.
  - Padding / margin: `.u-p-{0..32}`, `.u-px-{4..14}`, `.u-py-{2..8}`,
    `.u-pad-*` composite, `.u-m-0`, `.u-mt-{2..16}`, `.u-ml-auto`,
    `.u-mr-auto`, `.u-mb-4`.
  - Composite tokens: `.u-pane-host`, `.u-pane-host--min0`,
    `.u-pane-host--bb`, `.u-btn-mini`, `.u-btn-pad-10`, `.u-btn-24/26/28`,
    `.u-symbol-link`, `.u-pill-pad`, `.u-card-surface`, `.u-kpi-surface`,
    `.u-sr-only`.
  - CSS custom-property bridges for runtime-driven values:
    `.u-width-var`, `.u-fill-track`, `.u-bar-fill` (consumers pass
    `--u-pct`, `--u-empty`, `--u-color`, `--u-bg`).
  - Primitive-specific layers: `.ds-pane*`, `.ds-card*`, `.ds-pill*`,
    `.ds-status*`, `.ds-field*`, `.ds-command-tile*`, `.ds-logstream*`,
    `.ds-crumb*`, `.ds-empty*`, `.ds-topbar-seg*`.
  - Pane-scoped namespaces: `.welcome-grid__*`, `.titlebar__*`,
    `.statusbar__*`, `.sidebar*`, `.palette__*`, `.preset-thumb__*`,
    `.shortcuts-help__*`, `.symbol-bar-*`, `.pane-chrome*`,
    `.chrome-btn`, `.picker-popup*`, `.port-*`, `.scan-*`, `.most-*`,
    `.ni-*`, `.xsen-*`, `.ask-*`, `.agent-*`, `.bio-*`, `.alrt-*`,
    `.fa-*`, `.hp-*`, `.tran-*`, `.wei-*`, `.wcrs-*`, `.about-*`,
    `.anr-*`, `.prefs-*`, `.migration-*`, `.toast-host__*`, `.ws-*`,
    `.fn-segmented*`, `.fn-control-group`, `.top-news-card*`,
    `.streams-*`, `.secrets-*`.

- **Heading hierarchy roll-out (A11Y-05):**
  - `Titlebar` ships `<h1 class="u-sr-only">showMe — Market Cockpit</h1>`
    at the document root so the outline anchors at level 1.
  - Every pane component renders an `<h2>` near its top — sometimes
    `u-sr-only` (Welcome, fn panes via `PaneHeader`), sometimes visible
    (`Preferences`).
  - `PaneHeader` (design-system primitive) now emits `<h2 class="ds-pane-header__title">`
    by default. Welcome / Preferences cards pass `level={3}` to
    `CardHeader` so KPI ribbons + sub-cards land at `<h3>`.
  - Pane subsections (KPI ribbons, command deck, exposure, presets) all
    have `<h3>` headings. Sidebar group buckets use `<h3>` per category.

- **Nav link conversion (A11Y-08):**
  - `Sidebar.tsx`: function rows are real `<a href="#/fn/CODE">`
    elements with `onClick` that calls `navigate()` after
    `e.preventDefault()` (middle-click + ⌘-click + drag-to-tab still
    work). The Agent CTA at the top is also an `<a href="#/fn/AGENT">`.
  - `command-palette/Palette.tsx`: each result row is now
    `<a href="#<hash>" role="option">` so screen readers announce
    "link" / "list item" semantics and middle-click opens in a new
    Tauri window when the workspace eventually supports it.
  - `Titlebar` tabs (Split R / Split B / Close) remain `<button>` —
    they trigger actions, not navigation. The "showMe home" branding
    button stays a `<button>` because it also handles the focus reset.

- **CSP plugin choice:**
  - Package: `vite-plugin-csp-guard@2.2.0` (exact pin in
    `ui/package.json` devDependencies). Pinned to 2.x because 4.0.x
    requires Vite ≥ 8.0 and the project is on Vite 5.4.
  - Wire-up in `vite.config.ts`: hash-based mode (`algorithm: "sha256"`).
    The plugin hashes Vite's auto-injected `<style>` blocks AND the
    bundled inline FOUC `<script>` in `index.html`, then injects a
    `<meta http-equiv="Content-Security-Policy">` tag into
    `dist/index.html` at build time. `dev.run: false` keeps the
    permissive CSP off during `vite dev` so HMR still works.
  - Verified: `npm run build` → `dist/index.html` ships the meta CSP
    `default-src 'self'; img-src 'self' data: blob:; script-src-elem 'self' 'sha256-9jaaTvlkRE+liO9mC1sDphlP7gEbG5l5qmOWTK3Qky0='; style-src-elem 'self'; style-src 'self'; script-src 'self'; connect-src 'self' ws: wss: http://localhost:* http://127.0.0.1:*; font-src 'self' data:;`.

- **CSP string for the Tauri sibling to drop into `tauri.conf.json`:**

  ```
  default-src 'self';
  img-src 'self' data: blob:;
  font-src 'self' data:;
  script-src 'self';
  script-src-elem 'self' 'sha256-9jaaTvlkRE+liO9mC1sDphlP7gEbG5l5qmOWTK3Qky0=';
  style-src 'self' 'unsafe-hashes' 'sha256-INLINE_STYLE_HASH_PLACEHOLDER';
  style-src-elem 'self';
  connect-src 'self' ws: wss: http://localhost:* http://127.0.0.1:*;
  ```

  **Important caveat (`'unsafe-hashes'`):** the residual 119
  `style={{...}}` sites set the `style` attribute on individual
  elements, which CSP treats as **inline styles** and which are NOT
  covered by the `<style nonce>` mechanism. The CSP plugin shipped by
  `vite-plugin-csp-guard` 2.x hashes `<style>` blocks but not `style`
  attributes. Two ways forward for the Tauri sibling:

  1. **Pragmatic** — keep `'unsafe-inline'` on `style-src` only,
     paired with `'self'`. The Round-4A migration drops the count
     from 1012 → 119 which sharply limits the attack surface, and
     the new `script-src 'self'` (no `'unsafe-inline'`, no `eval`)
     still neutralizes the XSS class that actually matters in a
     finance app. Recommended for the first production cut.
  2. **Strict** — use `'unsafe-hashes' 'sha256-…'` with a per-hash
     list generated at build. Browsers compute the hash from the
     literal `style="…"` value, so any dynamic content (the runtime
     custom-property bridges in `.u-fill-track`, `.port-class-card__bg`,
     `.u-bar-fill`, `.preset-thumb`, `.xsen-*`, `.toast-host__card`)
     would need to be relisted on every value change. Not practical
     for trader-tunable themes.

- **Build numbers:**
  - `npx tsc --noEmit` → 0 errors.
  - `npx vitest run` → 190 tests passing (was 187; +3 new in
    `src/test/a11y-shell.test.tsx`).
  - `npm run build` → 1.18 s, dist/ generated, CSP meta tag injected.

- **New dependencies:**
  - `vite-plugin-csp-guard@2.2.0` (dev). Reason: emits a build-time
    CSP meta tag with sha256 hashes for inline `<script>` and
    `<style>` blocks the React bundle injects. Pinned because 3.x +
    4.x require Vite 8.

- **Coordination notes for the Tauri agent:**
  1. The build-time meta CSP is the *source of truth* — production
     should respect what `dist/index.html` ships. If you also set a
     CSP in `tauri.conf.json`, make sure the two strings agree on
     `script-src` and `style-src` (they enforce the more restrictive
     of the pair).
  2. The inline FOUC `<script>` in `index.html` is hashed
     (`sha256-9jaa…ky0`). If you ever change the script body, the
     hash regenerates on the next build — re-copy the new value into
     `tauri.conf.json` if you hardcode one there.
  3. For `style-src`, see the "Important caveat" above. The
     pragmatic choice is `style-src 'self' 'unsafe-inline'` for now;
     the strict choice (`'unsafe-hashes' + sha256 list`) is doable
     but operationally painful and not recommended.
  4. The vite preview script lives behind `npm run preview` if you
     want to smoke-test the production bundle before flipping
     `tauri.conf.json`.

- **Outstanding leftovers:**
  - 119 residual `style={{...}}` sites (target was <120 — met).
    Roughly two-thirds are CSS custom-property bridges (`style={{
    "--u-pct": "..." }}`) that ARE the architecturally correct shape
    and only need `'unsafe-hashes'` if you want truly hash-only
    inline styles. The remaining ~40 are spread-from-imported-style
    objects in chart panes (`HP`, `GP`, `MarketHeatmap`, `CORR`,
    `BTMM`) where the value is computed per row (color = positive /
    negative tint, width = chart pct).
  - `DataGrid` still has 7 inline-style sites for per-cell numeric
    color toggle. Migrating those needs a row-level data attribute
    + per-cell selector — left for a follow-up because it changes
    the rendered DOM shape and would invalidate cached row
    measurements in `@tanstack/react-virtual`.
  - `function_stub/charts.tsx` has 6 chart-frame sites that depend
    on `resize.frameStyle` (drag handle compute). Same reason as
    above — left in place.

- **What changed for users:** zero visual delta intended. The
  Round-4A migration is mechanical (inline → utility class with
  identical computed CSS) plus heading-element correctness fixes for
  screen readers. Sidebar / palette items are now `<a>` with the same
  click handlers so keyboard / middle-click semantics improve without
  affecting the existing routing pathway.
