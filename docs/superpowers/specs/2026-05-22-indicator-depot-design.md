# Indicator depot (Sub-system F)

**Date:** 2026-05-22
**Project:** showMe
**Depends on:** none (independent)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Build the indicator catalog framework + ship 15 representative built-in indicators with the full metadata schema the user requested:
- Plain-Turkish-language description
- Parameter glossary: what each parameter changes and how
- 10/10 confidence score with color coding (e.g. 9-10 green, 6-8 yellow, ≤5 red)
- Suggested strategy template per indicator

The 15 indicators (RSI, MACD, EMA, SMA, BB, Stoch, ATR, ADX, CCI, OBV, WilliamsR, VWAP, Ichimoku, ParabolicSAR, KDJ) cover trend / momentum / volatility / volume — the four core families. The architecture lets later additions drop into the catalog YAML without code change.

**Why not all 150-200 TradingView built-ins now:** YAGNI. Each indicator requires curated metadata (description, parameter docs, confidence rationale, strategy template) — automated extraction is unreliable. Ship the framework + 15, let the catalog grow organically.

## 2. Approach

* **Catalog file**: `backend/showme/indicators/catalog/indicators.yml` — YAML list of entries (similar structure to A's exchanges.yml).
* **Loader**: `backend/showme/indicators/catalog/loader.py` — `IndicatorEntry`/`IndicatorCatalog` dataclasses + `load_indicator_catalog()`.
* **Computation** **(out of scope for F)**: showMe's `engine/` already has working indicator computation (RSI, MACD, etc. from TBV3 lineage — but per [[showme_exchanges_isolate_tbv3]] we don't import from TBV3; we use showMe's own engine). F is about METADATA + UI. The actual `compute(series, params)` wiring lands in E (strategy editor).
* **Route**: `GET /api/indicators/catalog` exposes the loader's `to_payload()`.
* **UI**: new `INDX` (Indicator Index) pane — searchable grid of indicators with confidence chips, click-through to detail view with full metadata + suggested strategy.

## 3. Components

### 3.1 Catalog YAML schema

Each entry:
```yaml
- id: rsi
  display_name: RSI (Relative Strength Index)
  family: momentum
  short_description: "Bir varlığın aşırı alım/satım bölgelerini momentum açısından ölçer."
  long_description: |
    Wilder (1978) tarafından geliştirildi. Fiyatın belirli bir period
    içindeki kazanç ve kayıp ortalamalarını bir 0-100 ölçeğine yansıtır.
    Geleneksel olarak 70 üzeri "aşırı alım", 30 altı "aşırı satım" olarak
    yorumlanır — ancak güçlü trend dönemlerinde bu seviyeler aylarca
    tetiklenmeden kalabilir.
  formula: "RSI = 100 - 100 / (1 + RS), RS = avg_gain / avg_loss"
  parameters:
    - name: period
      type: int
      default: 14
      min: 2
      max: 100
      effect: "Düşürmek (örn 7) sinyali daha hızlı/cabuk yapar ama yanlış sinyal artar. Yükseltmek (örn 28) yumuşatır, yavaşlatır."
    - name: overbought
      type: float
      default: 70
      min: 50
      max: 95
      effect: "Yüksek değer (80+) daha az sinyal, daha güvenilir aşırı alım."
    - name: oversold
      type: float
      default: 30
      min: 5
      max: 50
      effect: "Düşük değer (20-) daha az ama daha güvenilir aşırı satım sinyali."
  confidence: 9
  confidence_rationale: "Doğru ortamda (range-bound / mean-reverting) çok güvenilir. Güçlü trendde yanıltıcı. Net 9/10."
  suggested_strategy:
    name: "RSI mean-revert"
    summary: "Period=14, overbought=70, oversold=30. RSI 30 altına düştüğünde long, 70 üstüne çıktığında close. Trend filtresi olmadan range piyasalarda iyi çalışır."
    rules:
      - "Entry: RSI crosses below `oversold` AND price > 200-SMA (trend filter)."
      - "Exit: RSI crosses above `overbought` OR stop-loss at entry - 2*ATR."
      - "Position sizing: 1% account risk per trade."
  references:
    - "Wilder, J. Welles (1978). New Concepts in Technical Trading Systems."
```

`confidence: int 1-10`. UI maps to color:
- 9-10 → green
- 7-8 → light green
- 5-6 → yellow
- 3-4 → orange
- 1-2 → red

### 3.2 The 15 initial indicators

| # | id | Family | Confidence |
|---|---|---|---|
| 1 | rsi | momentum | 9 |
| 2 | macd | momentum | 9 |
| 3 | ema | trend | 8 |
| 4 | sma | trend | 7 |
| 5 | bollinger_bands | volatility | 8 |
| 6 | stochastic | momentum | 7 |
| 7 | atr | volatility | 9 |
| 8 | adx | trend | 8 |
| 9 | cci | momentum | 6 |
| 10 | obv | volume | 6 |
| 11 | williams_r | momentum | 6 |
| 12 | vwap | volume | 9 |
| 13 | ichimoku | trend | 7 |
| 14 | parabolic_sar | trend | 6 |
| 15 | kdj | momentum | 5 |

Each entry hand-curated with the schema above.

### 3.3 Loader

`backend/showme/indicators/catalog/loader.py` — parallel to brokers/catalog/loader.py:
- `IndicatorParam(name, type, default, min, max, effect)` (frozen dataclass)
- `IndicatorEntry(id, display_name, family, short_description, long_description, formula, parameters, confidence, confidence_rationale, suggested_strategy, references)` (frozen)
- `IndicatorCatalog(entries: tuple[IndicatorEntry, ...])` with `by_id`, `search`, `filter(family=)`, `to_payload`
- `load_indicator_catalog(path)`

### 3.4 Route

`backend/showme/server_routes/indicators.py`:
- `GET /api/indicators/catalog` → `to_payload()`
- `GET /api/indicators/{id}` → single entry as JSON

### 3.5 UI

`ui/src/lib/indicator-store.ts` — zustand store, loads catalog once, exposes `entries`, `byId`, `search`.

`ui/src/functions/INDX.tsx` — new pane:
- **Left**: searchable grid of indicator cards, each showing display_name + family + confidence chip (color-coded).
- **Right**: detail view for selected indicator — short + long description, parameters table (with `effect` column), formula, confidence rationale, suggested strategy block.
- Search input filters by id/display_name/family.

Register `INDX` in `registry.tsx` + sidebar (new "Strategy" group or under "Tools").

## 4. Out of scope

* Indicator COMPUTATION engine (deferred to E — strategy editor needs to call `compute(series, params)`, but F is metadata-only)
* Backtesting (deferred to D or later)
* Custom user indicators (Pine-script-like DSL — deferred indefinitely)
* All 150-200 TradingView built-ins (deferred to organic expansion)
* GitHub/HF indicator imports (deferred to K)

## 5. Acceptance criteria

* F1. 15 indicator entries in `indicators.yml`, all validated by loader tests.
* F2. `GET /api/indicators/catalog` returns 15 entries with correct shape.
* F3. INDX pane renders the grid + detail view; search works; confidence colors render.
* F4. Backend + UI tests green; ≥10 new test cases total.
* F5. Native build deployed.

## 6. Frozen contracts

* `IndicatorEntry.id` is the stable lookup key — never rename
* Confidence is int 1-10 (UI maps to color tiers)
* `parameters` is a LIST (not dict) so iteration order is stable across the UI
* Route paths: `/api/indicators/catalog` + `/api/indicators/{id}`
