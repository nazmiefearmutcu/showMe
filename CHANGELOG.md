# Changelog

All notable changes to showMe are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **BTFW was not a walk-forward backtest.** `backtest_framework.py` was
  docstring'd "Walk-forward backtest framework", BTFW shipped
  `"methodology": "Single-symbol walk-forward backtest"` to the user, and the
  seed advertised a stitched out-of-sample equity curve — but `Backtest.run()`
  was a single in-sample pass with no train/test split anywhere. Real
  walk-forward is now implemented: sequential folds, parameters fitted on the
  train slice only, results reported from the test slices, a per-fold leakage
  tripwire, and worst-fold reporting.
- **BTFW's P&L was dimensionally wrong**, so every Sharpe / CAGR / Calmar /
  drawdown it reported was meaningless. Equity was marked as
  `cash += pos * (price - last_price)` — the P&L of one share — while the fee
  was charged on a ~$10,000 notional. Position size is now an explicit fraction
  of equity and both the mark and the fee use that same basis. Regression tests
  pin that a +1% move on a long is exactly +1% equity and that round-trip cost
  equals the configured bps on the notional actually traded. **Any BTFW result
  recorded before this change should be discarded.** BMTX and BTUNE share the
  engine and were equally affected.
- **CI had been red on every run.** The `rust` job died in `tauri_build::build()`
  on a resource glob pointing at a gitignored sidecar directory CI never builds;
  `npm ci` died on a `vitest` / `@vitest/coverage-v8` peer conflict left by an
  incomplete dependency bump; four backend tests depended on a third-party
  install present only on the author's machine, one made a live World Bank call,
  and one had hardcoded dates that aged past a 45-day freshness filter.
  `e2e-smoke` and `e2e-audit` had consequently never executed a single step.

### Changed
- BTFW now emits `oos_equity_curve`, `per_step_metrics` and an out-of-sample
  `summary` (including `worst_fold`) — the fields its manifest declared but the
  implementation never produced. `equity_curve` remains as an alias.
- BTFW's no-backtest path no longer reports invented metrics (it shipped a
  hardcoded `sharpe: 1.18`, `max_drawdown: -0.061`, `trades: 8`); the payload is
  now flagged as a placeholder with null metrics.
- BMTX and BTUNE state plainly that their rankings are in-sample.
- `no-undef` and `react-hooks/exhaustive-deps` re-enabled in the UI ESLint
  config, with the ambient-type and Node globals eslint was missing declared so
  the rules produce signal rather than noise.

## [0.1.1] — 2026-06-03

First release where the in-app version, the bundle/DMG version, and the
GitHub release tag are all aligned. (The `v0.1.0` cut shipped with an
internal `0.0.1` bundle version; this release fixes that mismatch.)

### Added
- **32 "garbage" stub functions converted to real keyless live data**, judged
  against each function's own info-button claim. Backend now sources real data
  from yfinance, SEC EDGAR/EFTS, US Treasury FiscalData, World Bank, IMF
  DataMapper, Binance, CoinGecko, mempool.space, Polymarket, NASA GIBS,
  Open-Meteo, FINRA, GDELT and FinBERT — returning honest `provider_unavailable`
  / empty on outage instead of fabricated constants.
- **9 bespoke React panes** wired into the renderer registry:
  CRPR, DEBT, IVOL, OVDV, MICRO, AIM, TCA, SAT, POLY.
- **showme-promo-video**: a Remotion (React/TS) promo-video project (source only;
  rendered media and `node_modules` are gitignored).

### Fixed
- **TCA**: pop `symbol` and `benchmark` from `inner_params` before calling
  `_execute_inner` (prevented a duplicate-argument failure).
- **Bots/portfolio**: corrected exit-fallback quantity matching, auto-heal of
  store ID ↔ filename mismatches, sizing-validation fixes, broker-connection
  leak on unregister, and preservation of `closed_trades_log` on PUT; tick
  interval is now auto-derived.
- **ECFC / SOSC / DARK / DPF / BRIEF / PVAR** data-source correctness fixes
  (IMF WAF bypass + ISO2→ISO3 map, GDELT query syntax + 429 backoff, fresh
  weekly FINRA ATS data, real dark-pool % from volume, composed briefings,
  real parametric VaR/ES).

### Changed
- **Performance**: `GP`/`HP` endpoints gained a `deep_history` parameter
  (default `False` under audit); `SPLC`/`BRIEF`/`ICX` timeouts tuned and
  redundant FinBERT batching removed to avoid function-quality audit timeouts;
  bond `DEBT` now fetches World Bank sovereign-debt exposures concurrently.
- Renamed `TRAN` → `TXNS` to avoid a namespace collision (code, tests, docs).
- Aligned RSI calculations with the negation pattern; added a `BotRecord`
  symbol-field validator and `StrategySpec.equals_approximately` tolerance
  validation (must be finite and positive).

### Security / Hardening
- Public-readiness pass: SSRF guard in `transcription.py`, file-read
  containment, and a clean semgrep + gitleaks scan over the change set.

### Maintenance
- Merged dependency updates across the Cargo and npm trees (multiple Dependabot
  PRs) and a repository-history cleanup pass.

### Tests
- 2133 backend tests green (0 fail / 9 skip) plus 28 new "de-garbage" test
  files; added `test_portfolio_route.py` covering the manual-close route and a
  root `test` script; UI typecheck clean.

[0.1.1]: https://github.com/nazmiefearmutcu/showMe/releases/tag/v0.1.1
[0.1.0]: https://github.com/nazmiefearmutcu/showMe/releases/tag/v0.1.0
