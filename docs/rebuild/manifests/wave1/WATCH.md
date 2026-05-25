# WATCH — Operator-Grade Watchlist

**Category:** screening
**Asset classes:** equity, etf, crypto, fx, commodity, future, index, bond
**Professional intent:** A first-class global watchlist that holds named instruments across all asset classes, shows live quotes + sparklines + alerts, supports drag-reorder + multi-list + bulk-actions, and is the canonical context other panes (GP/HP/DES/FA/CN) subscribe to for symbol selection.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| list_id | List | select | yes | default | dynamic from store | Active watchlist (multi-list supported) |
| sort_by | Sort | select | yes | manual | manual, day_change_pct_desc, day_change_pct_asc, last_price_asc, last_price_desc, volume_desc, alpha | Row order |
| show_sparklines | Sparklines | boolean | yes | true | — | 5d intraday spark in each row |
| sparkline_window | Spark Window | select | no | 1D | 1D, 5D, 1M | What sparkline covers |
| show_alerts | Show alert chips | boolean | yes | true | — | Show alert state per row |
| provider_mode | Data mode | provider_mode | no | live_exchange | live_exchange, delayed_reference, cached_snapshot | — |

## Provider chain
- Primary per row: `binance` for crypto symbols, `yfinance_adapter` for non-crypto (fast_info + small history for spark)
- Aggregation: client-side; backend exposes `POST /api/watch/quote-bulk` that fans out per-symbol to the appropriate adapter
- Fallbacks: `cached_snapshot`
- Acceptable modes: `live_exchange`, `delayed_reference`, `cached_snapshot`

## Output contract
- `must_have`: `["as_of", "list_id", "rows", "data_mode"]`
- `rows`: yes
- `series`: no (sparklines are embedded per-row payloads, not a global series)
- `cards`: yes (list size, advancers/decliners/unchanged, top mover)
- `warnings`: yes (stale per-symbol; quota issues)
- `next_actions`: yes (open GP for symbol, open DES, open CN, set alert)

## Table schema

| Column | Label | Kind | Unit | Format |
|--------|-------|------|------|--------|
| symbol | Symbol | text | — | — |
| name | Name | text | — | — |
| last | Last | currency | ccy | %.2f |
| change | Δ | currency | ccy | %.2f |
| change_pct | Δ% | percent | % | %.2f |
| spark | Spark | tag (custom) | — | — |
| volume | Vol | number | shares/coins | si |
| asset_class | Class | tag | — | — |
| alert_count | Alerts | number | — | %d |
| as_of | As of | datetime | — | rel |
| actions | — | action | — | — |

## Card schema (header)

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| list_size | Symbols | kpi | — |
| advancers | Up | kpi | — |
| decliners | Down | kpi | — |
| unchanged | Flat | kpi | — |
| top_mover | Top Mover | trend_pill | % |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
WATCH is backed by a persistent store in DuckDB (`watch_lists` and `watch_items` tables). The frontend `useWatchStore` (Zustand) reflects this state and is mounted globally so other panes can subscribe to "selected symbol" or "list contents". On render, the pane sends the current list's symbols to `POST /api/watch/quote-bulk`. The backend:
1. Buckets symbols by `asset_class` (inferred from symbol shape: crypto if matches `^[A-Z0-9]{2,10}USDT?$` or known base/quote pair; equity otherwise).
2. For each bucket, fans out per-adapter with concurrency cap (default 8).
3. Each row returns `{symbol, last, prev_close, change, change_pct, volume, sparkline: [close,...], as_of, source, latency_ms}`.
4. Rows where adapter fails return `{symbol, error: "<reason>", as_of}` instead of fabricated zeros — UI shows an error chip, not a synthetic green/red.

Drag-reorder updates the store immediately; persisted on next interval. Alerts are a separate concern (managed by ALRT pane); WATCH only displays count + chip indicator.

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| rows[].symbol | — | Canonical symbol | store |
| rows[].name | — | Display name (resolved via OpenFIGI on first add, cached) | OpenFIGI |
| rows[].last | quote_ccy | Last price | adapter |
| rows[].prev_close | quote_ccy | Previous close | adapter |
| rows[].sparkline | quote_ccy[] | Intraday close array (length depends on window) | adapter history |
| rows[].asset_class | — | Tag | inferred or stored |
| rows[].error | — | Per-row error reason if adapter failed | adapter |

## Provenance requirements
- Source list: required (per row, since multi-adapter)
- As-of: required (per row + aggregate)
- Latency ms: required when mode == `live_exchange`

## Alerting
- Conditions: handled by ALRT; WATCH displays count per row
- Delivery: handled by ALRT

## Semantic tests
1. **watch_empty_list_returns_empty_rows_not_error** — Given empty list. Asserts `rows == []`, `list_size == 0`, no error.
2. **watch_per_row_error_does_not_fake_quote** — Mock yfinance failing for "ZZZZZZ". Asserts that row has `error` field, NO synthetic `last` or `change`.
3. **watch_crypto_routed_to_binance_equity_to_yfinance** — Mock symbols `["BTCUSDT", "AAPL"]`. Asserts BTCUSDT row's `source == "binance"`, AAPL row's `source == "yfinance"`.
4. **watch_sparkline_length_matches_window** — Given `{sparkline_window: 5D}`, asserts sparkline length is consistent with 5D × bars-per-day for the chosen interval.
5. **watch_sort_by_day_change_pct_desc_is_actually_sorted** — Given mixed rows. Asserts rows are monotonically decreasing in `change_pct`.
6. **watch_reorder_persists_across_reload** — Add 3 symbols, reorder, save snapshot, reload. Asserts order persists.
