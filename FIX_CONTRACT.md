# Bot System Fix Contract (4-Agent Coordination)

**Tarih:** 2026-05-23 (2. tur audit fix)
**Referans:** `BOT_AUDIT_REPORT.md` (89 bug)
**Amaç:** 4 paralel fix-agent çakışmadan kod yazsın; cross-cutting concerns burada tanımlı.

---

## Domain Ownership

| Agent | Files (sahip) | Files (DOKUNMA) |
|-------|---------------|------------------|
| **1: Backend Runtime** | `backend/showme/bots/*.py`, `backend/showme/strategies/*.py`, `backend/showme/brokers/factory.py` | server_routes/*, ui/* |
| **2: Backend API + Cascade** | `backend/showme/server_routes/*.py`, `backend/showme/brokers/__init__.py` (cascade hooks) | bots/*, strategies/* core, ui/* |
| **3: UI Creation** | `ui/src/functions/{BOT,BDA,STRA,TMPL}.tsx`, `ui/src/lib/{bot,strategy,template,assistant}-store.ts` | functions/{BOTS,PERF,CONN,PORT}.tsx, backend/* |
| **4: UI Supervisor** | `ui/src/functions/{BOTS,PERF,CONN,PORT}.tsx`, `ui/src/lib/{bots-supervision,performance,portfolio,exchange}-store.ts` | functions/{BOT,BDA,STRA,TMPL}.tsx, backend/* |

**Test sahipliği:** Her agent kendi test dosyalarını ekler/günceller. Agent 1: `backend/tests/test_{bots,strategies,evaluate,compute,performance,sizing}*.py`. Agent 2: `backend/tests/test_{bots_route,strategies_route,templates_route,bots_feed,exchange_cascade}*.py`. Agent 3: `ui/src/functions/{BOT,BDA,STRA,TMPL}*.test.tsx`. Agent 4: `ui/src/functions/{BOTS,PERF,CONN,PORT}*.test.tsx`.

---

## Shared API Contracts (TÜM agent'lar uymak zorunda)

### C1 — Sizing math tek modülde
**Sahibi:** Agent 1 yazar; Agent 2 import eder (performance route'unda).

```python
# backend/showme/strategies/sizing.py (YENI)
from typing import Literal
SizingKind = Literal["fixed_quote", "fixed_base", "risk_pct"]

def resolve_quantity(
    *, sizing_kind: SizingKind, sizing_value: float, price: float, equity: float
) -> float:
    """Returns base-currency qty. Raises ValueError on invalid input."""
    if sizing_value <= 0:
        raise ValueError("sizing_value must be > 0")
    if price <= 0:
        raise ValueError("price must be > 0")
    if sizing_kind == "fixed_quote":
        return sizing_value / price
    if sizing_kind == "fixed_base":
        return sizing_value
    if sizing_kind == "risk_pct":
        if not (0 < sizing_value <= 100):
            raise ValueError("risk_pct must be in (0, 100]")
        if equity <= 0:
            raise ValueError("equity must be > 0 for risk_pct sizing")
        return (sizing_value / 100.0 * equity) / price
    raise ValueError(f"unknown sizing_kind: {sizing_kind}")

def compute_pnl(
    *, entry_price: float, exit_price: float, side: Literal["long","short"],
    entry_qty: float
) -> float:
    """Returns absolute PnL in quote currency. Side-aware."""
    if entry_price <= 0 or entry_qty <= 0:
        return 0.0
    delta = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    return delta * entry_qty
```

Both `runner._dispatch_*` and `performance.compute_trades` MUST call these.

### C2 — Reference equity from broker
**Sahibi:** Agent 1.

```python
# backend/showme/bots/runner.py
async def _resolve_equity(broker, fallback_usd: float = 10_000.0) -> float:
    """Try broker.account()['equity']; fall back to constant if unavailable."""
    try:
        if hasattr(broker, "account"):
            acct = await broker.account()
            eq = acct.get("equity") or acct.get("cash")
            if eq and eq > 0:
                return float(eq)
    except Exception:
        pass
    return fallback_usd
```

`risk_pct` sizing MUST go through this (no more hardcoded $10k for live mode).

### C3 — Cascade delete invalidation hooks
**Sahibi:** Agent 1 (register) + Agent 2 (call).

```python
# backend/showme/brokers/factory.py — already has _INVALIDATION_HOOKS
# Agent 1 adds in bots/lifespan.py:
def _on_credential_deleted(credential_id: str) -> None:
    """Disable any bot referencing this credential."""
    store = BotStore.fresh()
    for rec in store.list():
        if rec.credential_id == credential_id and rec.enabled:
            try:
                asyncio.create_task(runner.disable(rec.id, store))
            except Exception as e:
                logger.warning(f"cascade disable failed for bot {rec.id}: {e}")

# Agent 1 wires at startup in lifespan
factory_mod.register_invalidation_hook(_on_credential_deleted)
```

Agent 2 strategy DELETE route MUST check FK before deleting:

```python
# backend/showme/server_routes/strategies.py
@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, force: bool = False):
    bot_store = BotStore.fresh()
    refs = [b for b in bot_store.list() if b.strategy_id == strategy_id]
    if refs and not force:
        raise HTTPException(409, {
            "error": "strategy_has_bots",
            "bot_count": len(refs),
            "bot_ids": [b.id for b in refs[:10]],
            "hint": "Use ?force=true to cascade-disable bots."
        })
    if refs and force:
        # cascade-disable referencing bots
        for b in refs:
            if b.enabled:
                # disable via runner if available
                ...
    StrategyStore.fresh().delete(strategy_id)
    return {"ok": True}
```

Agent 2 credential DELETE route MUST do same check (in exchange.py).

### C4 — Signal log split
**Sahibi:** Agent 1.

`BotRecord` gains a new field `closed_trades_log: list[ClosedTrade]` (append-only, no cap). Existing `signal_log` cap=100 stays for debug. PnL/PERF computation reads from `closed_trades_log` ONLY.

```python
# backend/showme/bots/record.py
class ClosedTrade(BaseModel):
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    qty: float
    side: Literal["long","short"]
    pnl: float
    bar_index_entry: int
    bar_index_exit: int

class BotRecord(BaseModel):
    ...
    signal_log: list[SignalEntry] = Field(default_factory=list, max_length=100)
    closed_trades_log: list[ClosedTrade] = Field(default_factory=list)  # YENI, no cap
```

When runner detects an exit pairing, it appends to `closed_trades_log` AND `signal_log`.

### C5 — `evaluate_last_bar` state-aware
**Sahibi:** Agent 1.

```python
# backend/showme/strategies/evaluate.py
def evaluate_last_bar(
    spec: StrategySpec, df: pd.DataFrame, *, in_position: bool
) -> SignalEvent | None:
    """O(1) per call; only emits event for the last bar based on caller-provided state."""
    if df.empty or len(df) < 2:
        return None
    last_i = len(df) - 1
    # ... evaluate rules on df.iloc[last_i] with shift(1) lookup
    # ... return SignalEvent or None
```

Runner MUST call this in tick:
```python
in_pos = bool(rec.last_processed_event and rec.last_processed_event.kind == "entry")
event = evaluate_last_bar(spec, df, in_position=in_pos)
```

`evaluate()` (full backtest) stays for preview endpoint.

### C6 — Per-tick broker cache
**Sahibi:** Agent 1.

`brokers/factory.py:_LIVE` dict already exists. Agent 1 audits `get_broker()` to NEVER recreate when target already in `_LIVE`. Lifespan shutdown calls `close_all_brokers()` (already exists).

### C7 — Auto-derive `tick_interval_seconds` from timeframe
**Sahibi:** Agent 1.

```python
# backend/showme/bots/record.py
_TF_SECONDS = {"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}

def default_tick_interval(timeframe: str) -> int:
    tf_s = _TF_SECONDS.get(timeframe, 60)
    return max(5, min(3600, tf_s // 4))
```

`BotRecord` validator: if `tick_interval_seconds` not explicitly set, use this.

### C8 — PUT body sanitize
**Sahibi:** Agent 2.

`PUT /api/bots/{id}` MUST strip: `signal_log`, `last_processed_event`, `closed_trades_log`, `created_at`, `updated_at`, `enabled` (use /enable, /disable routes). Strip before pydantic validation.

### C9 — UI cross-store invalidation
**Sahibi:** Agent 3.

`assistant-store.ts:generate()` AND `template-store.ts:instantiate()` MUST call `useStrategyStore.getState().loadList()` after success. Same for `strategy-store.ts:save()` triggering `useBotStore.getState().loadList()` is NOT needed (bots reference by ID only).

For `useStrategyStore.remove()` and `useExchangeStore.removeCredential()`: BEFORE calling backend DELETE, fetch dependency count via new GET endpoint (Agent 2 adds `/api/strategies/{id}/dependents` and `/api/exchange/credentials/{id}/dependents`). Show `window.confirm(... X bot etkilenecek)` UI. If user confirms, POST DELETE with `?force=true`.

### C10 — UI form validation regex
**Sahibi:** Agent 3.

```typescript
// ui/src/lib/validators.ts (YENI)
export const SYMBOL_RE = /^[A-Z0-9]+\/[A-Z0-9]+$/;
export function validateSymbol(s: string): string | null {
    const trimmed = s.trim().toUpperCase();
    if (!trimmed) return "Sembol gerekli.";
    if (!SYMBOL_RE.test(trimmed)) return "Format: BASE/QUOTE (ör. BTC/USDT).";
    return null;
}
export function clampTickInterval(raw: string): number {
    const n = Number(raw);
    if (!Number.isFinite(n)) return 60;
    return Math.max(5, Math.min(3600, Math.round(n)));
}
```

BOT.tsx `setField("symbol", ...)` MUST call `validateSymbol`; `setField("tick_interval_seconds", ...)` MUST use `clampTickInterval`. STRA timeframe `<select>` MUST guard against unknown enum values (fallback to draft.timeframe ?? "1h" with warning).

---

## Test Obligation (her agent için)

After implementing, agent MUST:
1. Run own domain tests: pytest (backend) or vitest (UI).
2. Tests MUST be green before declaring done.
3. Add new regression tests for fixed bugs (at least 1 test per CRITICAL bug fix).
4. Do NOT remove existing tests unless they assert broken behavior — in that case explain in summary.

---

## Output Format (her agent için)

```markdown
# Fix Report — Agent N

## Changes
- [file:line] short description (BUG ID from report)

## New Files
- backend/showme/strategies/sizing.py — ...

## New Tests
- backend/tests/test_sizing.py: 6 cases

## Test Results
- pytest: 88 + 6 = 94/94 green
- vitest: 75/75 green (UI agent only)

## Bugs Fixed
- C-API-1 ✓ (validation + sizing.py)
- ...

## Bugs NOT Fixed (explain why)
- BUG #X: out of scope for this domain / requires Agent N coordination
```
