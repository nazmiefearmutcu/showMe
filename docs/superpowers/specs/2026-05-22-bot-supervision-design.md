# Bot supervision (Sub-system H)

**Date:** 2026-05-22
**Depends on:** D (bot runner + signal_log)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Show the live state of all running bots in one pane: unified signal feed across all bots, per-bot health (last-tick-time, signal count today, mode), and ability to jump into any bot's detail. The BOT pane (D5) is per-bot; this **BOTS** pane is the supervisor view.

## 2. Approach

**Backend additions are minimal** — D already exposes `/api/bots` and `/api/bots/{id}/signals`. We add ONE route that aggregates: `GET /api/bots/feed?limit=50` returns the most recent N signals across all bots, sorted by timestamp descending, each tagged with `bot_id` + `bot_symbol` so the UI can render bot identity inline.

**UI** is the heavy piece:
* `ui/src/functions/BOTS.tsx` (note the plural — distinct from D's per-bot `BOT.tsx`):
  * Top: aggregate strip (total bots, enabled count, live count, signals today)
  * Middle: per-bot table — symbol/strategy/timeframe/mode/enabled-pill/last-tick-time/signals-today/last-signal-summary
  * Bottom: live signal feed (last 50 across all bots) — scrolling tape with bot_id chip + symbol + kind + price
* Auto-refresh every 10 seconds (signal_log updates fast when bots are ticking).

## 3. Components

### 3.1 Backend

* `backend/showme/server_routes/bots.py` (modify) — add `GET /api/bots/feed?limit=50` endpoint that walks every bot, takes its signal_log tail, merges + sorts by timestamp.

### 3.2 UI

* `ui/src/lib/bots-supervision-store.ts` — zustand store: aggregate stats, per-bot rows, signal feed.
* `ui/src/functions/BOTS.tsx` — the supervisor pane.

## 4. Out of scope

* Realtime WebSocket push (poll only, 10s)
* Bot-level PnL or equity (deferred to I)
* Per-signal trade execution details beyond what signal_log already carries
* Per-bot historical charts

## 5. Acceptance criteria

* H1. `GET /api/bots/feed` returns merged signals across all bots, sorted desc by timestamp, capped by limit.
* H2. BOTS pane renders aggregate strip + per-bot table + signal feed.
* H3. Tests: route (3), store (3), pane (4) — ≥10 new tests total.
* H4. Native build deployed; live smoke shows BOTS pane with at least empty-state rendering.

## 6. Frozen contracts

* `GET /api/bots/feed?limit=N` returns `{signals: [...with bot_id+symbol], generated_at}`.
* `useBotsSupervisionStore` zustand store.
* BOTS pane registered as a NEW native function code (152→153 invariant bump).
