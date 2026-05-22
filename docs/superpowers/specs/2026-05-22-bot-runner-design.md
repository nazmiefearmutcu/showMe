# Strategy bot runner (Sub-system D)

**Date:** 2026-05-22
**Project:** showMe
**Depends on:** A (broker), C (write path), E (strategy spec + evaluate)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Run E's strategies live: on each tick of a per-strategy schedule, fetch recent OHLCV for the bound credential's exchange, evaluate the strategy, emit any new entry/exit signal, and (gated by trade permission + bot enable flag) submit the corresponding order via A's broker.

## 2. Approach

* **Bot record**: a separate entity from a strategy. A bot binds a strategy + a credential + a symbol + a tick interval + an enabled flag. Many bots can run different strategies in parallel; multiple bots can share the same strategy.
* **Scheduler**: a single `asyncio.Task` per enabled bot. The sidecar lifespan starts/stops them. On each tick:
  1. Fetch the latest N bars (`limit=200`) of OHLCV via ccxt's `fetch_ohlcv` (already accessible through the broker's exchange instance — D adds a small helper).
  2. Run `evaluate(spec, df)`.
  3. Compare last event to the bot's last-processed event (stored in bot record). If a NEW event appeared on the latest bar (within tolerance window), emit a signal.
  4. If `signal.kind == "entry"` and the bot is enabled with trade perm → place the order via the existing `broker.submit_order(...)`.
  5. If `signal.kind == "exit"` → submit an opposite-side market close.
* **Safety rails**: enabled bots that fire too fast are rate-limited (min 60s between live orders per bot). A "shadow" mode (the default) emits signals + writes to a log but does NOT place orders — so users can verify before going live.
* **Storage**: bots stored as JSON under `$SHOWME_HOME/bots/{id}.json` (parallel to strategies).

## 3. Bot record shape

```json
{
  "id": "uuid",
  "strategy_id": "<E strategy id>",
  "credential_id": "<A credential id>",
  "exchange_id": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1h",                       // overrides strategy.timeframe if set
  "tick_interval_seconds": 60,
  "mode": "shadow",                        // "shadow" | "live"
  "enabled": false,                        // bot must be explicitly enabled
  "last_processed_event": null,            // {bar_time, kind} of last event handled
  "signal_log": [...],                     // last 100 signals (FIFO)
  "created_at": "...",
  "updated_at": "..."
}
```

## 4. Components

### 4.1 Backend

* `backend/showme/bots/record.py` — pydantic `BotRecord` + `SignalEntry`.
* `backend/showme/bots/store.py` — FS CRUD under `$SHOWME_HOME/bots/`.
* `backend/showme/bots/ohlcv.py` — `async fetch_ohlcv(broker, symbol, timeframe, limit)` — uses the ccxt exchange behind a `CcxtBroker`. For non-ccxt adapters (Alpaca), returns a synthetic series (D doesn't aim to support non-ccxt live data in v1).
* `backend/showme/bots/runner.py` — `BotRunner` class with `start_all()` / `stop_all()` / `tick(bot_id)` methods. Each enabled bot gets an `asyncio.Task`. Cancelled cleanly on `aclose()`.
* `backend/showme/bots/lifespan.py` — `lifespan_startup()` / `lifespan_shutdown()` hooks called from `server.py`.
* `backend/showme/server_routes/bots.py` — CRUD + `POST /api/bots/{id}/enable` + `POST /api/bots/{id}/disable` + `GET /api/bots/{id}/signals`.

### 4.2 UI

* `ui/src/lib/bot-store.ts` — list bots, current bot, enable/disable, view signals.
* `ui/src/functions/BOT.tsx` — bot management pane:
  * Left: list of bots with status pill (shadow/live/disabled).
  * Right: form (strategy dropdown from STRA's list, credential dropdown from CONN's list, exchange/symbol/timeframe/tick_interval, mode toggle, enable/disable button), plus a signal-log viewer.

## 5. Mode safety

* Default mode `shadow` — NO live orders. Signal log only.
* Switching to `live` requires re-typing the credential's `account_label` (mirrors A/C's escalation pattern).
* `live` mode REQUIRES the credential to have `trade` permission. If permission is `("read",)`, the route refuses to set mode=live.
* Live trade calls go through C's `trading-store.openTicket → confirm(typedLabel)` path INTERNALLY? No — for the bot runner we bypass the human-confirmation modal (the user already confirmed at bot-enable time). But we DO log every live order. Adapter-level `_require("trade")` is the final defense.

## 6. Out of scope

* Per-bot risk metrics / Sharpe / equity curve (deferred to I)
* Multi-strategy bots (one bot = one strategy in v1)
* Order management beyond submit/close (no order modification, no bracket orders)
* Cross-bot coordination (each bot is independent)
* Backtest mode using historical OHLCV (defer)
* WebSocket-driven ticks (poll-only in v1)

## 7. Acceptance criteria

* D1. Bot CRUD: create/list/get/update/delete.
* D2. Enable/disable transitions update the in-memory runner.
* D3. Shadow-mode tick: bot evaluates strategy, appends to signal_log, does NOT place orders.
* D4. Live-mode requires (a) trade-permission credential, (b) account_label confirmation.
* D5. Tick interval honored — no double-ticks within interval.
* D6. Restart preserves bots; disabled bots stay disabled; enabled bots auto-resume on next sidecar boot.
* D7. Backend + UI tests green; live curl walk-through end-to-end.

## 8. Frozen contracts

* Bot record JSON shape (above)
* Routes: `/api/bots` (CRUD), `/api/bots/{id}/enable`, `/api/bots/{id}/disable`, `/api/bots/{id}/signals`
* `BotRunner` API: `start_all(store)`, `stop_all()`, `tick(bot_id)`, `aclose()`
* File location: `$SHOWME_HOME/bots/{id}.json`
* Signal log capped at 100 entries (FIFO)
