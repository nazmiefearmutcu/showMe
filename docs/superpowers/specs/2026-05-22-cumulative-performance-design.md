# Cumulative performance (Sub-system I)

**Date:** 2026-05-22
**Depends on:** D (bot runner + signal_log)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Compute PnL stats from each bot's `signal_log` (entry/exit pairs), show a leaderboard across all bots, and surface basic metrics: total PnL, win rate, trade count, average trade. Per-bot equity-curve list (each completed trade contributes a point).

## 2. Approach

**Pure aggregation from existing data** — no new storage. We walk each bot's `signal_log`, pair entries with subsequent exits, compute the difference (for `long` positions: exit.price - entry.price; sized by spec `sizing_value`), and aggregate into metrics.

Limitations of v1 (intentional):
* Treat each entry → next-exit-of-same-bot as ONE round-trip trade (FIFO).
* Long-only PnL math (shorts deferred — most strategies in G are long).
* No commission/slippage modelling.
* No mark-to-market on open positions — only closed trades count.
* `sizing_value` from the bound strategy spec is used as the trade size.

## 3. Components

### 3.1 Backend

* `backend/showme/bots/performance.py` — pure computation module:
  * `Trade(entry_time, exit_time, entry_price, exit_price, qty, pnl, pnl_pct)` dataclass.
  * `compute_trades(bot, spec) -> list[Trade]` walks signal_log pairwise.
  * `compute_metrics(trades) -> dict` returns total_pnl, win_rate, trade_count, avg_pnl, max_drawdown.
  * `compute_equity_curve(trades, starting_equity) -> list[dict]` cumulative.
* `backend/showme/server_routes/bots.py` (modify) — add `GET /api/bots/{id}/performance` + `GET /api/bots/performance` (leaderboard).

### 3.2 UI

* `ui/src/lib/performance-store.ts` — leaderboard, selected-bot metrics, equity curve.
* `ui/src/functions/PERF.tsx`:
  * Top: total PnL across all bots (sum), best/worst bot pills.
  * Middle: sortable leaderboard table — symbol/strategy/trades/win_rate/total_pnl/avg_pnl.
  * Bottom: when a bot is selected, show its equity curve as a simple `<svg>` line chart (no external chart library — we keep it dependency-light).

## 4. Acceptance criteria

* I1. `compute_trades` correctly pairs entry+exit signals (FIFO), produces `Trade` objects.
* I2. `compute_metrics` returns sane numbers (positive on profitable trades, win_rate in [0,1]).
* I3. `GET /api/bots/performance` returns leaderboard sorted by total_pnl desc.
* I4. `GET /api/bots/{id}/performance` returns the same + trades list + equity curve.
* I5. PERF pane renders leaderboard + selectable equity curve.
* I6. Backend + UI tests green; live smoke shows leaderboard.

## 5. Frozen contracts

* `Trade` dataclass shape: entry_time, exit_time, entry_price, exit_price, qty, pnl, pnl_pct
* Metrics dict keys: total_pnl, win_rate, trade_count, avg_pnl, max_drawdown
* `GET /api/bots/performance` returns `{records: [{bot_id, symbol, ...metrics}]}`
* `GET /api/bots/{id}/performance` returns `{bot_id, ...metrics, trades, equity_curve}`
* PERF registered as native function (153→154 invariant bump)
