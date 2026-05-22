# Template bot library (Sub-system G)

**Date:** 2026-05-22
**Project:** showMe
**Depends on:** E (strategy spec + store), F (indicator catalog), D (bot runner)
**Status:** Design — auto-approved per `feedback_decisive`

## 1. Goal

Ship a curated library of starter strategy templates that users can instantiate with one click. Each template binds to a specific F indicator and uses its `suggested_strategy` block as the base + adds concrete parameter values, rule sets, and position sizing. The user picks a template, names it, picks a credential/symbol, and the runner is ready to go.

This is the "hazır template botlar" the user originally asked for.

## 2. Approach

**Curated YAML catalog** of templates, parallel to F's `indicators.yml`:

```yaml
- id: rsi-mean-revert
  name: "RSI Mean Reversion (klasik)"
  description: "RSI 30 altına düşünce long, 70 üstüne çıkınca close. Trend filtresiz."
  uses_indicators: [rsi]
  recommended_timeframe: "1h"
  recommended_symbols: ["BTC/USDT", "ETH/USDT"]
  applicability: "Ranging piyasada en iyi; güçlü trendde whipsaw — adx filtresi ekle (opsiyonel)."
  natural_language_explanation: |
    Bu strateji RSI'ın 30'un altına düştüğü an satın al sinyali verir; fiyat
    'aşırı satılmış' bölgeden çıkmaya başladığında yeni bir long pozisyon
    açar. RSI 70'in üzerine çıktığında pozisyonu kapatır — 'aşırı alım'
    sinyali. Klasik mean-reversion mantığı.
  math: |
    RSI(period=14) = 100 - 100 / (1 + RS)
    RS = ortalama_kazanç / ortalama_kayıp (Wilder smoothing)
    Sinyal: prev_RSI >= 30 AND current_RSI < 30 → long entry
            prev_RSI <= 70 AND current_RSI > 70 → close
  spec_template:
    name: "RSI Mean Reversion"
    description: "RSI 30/70 mean-revert template"
    timeframe: "1h"
    indicators:
      - alias: rsi14
        id: rsi
        params: {period: 14}
    entry_rules:
      - {kind: crosses_below, left: rsi14, right: "literal:30"}
    entry_logic: all
    exit_rules:
      - {kind: crosses_above, left: rsi14, right: "literal:70"}
    exit_logic: any
    position:
      side: long
      sizing_kind: fixed_quote
      sizing_value: 100
      stop_loss_pct: 2.0
```

The user picks a template in the UI, the system POSTs `spec_template` (with the user's name override) to `/api/strategies` — and they have a saved strategy ready to wire into D's BOT pane.

## 3. Template set (initial 12)

One template per major indicator family + a few combo strategies:

| # | id | base indicators | family |
|---|---|---|---|
| 1 | rsi-mean-revert | rsi | momentum mean-revert |
| 2 | macd-cross | macd | momentum trend |
| 3 | ema-crossover | ema (20/50) | trend |
| 4 | golden-cross | sma (50/200) | trend (long-term) |
| 5 | bb-squeeze-breakout | bollinger_bands + atr | volatility breakout |
| 6 | stoch-oversold | stochastic | momentum |
| 7 | adx-trend-filter | adx + ema | trend filter |
| 8 | vwap-pullback | vwap | intraday |
| 9 | ichimoku-cloud-break | ichimoku | trend |
| 10 | parabolic-trail | parabolic_sar | trailing stop |
| 11 | atr-volatility-breakout | atr + sma | breakout |
| 12 | williams-r-reverse | williams_r | momentum |

Each comes with full natural-language explanation, math walk-through, applicability notes.

## 4. Components

### 4.1 Backend

* `backend/showme/templates/__init__.py` (empty)
* `backend/showme/templates/catalog/__init__.py` (empty)
* `backend/showme/templates/catalog/templates.yml` — the 12 entries
* `backend/showme/templates/loader.py` — TemplateEntry / TemplateCatalog / load_template_catalog
* `backend/showme/server_routes/templates.py` — `GET /api/templates`, `GET /api/templates/{id}`, `POST /api/templates/{id}/instantiate` (creates a StrategySpec and saves it)

### 4.2 UI

* `ui/src/lib/template-store.ts` — load list, instantiate (POSTs to `/api/templates/{id}/instantiate`)
* `ui/src/functions/TMPL.tsx` — template browser:
  * Grid of template cards (name + family + uses_indicators chips)
  * Detail panel: applicability + NL explanation + math (collapsible) + suggested timeframes/symbols + "Bu template'i kullan" button
  * Clicking "Use" opens a small modal: name override + symbol + creates strategy + navigates to STRA pane with the new strategy loaded.

## 5. Out of scope

* Backtesting templates against historical data (defer)
* User-submitted templates (defer to K when external integrations exist)
* Cross-template parameter sweeps
* Performance leaderboard across templates

## 6. Acceptance criteria

* G1. 12 template entries; loader parses them; per-entry catalog validation against F's indicator ids.
* G2. `POST /api/templates/{id}/instantiate?name=...` returns a freshly saved StrategySpec.
* G3. TMPL pane renders grid + detail + Use button.
* G4. Using a template creates a strategy in the existing strategies store (verifiable via `GET /api/strategies`).
* G5. Backend + UI tests green; live curl walk-through.

## 7. Frozen contracts

* `TemplateEntry.id` stable lookup
* `spec_template` shape = subset of StrategySpec (id/timestamps stripped at instantiate-time)
* Routes: `/api/templates`, `/api/templates/{id}`, `/api/templates/{id}/instantiate`
* TMPL pane is a strategy launcher, not editor — users edit in STRA
