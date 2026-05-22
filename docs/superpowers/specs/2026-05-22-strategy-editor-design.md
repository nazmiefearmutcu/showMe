# Strategy editor (Sub-system E)

**Date:** 2026-05-22
**Project:** showMe
**Depends on:** F (SHIPPED — indicator catalog)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Let the user compose a **strategy spec** from F's indicator catalog and save/load it. A strategy spec is a JSON document describing entry/exit rules in terms of indicator signals. Bot RUNNING is D's job; E is just the editor + storage + a thin **compute engine** that calculates indicator values over a price series.

The compute engine is small enough to ship here (vs deferring) because D and G both need it. It supports the 15 F indicators using `numpy`/`pandas` (already pyproject deps).

## 2. Strategy spec shape

```json
{
  "id": "uuid4-hex",
  "name": "RSI mean revert",
  "description": "Entry RSI<30, exit RSI>70",
  "version": 1,
  "asset_filter": {                        // optional
    "exchanges": ["binance"],              // or null = any
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "asset_classes": ["spot"]
  },
  "timeframe": "1h",                       // 1m | 5m | 15m | 1h | 4h | 1d
  "indicators": [
    {"alias": "rsi14", "id": "rsi", "params": {"period": 14, "overbought": 70, "oversold": 30}},
    {"alias": "sma200", "id": "sma", "params": {"period": 200}}
  ],
  "entry_rules": [
    {"kind": "crosses_below", "left": "rsi14", "right": "literal:30"},
    {"kind": "greater_than", "left": "close", "right": "sma200"}
  ],
  "entry_logic": "all",                    // "all" | "any"
  "exit_rules": [
    {"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}
  ],
  "exit_logic": "any",
  "position": {
    "side": "long",                         // long | short
    "sizing_kind": "fixed_quote",           // fixed_quote | fixed_base | risk_pct
    "sizing_value": 100,                    // quote amount, or % per risk_pct
    "stop_loss_pct": 2.0,                   // optional
    "take_profit_pct": null
  },
  "created_at": "2026-05-22T10:00:00Z",
  "updated_at": "2026-05-22T10:00:00Z"
}
```

**Rule kinds** (kept minimal):
- `crosses_above(left, right)` — left was ≤ right, now >
- `crosses_below(left, right)` — opposite
- `greater_than(left, right)` — left > right at the current bar
- `less_than(left, right)` — left < right
- `equals_approximately(left, right, tolerance)` — |left - right| / right < tol

**Operands** are:
- An indicator alias: `"rsi14"` → looks up the indicator's primary output series
- A literal: `"literal:30"` (parsed as float)
- A price field: `"close"`, `"open"`, `"high"`, `"low"`, `"volume"`

This grammar is intentionally small. E ships a minimal but expressive baseline. G (template bots) and J (NL assistant) will leverage it. D adds the live-execution layer.

## 3. Components

### 3.1 Backend

* `backend/showme/strategies/spec.py` — pydantic models (`StrategySpec`, `IndicatorRef`, `Rule`, `Position`). Includes a `validate()` that checks indicator ids against F's catalog and resolves aliases.
* `backend/showme/strategies/store.py` — filesystem CRUD under `$SHOWME_HOME/strategies/{id}.json`. CRUD: `list()`, `get(id)`, `save(spec)`, `delete(id)`.
* `backend/showme/strategies/compute.py` — pure-Python indicator computation for the 15 F indicators. Takes an OHLCV DataFrame, returns a dict `{alias: pd.Series}`. Mirrors common Pine implementations.
* `backend/showme/strategies/evaluate.py` — given a price series + StrategySpec, returns a list of `{bar_index, kind: "entry"|"exit", details}` events. Used by D and by the editor's "Preview" feature.
* `backend/showme/server_routes/strategies.py` — `GET /api/strategies`, `POST /api/strategies`, `GET /api/strategies/{id}`, `PUT /api/strategies/{id}`, `DELETE /api/strategies/{id}`, `POST /api/strategies/{id}/preview?symbol=BTC/USDT&timeframe=1h&limit=200` (returns events for a sample series).

### 3.2 UI

* `ui/src/lib/strategy-store.ts` — zustand: `strategies: StrategyMeta[]`, `selected: StrategySpec | null`, CRUD actions via `sidecarFetch`.
* `ui/src/functions/STRA.tsx` — Strategy editor pane:
  * Left: list of saved strategies + "New" button.
  * Right: form with name/description/asset_filter/timeframe + indicator picker (uses F's INDX-style search) + rule builder (Add Entry Rule, Add Exit Rule — dropdowns for kind/left/right) + position sizing fields + Save + Preview buttons.
  * Preview: calls `/api/strategies/{id}/preview` and shows the list of detected entry/exit events.

## 4. Compute engine — what we implement vs. defer

The 15 indicators in F all have established formulas. Implementing them in pandas/numpy is ~10-30 lines each. We DO implement them (with unit tests vs published reference values) because D and G can't exist without them.

For accuracy: each indicator's tests assert against hand-computed expected values on a known small series (5-10 bars). Not against Pine-script outputs (no test fixture for that). Reasonable trust threshold for educational/demo use; users should validate with their own backtest before live trading — and the trade-permission gate from A ensures that's a deliberate decision.

## 5. Out of scope

* True backtesting metrics (Sharpe, max DD, drawdown curve) — minimal events list only in v1; full backtest engine deferred
* Multi-symbol / portfolio-level strategies — single-symbol-per-strategy in v1
* Time-based exit rules (e.g., "exit at 16:00") — deferred
* Compound conditions (nested AND/OR beyond top-level all/any) — deferred
* Strategy versioning / git-style branching — single-version per id
* Strategy sharing / export — defer to G+K (templates + integrations)

## 6. Acceptance criteria

* E1. Strategy spec roundtrips through pydantic + JSON without data loss.
* E2. `compute.py` produces correct outputs for the 15 F indicators against hand-curated reference series (≥10 unit tests).
* E3. `evaluate.py` correctly identifies entry/exit events on a fixture series.
* E4. CRUD routes return correct shapes; PUT preserves the `created_at`.
* E5. STRA pane lets user create + save + preview a strategy end-to-end.
* E6. Strategy files live in `$SHOWME_HOME/strategies/`; survive restart.
* E7. Live curl: POST a strategy, GET it back, preview it against a price series.
* E8. Native build deployed.

## 7. Frozen contracts

* `StrategySpec` JSON shape (above) — pin v1; future versions bump `version`
* Indicator alias namespace — globally unique within a strategy
* Rule kinds: `crosses_above`, `crosses_below`, `greater_than`, `less_than`, `equals_approximately`
* Operand prefixes: bare ident → indicator alias; `literal:` → float; `close|open|high|low|volume` → price fields
* Compute engine signature: `compute(df: pd.DataFrame, indicator_refs: list[IndicatorRef]) -> dict[str, pd.Series]`
* Routes: `/api/strategies` (CRUD) + `/api/strategies/{id}/preview`
* File location: `$SHOWME_HOME/strategies/{id}.json`
