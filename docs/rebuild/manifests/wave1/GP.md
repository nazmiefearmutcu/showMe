# GP — Generic Price Chart

**Category:** charts_tech
**Asset classes:** equity, etf, crypto, fx, commodity, future, index
**Professional intent:** Inspect price action for any tradable instrument with candles/line, overlays, indicator studies, compare mode, and a fast symbol switcher — the workspace's default price chart.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| symbol | Symbol | symbol_picker | yes | AAPL | — | Canonical security identifier |
| range | Range | select | yes | 1Y | 1D, 5D, 1M, 3M, 6M, YTD, 1Y, 5Y, MAX | Lookback window |
| interval | Interval | select | yes | 1d | 1m,5m,15m,30m,1h,4h,1d,1wk,1mo | Bar interval (validated against range) |
| chart_kind | Chart | select | yes | candles | candles, line, area, hollow_candles | Render style |
| overlays | Overlays | multiselect | no | [SMA20, SMA50] | SMA20, SMA50, SMA200, EMA20, EMA50, EMA200, BB20_2, VWAP, IchimokuCloud | Price overlays |
| studies | Sub-pane studies | multiselect | no | [VOLUME] | VOLUME, RSI14, MACD_12_26_9, ATR14, OBV, STOCH_14_3_3, ADX14, ROC10 | Lower-pane indicators |
| compare | Compare with | symbol_picker | no | — | — | Second instrument to pin as overlay (normalized to 100 at range start) |
| provider_mode | Data mode | provider_mode | no | live_exchange | live_exchange, delayed_reference, cached_snapshot | Override provider preference |

`depends_on`: `interval` depends on `range` (1d intervals not allowed for 1D range, etc).

## Provider chain
- Primary: `binance` (when asset_class == crypto inferred from symbol)
- Primary alt: `yfinance_adapter` (for equity/etf/fx/commodity/index)
- Fallbacks: `cached_snapshot` (DuckDB cache)
- Acceptable modes: `live_exchange`, `delayed_reference`, `cached_snapshot`

## Output contract
- `must_have`: `["symbol", "candles", "as_of", "provider", "data_mode", "interval"]`
- `rows`: no
- `series`: yes (candles + overlays + study series)
- `cards`: yes (last price, change, change%, day range, volume)
- `warnings`: yes
- `next_actions`: yes (open HP, open DES, open FA, open CN, open OMON for options-eligible symbols)

## Chart grammar
- Kind: `time_series_candles` (or `time_series_line` if `chart_kind == "line"`)
- X axis: `{type: time, unit: ms, label: ""}`
- Y axis (price pane): `{type: numeric, unit: <quote_ccy>, label: "Price"}`
- Y axis (volume pane): `{type: numeric, unit: "", label: "Volume"}`
- Y axis (study panes): per-study
- Panes:
  - `{name: "price", series_kind: "candle", height_pct: 60}`
  - `{name: "volume", series_kind: "histogram", height_pct: 15}`
  - One pane per study at `height_pct: 25 / nStudies`
- Overlays: yes
- Compare: yes

## Card schema
| Slot | Label | Kind | Unit |
|------|-------|------|------|
| last_price | Last | big_number | quote_ccy |
| change | Change | trend_pill | quote_ccy |
| change_pct | Change % | trend_pill | % |
| day_range | Day Range | text | quote_ccy |
| volume_24h | Volume | kpi | shares/coins |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
GP fetches OHLCV bars from the primary provider for the chosen `interval` and `range`. Overlays are computed client-side from the returned candle series (SMA/EMA/BB/VWAP/Ichimoku are O(n) deterministic). Sub-pane studies are computed from the same series (RSI uses Wilder's smoothing; MACD uses 12/26/9 EMA; ATR uses Wilder; STOCH uses %K=14 %D=3 SMA; ADX uses 14-period DMI; OBV uses signed-volume cumsum). Compare mode normalizes both series to 100 at the first visible candle. The pane respects user pan/zoom across data refresh (first-seed-focus pattern). Live mode listens on the provider's WS stream and patches the last candle on tick.

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| SMA(n) | `SMA_t = (1/n) * Σ_{i=0}^{n-1} close_{t-i}` | n=period |
| EMA(n) | `EMA_t = α*close_t + (1-α)*EMA_{t-1}, α=2/(n+1)` | n=period |
| BB(n,k) | `BB_upper = SMA + k*σ, BB_lower = SMA - k*σ` | n=20, k=2, σ=rolling stdev |
| VWAP | `Σ(price*vol) / Σ(vol)` per session | — |
| RSI(14) | Wilder: `RSI = 100 - 100/(1+RS), RS = avg_gain/avg_loss` | period=14 |
| MACD | `MACD = EMA12 - EMA26; signal = EMA9(MACD)` | 12,26,9 |
| ATR(14) | Wilder: `TR = max(H-L, |H-C_prev|, |L-C_prev|); ATR = EMA(TR, 14)` | 14 |
| OBV | `OBV_t = OBV_{t-1} + sign(close_t - close_{t-1}) * volume_t` | — |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| candles[].t | epoch ms | Bar open time | provider |
| candles[].o | quote_ccy | Open price | provider |
| candles[].h | quote_ccy | High price | provider |
| candles[].l | quote_ccy | Low price | provider |
| candles[].c | quote_ccy | Close price | provider |
| candles[].v | base/quote | Volume in base or quote depending on adapter | provider |
| quote_ccy | — | Quote currency (USD, USDT, EUR) | provider exchange_info |
| change | quote_ccy | last - prev_close | computed |
| change_pct | % | change / prev_close * 100 | computed |
| day_range | quote_ccy | "L – H" of current session | computed |

## Provenance requirements
- Source list: required (e.g. `["binance"]` or `["yfinance"]`)
- As-of: required (ISO 8601 UTC, last bar close time or live tick time)
- Latency ms: required when mode == `live_exchange`

## Alerting
- Conditions: `price_above`, `price_below`, `change_pct_above`, `change_pct_below`, `volume_spike`
- Delivery: `tray`, `notification`, `log`

## Semantic tests
1. **gp_aapl_1y_1d_returns_real_candles** — Given `{symbol: AAPL, range: 1Y, interval: 1d}`, asserts: response has ≥200 candles, each with OHLC fields, monotonic time, all numeric, `provider` ∈ {yfinance, cached_snapshot}, no candle has `c == 0` or `h < l`.
2. **gp_btcusdt_1d_5m_uses_binance** — Given `{symbol: BTCUSDT, range: 1D, interval: 5m}`, asserts: `provider == "binance"`, `data_mode == "live_exchange"`, ≥250 candles.
3. **gp_invalid_interval_for_range_rejected** — Given `{symbol: AAPL, range: 1D, interval: 1d}`, asserts: response is 422 (validation error) OR returns degraded with a warning explaining the interval/range incompatibility — no silent success.
4. **gp_compare_overlay_normalized** — Given `{symbol: AAPL, compare: MSFT, range: 1Y}`, asserts: response includes a `compare_series` with same length as `candles`, first value == 100, all subsequent values are relative.
5. **gp_overlay_sma20_matches_formula** — Given `{symbol: AAPL, range: 6M, overlays: [SMA20]}`, asserts: 20th and onward overlay values equal the rolling mean of close to within 1e-9.
6. **gp_chart_grammar_is_candles_not_row_index** — Asserts the rendered chart's x-axis is time-based (manifest grammar `time_series_candles`) and NOT a row-index plot.
