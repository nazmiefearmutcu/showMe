# PORT — Canonical Portfolio Workspace

**Category:** portfolio
**Asset classes:** equity, etf, crypto, fx, commodity, bond, future, option
**Professional intent:** The single source of truth for what you own across all connected accounts — positions with cost basis, realized + unrealized PnL, cash, financing, exposure breakdown, transaction history, with live quote overlays that reconcile visibly against the ledger.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| accounts | Accounts | multiselect | no | [ALL] | dynamic from credential vault | Filter to specific connected accounts; ALL aggregates |
| as_of | As of | date_range | no | today | — | Snapshot date; default = live |
| group_by | Group by | select | yes | asset_class | account, asset_class, sector, currency, none | Roll-up dimension |
| show_zero | Show closed positions | boolean | no | false | — | Include positions with qty=0 (history) |
| ccy | Base currency | select | yes | USD | USD, EUR, GBP, TRY, JPY | Reporting currency |
| provider_mode | Data mode | provider_mode | no | live_exchange | live_exchange, cached_snapshot | — |

## Provider chain
- Primary: `ccxt_broker` (live positions per credential) + `binance` / `yfinance_adapter` (live quotes)
- Fallbacks: `cached_snapshot` (last good portfolio snapshot from DuckDB)
- Acceptable modes: `live_exchange`, `cached_snapshot`

## Output contract
- `must_have`: `["as_of", "ccy", "totals", "groups", "positions", "data_mode"]`
- `rows`: no (positions is structured, not generic rows)
- `series`: yes (equity_curve for the requested range)
- `cards`: yes (total equity, cash, day PnL, unrealized PnL, realized PnL YTD, exposure %)
- `warnings`: yes (per-account reconciliation diffs, stale quotes, etc.)
- `next_actions`: yes (open TLH for tax-loss harvesting, open REBA for rebalance, open PORT_OPT for optimization)

## Table schema (positions)

| Column | Label | Kind | Unit | Format |
|--------|-------|------|------|--------|
| symbol | Symbol | text | — | — |
| name | Name | text | — | — |
| account | Account | tag | — | — |
| qty | Qty | number | shares/coins | %.6g |
| avg_cost | Avg Cost | currency | ccy | %.2f |
| last | Last | currency | ccy | %.2f |
| market_value | Mkt Value | currency | ccy | %.0f |
| weight | Weight | percent | % | %.2f |
| unrealized | Unrealized | currency | ccy | %.0f |
| unrealized_pct | Unrealized % | percent | % | %.2f |
| day_change | Day Δ | currency | ccy | %.0f |
| day_change_pct | Day Δ% | percent | % | %.2f |
| asset_class | Class | tag | — | — |
| as_of | As of | datetime | — | — |
| actions | — | action | — | — |

## Card schema (header)

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| total_equity | Total Equity | big_number | ccy |
| cash | Cash | kpi | ccy |
| day_pnl | Day PnL | trend_pill | ccy |
| unrealized_pnl | Unrealized | trend_pill | ccy |
| realized_pnl_ytd | Realized YTD | kpi | ccy |
| equity_in_pos | In Position | kpi | % |
| as_of | As of | timestamp | — |
| data_mode | Mode | mode_pill | — |

## Chart grammar (equity curve sub-component)
- Kind: `time_series_line`
- X axis: `{type: time, unit: ms, label: ""}`
- Y axis: `{type: numeric, unit: ccy, label: "Equity"}`
- Compare: yes (benchmark overlay e.g. SPY)

## Methodology
PORT aggregates positions across all enabled credentials in the exchange vault. For each credential, it fetches live positions via the broker's `account()` and `positions()` calls, joins with live quotes from the appropriate market data adapter, and computes:
- `market_value = qty * last`
- `unrealized = (last - avg_cost) * qty` (sign-aware for shorts)
- `unrealized_pct = unrealized / (avg_cost * |qty|) * 100`
- `day_change = (last - prev_close) * qty`
- `weight = market_value / total_market_value * 100`
Currency conversion uses the FX adapter (cached intraday). Equity curve is reconstructed from snapshot history in DuckDB (one snapshot per minute when sidecar is running). Realized PnL YTD is summed from broker transaction history (fetched on first load, cached, incrementally updated). Reconciliation diffs between broker-reported equity and computed market_value are surfaced as warnings (not silently absorbed).

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| MarketValue | `mv = qty * last_price` | — |
| Unrealized | `u = (last - avg_cost) * qty` (sign-aware for short) | — |
| Weight | `w = mv / Σ_i mv_i * 100` | — |
| DayChange | `dc = (last - prev_close) * qty` | — |
| Exposure | `exposure = Σ |mv_position| / total_equity` | — |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| positions[].qty | base | Position size in base currency | broker |
| positions[].avg_cost | quote | Volume-weighted average cost | broker |
| positions[].last | quote | Last traded price | market adapter |
| totals.total_equity | ccy | Cash + Σ position market values, converted to base ccy | computed |
| totals.day_pnl | ccy | Σ position day_change, sign-aware | computed |
| equity_curve[].t | epoch ms | Snapshot time | snapshot store |
| equity_curve[].equity | ccy | Equity at that snapshot | snapshot store |

## Provenance requirements
- Source list: required (list of credentials + market adapter names)
- As-of: required
- Latency ms: required when mode == `live_exchange`

## Alerting
- Conditions: `equity_drawdown_pct`, `position_unrealized_loss_pct`, `cash_below`, `concentration_above`
- Delivery: `tray`, `notification`, `log`

## Semantic tests
1. **port_zero_credentials_returns_empty_with_explanation** — No credentials in vault. Asserts `totals.total_equity == 0`, `positions == []`, `warnings` includes "no credentials configured", `data_mode == "not_configured"`.
2. **port_one_credential_aggregates_correctly** — Mock one credential with two positions. Asserts totals == sum of positions, weights sum to ~100%, day_pnl matches per-position day_change sum.
3. **port_currency_conversion_round_trip** — Mock EUR-denominated position with USD base ccy. Asserts market_value in USD = qty * last * fx_rate, fx_rate provenance recorded.
4. **port_reconciliation_diff_surfaced** — Mock broker reports equity that disagrees by 0.5% from computed market_value. Asserts a warning is present in `warnings` array.
5. **port_equity_curve_monotonic_time** — Asserts `equity_curve` timestamps are strictly increasing.
6. **port_no_silent_zero_qty_positions_when_show_zero_false** — Asserts no rows with qty==0 unless `show_zero: true`.
