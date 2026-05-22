# Bot runner (Sub-system D) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Run E strategies live via asyncio scheduler per enabled bot. Shadow mode default; live mode requires account_label confirm + trade permission.

**Architecture:** Spec at `docs/superpowers/specs/2026-05-22-bot-runner-design.md`.

**Tech Stack:** Python 3.11+ asyncio, pydantic, pandas, ccxt; React + TS + zustand.

---

## Tasks

### Task D1: BotRecord + store
**Files:** `backend/showme/bots/__init__.py`, `backend/showme/bots/record.py`, `backend/showme/bots/store.py`, `backend/tests/test_bot_record.py`, `backend/tests/test_bot_store.py`

`record.py`: `BotRecord` pydantic with id, strategy_id, credential_id, exchange_id, symbol, timeframe ("1m".."1d"), tick_interval_seconds (default 60, min 5), mode ("shadow"|"live"), enabled (bool), last_processed_event (`SignalEntry | None`), signal_log (list[SignalEntry], capped at 100), created_at, updated_at. `SignalEntry`: bar_index, bar_time, kind, price, action ("placed"|"shadow"|"skipped"), order_id (optional), error (optional). `BotRecord.append_signal(entry)` returns a new record with FIFO-truncated signal_log.

`store.py`: `BotStore` parallel to `StrategyStore`. CRUD + `BotStore.fresh()`.

Tests: roundtrip; signal_log FIFO at 100; CRUD; created_at preserved on save.

### Task D2: OHLCV fetcher
**Files:** `backend/showme/bots/ohlcv.py`, `backend/tests/test_ohlcv.py`

`async fetch_ohlcv(broker, symbol, timeframe, limit) -> pd.DataFrame`. If broker is a `CcxtBroker`, calls `broker._ex.fetch_ohlcv(symbol, timeframe, limit=limit)` and converts to OHLCV DataFrame with datetime index. For non-ccxt brokers, raises `BotRunnerError("non-ccxt OHLCV not supported")`.

Tests: mock ccxt module; verify DataFrame shape (columns open/high/low/close/volume + datetime index); non-ccxt raises.

### Task D3: Runner + lifespan
**Files:** `backend/showme/bots/runner.py`, `backend/showme/bots/lifespan.py`, `backend/tests/test_bot_runner.py`

`BotRunner` class with:
- `_tasks: dict[bot_id, asyncio.Task]`
- `async start_all(store)` — for each enabled bot, spawn a task running `_run_loop(bot_id)`.
- `async _run_loop(bot_id)`: every `tick_interval_seconds`, call `tick(bot_id)`. Catches per-tick exceptions, logs at WARNING, continues. Stops when task is cancelled.
- `async tick(bot_id)` — heart of the runner: load bot+strategy, fetch OHLCV, evaluate, detect NEW event vs `last_processed_event`, append signal, if mode==live + trade perm, submit order via factory broker.
- `async enable(bot_id, store)` — mark enabled in store, spawn task if not running.
- `async disable(bot_id, store)` — mark disabled in store, cancel task.
- `async aclose()` — cancel all tasks.

`lifespan.py`: module-level singleton `_RUNNER: BotRunner | None`; `await startup()` creates+starts; `await shutdown()` aclose. Both wired from `server.py` lifespan.

Tests (with mocked broker + store): tick produces signal in shadow mode; tick skips when interval not elapsed; runner.aclose() cancels tasks; new event vs last_processed gets logged once; enable/disable transitions work.

### Task D4: /api/bots/* routes
**Files:** `backend/showme/server_routes/bots.py`, modify `backend/showme/server_routes/__init__.py`, `backend/tests/test_bots_route.py`

Routes:
- `GET /api/bots`
- `POST /api/bots` (mode forced to "shadow" on create)
- `GET /api/bots/{id}`
- `PUT /api/bots/{id}` — validates trade perm if mode=live + confirm_account_label
- `DELETE /api/bots/{id}` — disables + removes
- `POST /api/bots/{id}/enable` — body `{confirm_account_label?: str}` (required if mode=live)
- `POST /api/bots/{id}/disable`
- `GET /api/bots/{id}/signals` — returns `signal_log`

### Task D5: UI bot-store + BOT pane
**Files:** `ui/src/lib/bot-store.ts` + test, `ui/src/functions/BOT.tsx` + test, modify registry/registry.test/Sidebar.

BOT pane:
- Left: list of bots with mode pill (shadow=warn, live=err, disabled=gray).
- Right: form (strategy_id dropdown from STRA store, credential_id from exchange-store, exchange_id auto-filled from credential, symbol input, timeframe dropdown, tick_interval input, mode toggle with account_label confirm input), Enable/Disable button, Signal log (last 20).

### Task D6: native rebuild + close-out
Full tests; sidecar+tauri build; deploy; live curl: create bot (shadow), enable, tick (verify signal_log grows), disable, delete; screenshot; memory note; SUBSYSTEM_D.md.
