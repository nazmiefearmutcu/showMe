# CORR — Correlation Heatmap (Real Heatmap, Not Row-Index Plot)

**Category:** portfolio
**Asset classes:** equity, etf, crypto, fx, commodity, bond, index
**Professional intent:** Show pairwise return correlations across a chosen universe over a chosen window with method controls (Pearson/Spearman/Kendall, return type, frequency, horizon) — visualized as an actual heatmap with hover details and an exportable correlation matrix.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| universe | Universe | multiselect | yes | [] | symbols from WATCH or PORT or custom add | Set of instruments to correlate |
| method | Method | select | yes | pearson | pearson, spearman, kendall | Correlation kernel |
| return_type | Returns | select | yes | log | log, simple | Return definition |
| frequency | Frequency | select | yes | 1d | 1h, 1d, 1wk, 1mo | Return sampling |
| window | Window | select | yes | 90d | 30d, 60d, 90d, 180d, 1Y, 2Y, 5Y | Lookback for correlation computation |
| min_overlap | Min observations | number | yes | 30 | 10–500 | Reject pairs with fewer overlapping bars |
| as_of | As of | date_range | no | today | — | Anchor date |
| provider_mode | Data mode | provider_mode | no | delayed_reference | live_exchange, delayed_reference, cached_snapshot | — |

`depends_on`: `min_overlap` depends on `frequency` (suggested defaults change with freq).

## Provider chain
- Primary: `binance` for crypto rows, `yfinance_adapter` for non-crypto rows (histories pulled in parallel)
- Caching: heavy use of DuckDB cache (correlations on a fixed universe + window are deterministic and re-usable across sessions)
- Fallbacks: `cached_snapshot`
- Acceptable modes: `live_exchange`, `delayed_reference`, `cached_snapshot`

## Output contract
- `must_have`: `["as_of", "symbols", "matrix", "method", "frequency", "window", "data_mode"]`
- `rows`: no (matrix is structured)
- `series`: no
- `cards`: yes (universe size, highest pair, lowest pair, average abs correlation)
- `warnings`: yes (pairs rejected for insufficient overlap, etc.)
- `next_actions`: yes (open PORT_OPT with this universe, open BLAK, drilldown into a pair's rolling correlation)

## Chart grammar
- Kind: `heatmap`  ← **NOT row-index plot**
- X axis: `{type: category, unit: "", label: "Symbol"}`
- Y axis: `{type: category, unit: "", label: "Symbol"}`
- Panes: single heatmap pane
- Cells: color-mapped to correlation value [-1, +1] via diverging palette (red-white-blue or domain-customized)
- Overlays: none
- Compare: no (could be added as side-by-side panels in v2)

## Card schema

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| universe_size | N | kpi | — |
| highest_pair | Highest | big_number | ρ |
| highest_pair_label | — | text | — |
| lowest_pair | Lowest | big_number | ρ |
| lowest_pair_label | — | text | — |
| avg_abs_corr | Avg \|ρ\| | kpi | — |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
For each instrument in `universe`, CORR fetches close prices at `frequency` for the `window` ending at `as_of`. Returns are computed per `return_type`:
- `log`: `r_t = ln(p_t / p_{t-1})`
- `simple`: `r_t = (p_t - p_{t-1}) / p_{t-1}`

Returns matrix is aligned (asof-joined) to a common time index. Pairs with fewer than `min_overlap` observations after alignment are rejected and surfaced as warnings. The correlation matrix is computed with the chosen `method` (Pearson uses Pearson product-moment; Spearman uses rank correlation; Kendall uses Kendall's τ). The output matrix is symmetric with 1.0 on the diagonal. Heatmap visualization uses a diverging color scale anchored at 0 (no correlation), with deep red at -1 and deep blue at +1 (or theme-customizable).

This is explicitly NOT a row-index scatter: x and y axes are the universe symbols (categorical), not the bar index of the return series.

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| Pearson | `ρ(X,Y) = cov(X,Y) / (σ_X σ_Y)` | — |
| Spearman | `ρ_s = 1 - 6 Σ d²_i / (n(n²-1))` (rank correlation) | d_i = rank diff |
| Kendall τ | `τ = (n_c - n_d) / (n(n-1)/2)` | n_c = concordant pairs, n_d = discordant |
| Log return | `r_t = ln(p_t) - ln(p_{t-1})` | — |
| Average \|ρ\| | `(1 / (N(N-1))) Σ_{i≠j} |ρ_ij|` | exclude diagonal |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| symbols | — | Ordered list of N symbols (matrix row/column labels) | input |
| matrix | — | N×N float; cell[i][j] = ρ(symbols[i], symbols[j]) | computed |
| pair_overlap[i][j] | bars | Number of observations used for that pair | derived |
| rejected_pairs | — | list of (i,j, reason) | derived |

## Provenance requirements
- Source list: required (which adapters supplied which symbols)
- As-of: required
- Latency ms: required when mode == `live_exchange`

## Semantic tests
1. **corr_chart_grammar_is_heatmap_not_row_index** — Asserts manifest.chart_grammar.kind == "heatmap"; asserts handler response includes a `matrix` field and not a row-index series.
2. **corr_diagonal_is_one** — Given any universe. Asserts `matrix[i][i] == 1.0 ± 1e-12` for all i.
3. **corr_symmetric** — Asserts `matrix[i][j] == matrix[j][i]` for all i,j.
4. **corr_two_perfectly_correlated_returns_pearson_one** — Mock universe `[A, B]` with B's returns == A's returns. Asserts `ρ(A,B) == 1.0 ± 1e-9`.
5. **corr_insufficient_overlap_rejected_with_warning** — Mock universe with one symbol having only 5 observations and `min_overlap=30`. Asserts pair is rejected and warning is present.
6. **corr_method_changes_result** — Given a non-linear monotonic relationship. Asserts Pearson and Spearman yield materially different values.
