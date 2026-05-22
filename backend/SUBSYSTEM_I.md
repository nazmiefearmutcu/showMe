# Sub-system I — Cumulative performance (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-cumulative-performance-design.md](../docs/superpowers/specs/2026-05-22-cumulative-performance-design.md)
Plan: [docs/superpowers/plans/2026-05-22-cumulative-performance.md](../docs/superpowers/plans/2026-05-22-cumulative-performance.md)

## What landed

* Trade dataclass + pure-aggregation compute module (trades / metrics / equity curve)
* /api/bots/performance leaderboard + /api/bots/{id}/performance detail
* PERF pane with KPI strip, sortable leaderboard, SVG equity curve

## V1 limitations

* Long-only PnL
* No commissions / slippage
* No MTM on open positions
* sizing_value from strategy spec

## Out of scope

J (NL assistant), K (integrations).
