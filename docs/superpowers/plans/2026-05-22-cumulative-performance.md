# Cumulative performance (Sub-system I) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Pure-aggregation PnL metrics from bot signal_log + leaderboard + PERF pane.

---

## Tasks

### Task I1: performance.py + tests

**Files:**
- `backend/showme/bots/performance.py`
- `backend/tests/test_performance.py`

Module:
- `@dataclass(frozen=True) Trade(entry_time, exit_time, entry_price, exit_price, qty, pnl, pnl_pct)` with `to_dict()`.
- `compute_trades(bot_signal_log, sizing_value) -> list[Trade]` — walks signals; when `kind=="entry"` pushes to open stack; on `kind=="exit"` pops oldest entry, builds Trade. Skips entries with `action == "skipped"`.
- `compute_metrics(trades) -> dict` — returns `{total_pnl, win_rate, trade_count, avg_pnl, max_drawdown}`. Max drawdown computed from cumulative-pnl series.
- `compute_equity_curve(trades, starting_equity=10_000) -> list[dict]` — list of `{t, equity}`.

Tests: empty signal log → no trades / 0 metrics; one entry-then-exit pair → 1 trade with correct PnL; multiple round-trips → metrics aggregate; max drawdown from a sequence of wins followed by losses; `action=="skipped"` entries ignored.

### Task I2: Routes + UI + PERF pane

**Files (backend):**
- Modify: `backend/showme/server_routes/bots.py` — add 2 new endpoints BEFORE `/api/bots/{id}` route (FastAPI order matters, per H1 finding):
  - `GET /api/bots/performance` — leaderboard across all bots
  - `GET /api/bots/{id}/performance` — single bot trades + metrics + equity_curve
- Create: `backend/tests/test_performance_route.py`

For `/api/bots/{id}/performance`, also load the bot's bound StrategySpec to get sizing_value (default 100 if missing).

**Files (UI):**
- Create: `ui/src/lib/performance-store.ts` + test
- Create: `ui/src/functions/PERF.tsx` + test
- Modify: `ui/src/functions/registry.tsx` + test (153→154, NATIVE_ONLY += "PERF")
- Modify: `ui/src/shell/Sidebar.tsx` (PERF after BOTS in TOOL_ITEMS)

performance-store: `leaderboard`, `selected: {bot_id, metrics, trades, equity_curve}`, `loadLeaderboard()`, `loadBot(id)`.

PERF pane:
- Top: total PnL across all bots (sum), best/worst pills.
- Middle: sortable leaderboard table.
- Right pane (when bot selected): equity curve `<svg>` (no chart lib).

### Task I3: Native rebuild + close-out

Tests; build; deploy; live smoke `/api/bots/performance`; screenshot; memory note; SUBSYSTEM_I.md.
