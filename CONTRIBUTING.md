# Contributing to ShowMe

ShowMe is a personal-use desktop terminal that ships as open source for
audit + reuse. External contributions are welcome but the architecture is
opinionated and the bar for accepted PRs is high.

## Easiest contributions

- **Indicator weights** — `backend/showme/mis.py` has hand-tuned per-market
  weights for the 23 indicators across 12 timeframes. PRs that adjust
  these with a quantified justification (out-of-sample performance on
  named datasets) are welcome.
- **Exchange adapters** — `ccxt` handles ~110 exchanges. If a specific one
  needs a wrapper for non-standard quirks, open an issue with the symptom
  and a fix proposal before sending a PR.
- **Theme presets** — the design-system tokens are in `ui/src/styles/`.
  PRs that add a coherent preset (5+ token overrides at minimum) are
  welcome; one-off color swaps are not.

## Code contributions

1. Fork and branch from `main`.
2. Backend: `pip install -e backend/[dev]` + `pytest backend/tests/`.
3. UI: `cd ui && npm install && npm run test` + `npm run lint`.
4. Native shell: `cd tauri && cargo check` (no need to build native
   for every PR; CI handles that).
5. The native macOS .app is rebuilt via `npm run build:native` from the
   repo root.
6. **Manifest contracts**: every pane displays a `📜 M` manifest dot +
   data-mode pill. Changes that alter data flow MUST update the manifest
   entry in `backend/showme/manifest/seeds/` — the strict-zero gate runs
   in CI and blocks PRs that surface unmanifested data.

## Out of scope

- Multi-platform builds (we will accept Win/Linux scaffolding under
  `tauri/` but the maintained build target is macOS ARM64).
- Hosted-API integrations that require paid keys without a degraded-mode
  fallback.

## Code of conduct

Be respectful, be specific, be brief. Disagreements are fine; insults are not.
