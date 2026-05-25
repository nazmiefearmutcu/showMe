# GEX — Gamma Exposure (Strike Ladder + Walls + Flip)

**Category:** derivatives
**Asset classes:** option, equity, index, etf
**Professional intent:** Show dealer/MM gamma exposure by strike for a chosen underlying so a trader can identify gamma walls, the gamma flip point, and exposure regimes that affect realized volatility behavior — with explicit model assumptions visible.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| underlying | Underlying | symbol_picker | yes | SPY | options-eligible | Equity/ETF/index ticker |
| expiry_filter | Expirations | multiselect | yes | [next_3] | next_1, next_3, next_6, weekly_only, monthly_only, all | Which expiries to include |
| oi_source | OI Source | select | yes | exchange | exchange, modeled | Where Open Interest comes from |
| risk_free | Risk-free | number | yes | 0.045 | 0–0.10 | r used in BSM gamma calc |
| dividend_yield | Div Yield | number | yes | 0.015 | 0–0.10 | q used in BSM gamma calc |
| iv_source | IV Source | select | yes | market | market, modeled_vol_surface, fixed_30d_atm | Implied vol source |
| dealer_assumption | Dealer Side | select | yes | short_calls_long_puts | short_calls_long_puts, sticky_strike, sticky_delta, neutral | Convention for who's net short γ |
| as_of | As of | date_range | no | last_close | — | Snapshot time |
| provider_mode | Data mode | provider_mode | no | delayed_reference | live_official, delayed_reference, cached_snapshot | — |

## Provider chain
- Primary: `cboe_options` (paid; if not configured → `provider_unavailable`)
- Secondary: `yfinance_adapter` (chain via `Ticker.option_chain` — delayed/free)
- Tertiary: `cached_snapshot`
- Acceptable modes: `live_official`, `delayed_reference`, `cached_snapshot`, `provider_unavailable`

## Output contract
- `must_have`: `["underlying", "spot", "as_of", "strikes", "data_mode", "iv_source", "dealer_assumption"]`
- `rows`: no
- `series`: yes (`gex_by_strike` bar series; optional `cumulative_gex_curve`)
- `cards`: yes (gamma flip strike, largest call wall, largest put wall, net GEX, spot)
- `warnings`: yes
- `next_actions`: yes (open OMON for full chain, open IVOL for surface, open HVT for realized vol context)

## Chart grammar
- Kind: `bar_ladder` (vertical strike ladder)
- X axis: `{type: numeric, unit: "GEX $/1%", label: "Gamma exposure"}`
- Y axis: `{type: numeric, unit: "$", label: "Strike"}` (strikes ascending)
- Panes:
  - `{name: "gex_bars", series_kind: "bar", height_pct: 75}` — diverging bars (call γ right, put γ left, signed)
  - `{name: "cumulative", series_kind: "line", height_pct: 25}` — cumulative gamma vs strike, with zero-cross at gamma flip
- Overlays: spot price reference line; largest wall annotations
- Compare: no

## Card schema

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| spot | Spot | big_number | $ |
| net_gex | Net GEX | trend_pill | $/1% |
| gamma_flip | Gamma Flip | big_number | $ |
| largest_call_wall | Call Wall | kpi | $ |
| largest_put_wall | Put Wall | kpi | $ |
| iv_source | IV Source | badge | — |
| dealer_assumption | Dealer | badge | — |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
GEX is computed strike-by-strike from the option chain. For each strike K and option O (call or put) with open interest OI(O), implied vol σ(O), days-to-expiry T(O):
1. Compute Black-Scholes-Merton gamma `γ(S, K, T, σ, r, q)`.
2. Per-contract dollar gamma: `γ * S^2 * contract_multiplier * 0.01` (the $/1% convention).
3. Dealer-signed gamma: under `short_calls_long_puts` convention, dealers are short calls and long puts → call γ contribution is positive (dealers need to hedge by buying as price rises → suppresses realized vol when net γ > 0), put γ contribution is negative on the dealer book.
4. Aggregate by strike across selected expiries.
5. Gamma flip = strike where cumulative signed γ from low → high crosses zero.
6. Call/Put walls = strikes with largest absolute call γ / put γ.

Model assumptions are visible (not hidden). If IV source is `fixed_30d_atm`, all strikes use a single ATM 30D IV (transparent simplification — flagged as a warning that this loses skew). If `modeled_vol_surface`, IV is computed from the live surface (requires IVOL infra). If `market`, IV is the chain's bid/ask mid IV per contract (most accurate but noisy at illiquid strikes).

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| BSM gamma | `γ = ϕ(d1) / (S σ √T)` where `d1 = (ln(S/K) + (r − q + σ²/2) T) / (σ √T)` | S, K, T, σ, r, q |
| Dollar gamma | `Γ_$ = γ · S² · 100 · 0.01` | per contract, $/1% |
| Dealer-signed | `signed_γ = +Γ_$(call) − Γ_$(put)` under standard dealer-short-calls assumption | — |
| Gamma flip | first strike K* where `Σ_{K ≤ K*} signed_γ ≥ 0` and prev `< 0` | — |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| spot | $ | Current underlying price | quote provider |
| strikes[].strike | $ | Strike price | option chain |
| strikes[].call_gex | $/1% | Aggregated call dealer γ at strike | computed |
| strikes[].put_gex | $/1% | Aggregated put dealer γ at strike | computed |
| strikes[].signed_gex | $/1% | call_gex − put_gex | computed |
| strikes[].oi_call | contracts | Call OI summed across selected expiries | option chain |
| strikes[].oi_put | contracts | Put OI summed across selected expiries | option chain |
| cumulative_gex_curve[].strike | $ | Strike | derived |
| cumulative_gex_curve[].cum_gex | $/1% | Running Σ signed_gex from lowest strike | derived |
| net_gex | $/1% | Σ signed_gex | derived |
| gamma_flip | $ | First strike where cumulative crosses zero | derived |

## Provenance requirements
- Source list: required (provider + IV source)
- As-of: required
- Latency ms: required when mode == `live_official`

## Alerting
- Conditions: `spot_crosses_gamma_flip`, `net_gex_sign_change`, `wall_breached`
- Delivery: `tray`, `notification`

## Semantic tests
1. **gex_spy_strike_ladder_real_axis** — Given `{underlying: SPY, expiry_filter: next_3}`, asserts: chart x-axis is strike-based (not row-index), every bar has a numeric strike, strikes are sorted ascending.
2. **gex_gamma_flip_consistent_with_cumulative** — Asserts the reported `gamma_flip` strike equals the first cumulative_gex_curve point where `cum_gex` crosses zero.
3. **gex_bsm_gamma_matches_reference** — For a known (S=100, K=100, T=30/365, σ=0.2, r=0.04, q=0), asserts computed γ matches the BSM closed-form value to within 1e-6.
4. **gex_no_provider_returns_unavailable_not_silent_zero** — Mock no provider configured. Asserts `data_mode == "not_configured"` (or `provider_unavailable`), `strikes == []`, warning explains missing config — NOT a zero-strike chart pretending to be live.
5. **gex_dealer_assumption_changes_sign** — Same inputs with `dealer_assumption: short_calls_long_puts` vs `neutral` should yield different signed_gex; assert net_gex differs.
6. **gex_fixed_30d_atm_warns_about_skew_loss** — Given `{iv_source: fixed_30d_atm}`, asserts a warning is present mentioning "skew not modeled".
