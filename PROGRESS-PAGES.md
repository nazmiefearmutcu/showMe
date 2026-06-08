# ShowMe — Page-by-Page Development Progress

Ralph-driven, one page per iteration. Plan: `docs/superpowers/plans/2026-06-08-page-by-page-development.md`.

| # | Code | Page | Status | Notes |
|---|------|------|--------|-------|
| 1 | HOME | Overview | ✅ done | live movers (live:true), BRIEF wired + honest demo fallback, aria-labels + role=status, div role=row (a11y fix), tabular-nums, centralized formatters; 78 tests pass. commit 749a156 |
| 2 | WATCH | Live Watchlist | ✅ done | stable-node live pulse restart (no jitter+flash), Volume/Notional cols (real snapshot.volume, honest —), aria-labels + role=status/alert, terminal-grid-numeric, compact sparkline; all WATCH tests pass. commits 1f9c79d+de4f597 |
| 3 | PORT | Portfolio | ✅ done | broker positions surfaced in main view (frontend merge, real asset_class), crypto live quotes (backend), honest return badge (replaced fake sparkline), DRY formatters + terminal-grid-numeric, sorting + aria; UI 20 + backend 132 tests pass. commits 269becb+bc32a21 |
| 4 | WEI | Macro Monitor | ✅ done | world indices 11→31 (all regions, EM; single source of truth + baseline-drift guard), real as_of freshness, "Model data" badge + honest de-emphasized synthetic sparklines, fixed false Degraded banner, format.ts+terminal-grid-numeric, sorting + a11y + responsive KPI; UI 9 + backend 87 tests pass. commit ee1e2ca |
| 5 | NI | News Desk | ✅ done | honest states (provider-unavailable → error banner not fake cards; removed ~290 lines of fake "pipeline log" animation → honest loader); headlines unblocked from async Veryfinder; keyboard-nav + list semantics + aria-labels + line-clamp headlines; data is real (RSS/GDELT/FinBERT/Veryfinder). UI 10 tests pass. commits 3d3f4c7+24e905b |
| 6 | SCAN | All Functions | ✅ done | NOTE: SCAN is a TRADING SCANNER (not a function catalog). Removed synthetic per-row "Trend" sparkline (honesty); fixed dbl-click double-fire + Reset&retry stale-closure + Long/Short color collision; keyboard a11y (focus-visible/cursor, Enter→DES launch, aria-labels), empty/error Retry, mono/CSS-class polish; scanner data confirmed REAL (no stub). NEW SCAN.test.tsx 11 tests. commits 227cfec+936207c |
| 7 | MIS | Multi Indicator Scan | ✅ done | data verified REAL (23 indicators on real multi-TF OHLCV, no stub); added indicator drill-down (inline expandable, useSyncExternalStore — memo-stable cols), a11y (aria-labels, TF fieldset, confidence role=meter, inline no-markets alert + select-all, progress-on-click), DRY formatters + terminal-grid-numeric, skip-reason tooltips. UI 12 + 356 src/functions tests pass. commits d835528+9090272 |
| 8 | PREF | Settings | pending | |
