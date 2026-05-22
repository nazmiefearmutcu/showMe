# Strategy editor (Sub-system E) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Strategy spec + filesystem store + compute engine for the 15 F indicators + evaluate engine + routes + STRA pane.

**Architecture:** Spec at `docs/superpowers/specs/2026-05-22-strategy-editor-design.md`.

**Tech Stack:** Python 3.11+, pydantic v2, pandas, numpy (all existing deps); React + TS + zustand.

---

## Tasks

### Task E1: spec.py + store.py

**Files:**
- `backend/showme/strategies/__init__.py` (empty)
- `backend/showme/strategies/spec.py` — pydantic models
- `backend/showme/strategies/store.py` — FS CRUD
- `backend/tests/test_strategy_spec.py`
- `backend/tests/test_strategy_store.py`

`spec.py` defines `StrategySpec`, `IndicatorRef`, `Rule`, `Position`, `AssetFilter` (all pydantic BaseModel). `from_json(s)` / `to_json()` classmethods. `validate_against_catalog(catalog)` checks indicator ids + alias uniqueness.

`store.py` defines `StrategyStore` with `list() -> list[StrategyMeta]`, `get(id) -> StrategySpec`, `save(spec) -> StrategySpec` (sets created_at on first save, always bumps updated_at), `delete(id) -> bool`. Storage: `$SHOWME_HOME/strategies/{id}.json`. `StrategyStore.fresh()` classmethod resolves the path.

Tests: spec roundtrip, validation rejects missing indicator, alias-uniqueness, store CRUD with tmp SHOWME_HOME, save preserves created_at on update.

### Task E2: compute.py (15 indicators)

**Files:**
- `backend/showme/strategies/compute.py`
- `backend/tests/test_compute.py`

Implements the 15 F indicators on a pandas OHLCV DataFrame. Function signature: `compute(df: pd.DataFrame, indicator_refs: list[IndicatorRef]) -> dict[str, pd.Series]`. Each ref produces ONE series (the primary output) under its `alias` key. Internally dispatched via `_FUNCTIONS: dict[str, Callable]`.

For each indicator (rsi, macd, ema, sma, bollinger_bands, stochastic, atr, adx, cci, obv, williams_r, vwap, ichimoku, parabolic_sar, kdj):
- Implementation in 10-30 lines using pandas/numpy
- Unit test with a hand-curated 10-bar series → assertions on the last 1-2 values
- Edge case: insufficient data → returns NaN series (caller handles)

Some indicators are multi-output (e.g. MACD has MACD/Signal/Hist). For v1, return the primary line as the alias output. Downstream rule grammar references one series per alias.

### Task E3: evaluate.py + tests

**Files:**
- `backend/showme/strategies/evaluate.py`
- `backend/tests/test_evaluate.py`

`evaluate(spec: StrategySpec, df: pd.DataFrame) -> list[Event]` returns chronological events. Event = `{bar_index: int, bar_time: str, kind: "entry"|"exit", price: float, details: dict}`.

Algorithm: for each bar (after warm-up = max indicator period), compute all conditions in entry/exit lists; combine with `entry_logic`/`exit_logic` (`all` / `any`); emit events on edge transitions (NOT every bar that's in state).

State machine: flat → entry → in_position → exit → flat. Reject contradictory same-bar entry+exit; first event of the bar wins (entry).

Tests: 5+ fixtures covering crosses_above/below, AND/OR logic, single-bar gap edge cases, warm-up bars produce no events.

### Task E4: /api/strategies/* routes

**Files:**
- `backend/showme/server_routes/strategies.py`
- Modify `backend/showme/server_routes/__init__.py`
- `backend/tests/test_strategies_route.py`

Routes:
- `GET /api/strategies` — list metadata
- `POST /api/strategies` — create (body = StrategySpec without id; server assigns uuid + timestamps)
- `GET /api/strategies/{id}` — single
- `PUT /api/strategies/{id}` — update
- `DELETE /api/strategies/{id}` — remove
- `POST /api/strategies/{id}/preview?symbol=BTC/USDT&timeframe=1h&limit=200` — calls existing showMe chart history to pull OHLCV, runs `evaluate()`, returns event list

Family register inserts `strategies` alphabetically.

### Task E5: UI strategy-store + STRA pane

**Files:**
- `ui/src/lib/strategy-store.ts`
- `ui/src/lib/strategy-store.test.ts`
- `ui/src/functions/STRA.tsx`
- `ui/src/functions/STRA.test.tsx`
- Modify `ui/src/functions/registry.tsx` + `registry.test.tsx` (148→149 already from F, bump to 150 here)
- Modify `ui/src/shell/Sidebar.tsx`

strategy-store: list, currentSpec, dirty flag, CRUD actions, preview action.

STRA pane:
- Left: list of saved strategies + "New strategy" button.
- Right: form
  - Name, description, timeframe dropdown
  - AssetFilter inputs (symbols comma-sep, exchanges multi-select from CONN, asset_classes chips)
  - Indicators: list with Add button → opens picker from `useIndicatorStore` (F's catalog); each row shows alias input + params for that indicator.
  - Entry rules: list with Add → kind dropdown + left/right operand selects + literal input.
  - Exit rules: same shape.
  - Logic toggles (all / any).
  - Position sizing fields.
  - Save / Save As / Delete / Preview buttons.
- Preview result: list of events with bar_time + kind + price.

Tests: STRA renders list, new strategy form opens, add indicator action populates, save calls store action.

### Task E6: native rebuild + close-out

Full tests; sidecar+tauri build; deploy; live curl `/api/strategies` CRUD + preview; screenshot; memory `showme_subsystem_e.md`; `backend/SUBSYSTEM_E.md`.
