# ShowMe — Page-by-Page Development Progress

Ralph-driven, one page per iteration. Plan: `docs/superpowers/plans/2026-06-08-page-by-page-development.md`.

| # | Code | Page | Status | Notes |
|---|------|------|--------|-------|
| 1 | HOME | Overview | ✅ done | live movers (live:true), BRIEF wired + honest demo fallback, aria-labels + role=status, div role=row (a11y fix), tabular-nums, centralized formatters; 78 tests pass. commit 749a156 |
| 2 | WATCH | Live Watchlist | ✅ done | stable-node live pulse restart (no jitter+flash), Volume/Notional cols (real snapshot.volume, honest —), aria-labels + role=status/alert, terminal-grid-numeric, compact sparkline; all WATCH tests pass. commits 1f9c79d+de4f597 |
| 3 | PORT | Portfolio | ✅ done | broker positions surfaced in main view (frontend merge, real asset_class), crypto live quotes (backend), honest return badge (replaced fake sparkline), DRY formatters + terminal-grid-numeric, sorting + aria; UI 20 + backend 132 tests pass. commits 269becb+bc32a21 |
| 4 | WEI | Macro Monitor | ✅ done | world indices 11→31 (all regions, EM; single source of truth + baseline-drift guard), real as_of freshness, "Model data" badge + honest de-emphasized synthetic sparklines, fixed false Degraded banner, format.ts+terminal-grid-numeric, sorting + a11y + responsive KPI; UI 9 + backend 87 tests pass. commit ee1e2ca |
| 5 | NI | News Desk | pending | |
