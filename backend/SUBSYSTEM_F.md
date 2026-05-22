# Sub-system F — Indicator depot (SHIPPED 2026-05-22)

Spec: [docs/superpowers/specs/2026-05-22-indicator-depot-design.md](../docs/superpowers/specs/2026-05-22-indicator-depot-design.md)
Plan: [docs/superpowers/plans/2026-05-22-indicator-depot.md](../docs/superpowers/plans/2026-05-22-indicator-depot.md)

## What landed

* 15 hand-curated indicators (RSI, MACD, EMA, SMA, Bollinger Bands, Stochastic, ATR, ADX, CCI, OBV, Williams %R, VWAP, Ichimoku, Parabolic SAR, KDJ) covering trend/momentum/volatility/volume.
* Each entry: TR descriptions, parameter→effect glossary, formula, 10/10 confidence with rationale, suggested strategy template, references.
* Loader/dataclasses + YAML catalog mirror A's brokers/catalog pattern.
* `/api/indicators/catalog` + `/api/indicators/{id}`.
* zustand `useIndicatorStore` + `confidenceColor()` helper.
* `INDX` pane — searchable grid + detail view.

## Frozen contracts

* `IndicatorEntry.id` stable lookup key
* `confidence` int 1-10, UI tier-colored
* `parameters` is a list (ordering preserved)
* Routes: `/api/indicators/{catalog,/{id}}`

## Out of scope

E (strategy editor — needs compute engine), D (bot runner), G (templates), J (NL assistant), K (integrations).
