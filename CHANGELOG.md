# Changelog

All notable changes to showMe are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **D phase: function truth audit fixes (branch `fix/foundation-audit`).** 626
  audited findings were fixed and verified across seven fix waves, and about 40
  more were fixed by hand afterwards. The full write-up is in
  `docs/audit/d-phase-delivery.md`. Main changes:
  - **The `/api/fn` route no longer overrides function defaults.** The agent
    probe profile (limit 6, 120 days, peer list, news query, 3 s fetch budget)
    used to replace each function's own defaults. The route now reports what it
    filled in as `routeDefaults`, and `inputEcho` shows only what the caller
    sent.
  - **No generated data anywhere.** CORR's reference series, WETR's
    "seasonal model" and TRA's template history were generated price and
    weather paths. They are gone, along with the panes' Ref, Modeled and MODEL
    switches.
  - **Honest states everywhere.**
    - Quotes without an exchange time are refused.
    - Previous-close checks use the exchange trade day.
    - A yield below the same-month UST average is not treated as a credit
      spread, so SRSK can no longer report a negative default probability.
    - FINRA and EIA data carry their own dates.
    - Error messages are never empty (about 250 sites).
    - Provider links become clickable only when they are http(s) URLs.
  - **New audit check and lower ratchets.** A new T10 offline-honesty audit is
    ratcheted at 0 red findings over 142 functions. The truth-audit ratchet went
    from 522 to 411.
- **FinBERT bear-listed contrarian headlines ("cycle bottom may already be
  in at $56K").** FinBERT scores the tone of the words, not the direction a
  headline argues for, so completed-bottom calls and fear-pivot headlines
  ("traders braced for a total wipeout but Bitcoin had other plans") landed
  in the CN/NI BEAR bucket — built from bear-market vocabulary ("bottom",
  a price anchor far below spot) despite making a bullish claim. A new
  deterministic corrector (`showme/contrarian.py`) now runs inside
  `stamp_items`: whitelisted completed-bottom / fear-pivot phrasings flip a
  neg verdict to pos with a score floored at 0.6 (clears the UI bull
  bucket), pos/neu rows are never touched, and flipped rows are visibly
  stamped `sentiment_model="finbert+contrarian"` + `sentiment_note` so a
  corrected row never masquerades as raw model output. All news handlers
  (CN, NI, TOP, BRIEF, SOSC, TSAR, instant) inherit the fix. Covered by
  `tests/test_finbert_contrarian.py`.
- **DES rendered empty placeholder cells instead of nothing.** When the
  provider had no fundamentals for an instrument (the owner's XAU/YHD run), the
  pane showed a seven-cell fundamentals strip of "—" cards, a Snapshot card
  full of "—" rows, and a "Provider did not return a business summary."
  dead-end — a wall of blank space. Metrics, snapshot rows and the summary card
  with no provider value are now omitted entirely; only real data renders (the
  crypto "∞" max-supply sentinel is preserved). The index branch behaves the
  same way when its bars are unavailable. Covered by
  `DES.missing-data.test.tsx`.
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
- **Repo-wide bug hunt (10 parallel audit agents + sequential fix waves).** A
  full-tree review of the Rust shell, the Python sidecar (server routes,
  engine core, data sources, all ~141 functions) and the React UI surfaced 171
  defects; ~145 are fixed in this change. Highlights, by severity: WebAuthn
  authentication is now verified server-side (it previously trusted a
  client-posted `{"ok": true}`, letting anyone authenticate as any user);
  Alpaca partial closes send `qty` as a query parameter (the JSON body was
  ignored, liquidating the whole position) and stored credentials are actually
  used, gated by their permissions. The BETA function no longer fabricates a
  seed-derived beta on provider failure — the fake value flowed into the
  WACC/DCF/DDM chain tagged "live"; the strict-zero gate was likewise restored
  across EE surprise scaling (×100 on small prints), CORR's synthetic series
  (dropped from the live matrix instead of mixed in), MAP/HVT fallback rows and
  the ASK briefing scanner (real scan instead of index-modulated fake
  signals). Paper-trading money paths were repaired: market orders without a
  price hint are rejected instead of filling at 0.0, position flips realize
  the closed leg, the duplicated entry fee is gone, and REBA no longer
  computes crypto liquidation quantity as notional/1. The sidecar's WS
  gap-fill no longer poisons the candle cache with out-of-order duplicates,
  StateStore writes are lock-protected (a write race could corrupt state.json
  and wipe all positions on restart), and the Rust shell gained
  char-boundary-safe log truncation (a >4 KB multi-byte message aborted the
  whole app), sidecar crash-restart with a shutdown flag (no orphaned
  processes holding the DuckDB lock), and window-state persistence on Cmd+Q.
  Blocking calls (Whisper, FinBERT, HF classify, PEOP, crypto-alias network
  resolution, Alpaca/IBKR SDK) moved off the event loop. Windows development
  got utf-8 catalog/store loaders, APPDATA-correct portfolio state and the
  NSIS bundle config. The UI gained chart symbol-swap state restoration with
  fetch-race guards, a readable custom light preset, UTC parsing for naive
  datetimes (news ordering was off by the local UTC offset), and the INSTANT
  squawk no longer lags one poll cycle behind the visual flash. Backend 3277,
  UI 3624 and Rust 25 tests green after the change.

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
