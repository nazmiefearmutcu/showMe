# Bot supervision (Sub-system H) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** BOTS supervisor pane with aggregate stats + per-bot table + unified signal feed; backed by ONE new route `GET /api/bots/feed`.

**Tech Stack:** existing — FastAPI, React + TS + zustand.

---

## Tasks

### Task H1: /api/bots/feed route + tests

**Files:**
- Modify: `backend/showme/server_routes/bots.py` — add `feed` endpoint
- Create: `backend/tests/test_bots_feed.py`

Endpoint:
```python
@router.get("/api/bots/feed")
async def bots_feed(limit: int = 50) -> dict[str, Any]:
    """Aggregate latest signals across all bots."""
    from datetime import datetime, timezone
    store = _store()
    all_signals: list[dict[str, Any]] = []
    for meta in store.list():
        rec = store.get(meta.id)
        for entry in rec.signal_log:
            d = entry.model_dump()
            d["bot_id"] = rec.id
            d["bot_symbol"] = rec.symbol
            d["bot_strategy_id"] = rec.strategy_id
            d["bot_exchange_id"] = rec.exchange_id
            d["bot_mode"] = rec.mode
            all_signals.append(d)
    all_signals.sort(key=lambda s: s.get("timestamp") or s.get("bar_time") or "", reverse=True)
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "signals": all_signals[:max(0, min(limit, 500))],
    }
```

Tests:
1. Empty (no bots) → empty list.
2. Two bots with signals → merged + sorted by timestamp descending.
3. Limit honored.

### Task H2: UI bots-supervision-store + BOTS pane + registry

**Files:**
- `ui/src/lib/bots-supervision-store.ts` + test
- `ui/src/functions/BOTS.tsx` + test
- Modify registry.tsx + registry.test.tsx (152→153 + NATIVE_ONLY += "BOTS")
- Modify Sidebar.tsx (BOTS added to TOOL_ITEMS after TMPL)

Store: `aggregateStats`, `botRows`, `feed`, `loading`, `error`, `loadAll()` calls `/api/bots`, `/api/bots/feed` in parallel, computes stats client-side.

BOTS pane:
- Top: aggregate strip (KPI cards: total / enabled / live / signals_today)
- Middle: per-bot table — symbol, strategy_id, timeframe, mode (pill), enabled, last_signal_time, signals_count
- Bottom: signal feed table — bot_id chip, symbol, kind, price, action, time

Auto-refresh every 10s.

Tests:
- store: loadAll populates 3 slices; error path
- pane: renders empty state, table rows, signal feed entries, KPI cards

### Task H3: Native rebuild + close-out

Tests; sidecar+tauri build (no spec datas change — pure code); deploy; live smoke `GET /api/bots/feed`; screenshot; memory note; SUBSYSTEM_H.md.
