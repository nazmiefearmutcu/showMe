# WIRP — World Interest Rate Probabilities (Cut/Hold/Hike)

**Category:** macro
**Asset classes:** rate, bond, fx
**Professional intent:** For each major central bank, show the market-implied probability distribution of the next rate decision (cut/hold/hike) and the path-implied terminal rate over the next 4 meetings — with the formula and inputs visible so an analyst can sanity-check or disagree.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| central_banks | Central banks | multiselect | yes | [Fed, ECB, BoE, BoJ, SNB, BoC, RBA] | full list | Which banks to show |
| meeting_horizon | Horizon | select | yes | next_4 | next_1, next_2, next_4, next_6, full_curve | How many forward meetings |
| source | Source | select | yes | sofr_futures | sofr_futures, ois, stir_futures, modeled | Probability inference source |
| as_of | As of | date_range | no | last_close | — | Anchor date |
| provider_mode | Data mode | provider_mode | no | live_official | live_official, delayed_reference, cached_snapshot | — |

## Provider chain
- Primary: `cme_sofr` for Fed (paid feed; if unavailable → cached_snapshot or modeled mode with explicit flag)
- Primary alt: `eonia_ois` / `sonia_ois` etc. for other banks (research feeds)
- Secondary: `fred` for current policy rate context (overnight rate series)
- Fallbacks: `cached_snapshot`, `modeled`
- Acceptable modes: `live_official`, `delayed_reference`, `cached_snapshot`, `modeled` (with warning)

## Output contract
- `must_have`: `["as_of", "banks", "data_mode"]`
- `rows`: no
- `series`: yes (`implied_path` per bank)
- `cards`: yes (per-bank: current rate, next meeting date, cut prob, hold prob, hike prob, expected magnitude bps)
- `warnings`: yes
- `next_actions`: yes (open ECO for upcoming meeting, open BTMM for monetary policy view, open ECST for related series)

## Card schema (per bank, repeated)

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| current_rate | Current Rate | big_number | % |
| next_meeting_date | Next Meeting | timestamp | — |
| p_cut | P(Cut) | kpi | % |
| p_hold | P(Hold) | kpi | % |
| p_hike | P(Hike) | kpi | % |
| expected_move_bps | Expected Δ | trend_pill | bps |
| terminal_rate | Terminal (4 mtg) | big_number | % |

## Chart grammar
- Kind: `bar_ladder` (per bank, vertical bars over forward meetings) PLUS sub-pane `time_series_line` for the implied policy path
- X axis (bars): `{type: category, unit: "", label: "Meeting"}`
- Y axis (bars): `{type: numeric, unit: "%", label: "Probability"}`
- X axis (line): `{type: time, unit: "", label: "Meeting date"}`
- Y axis (line): `{type: numeric, unit: "%", label: "Implied policy rate"}`
- Panes:
  - `{name: "stacked_probs", series_kind: "bar", height_pct: 60}` — stacked p_cut / p_hold / p_hike per meeting
  - `{name: "implied_path", series_kind: "line", height_pct: 40}` — implied rate trajectory
- Overlays: actual policy rate history overlay on the implied path
- Compare: no

## Methodology
For each central bank:
1. Get the current policy rate from `fred` (Fed Funds for US, etc.) and the dated forward meeting schedule from a curated `central_bank_calendar.yml` (committed in repo, manually maintained ~quarterly).
2. From the futures-implied curve at `as_of`, compute the implied policy rate at each forward meeting:
   - For Fed: average daily SOFR over the meeting period implied by the corresponding SOFR future.
   - For other banks: corresponding OIS / STIR futures.
3. Compute the implied change vs current rate at each meeting → `expected_move_bps`.
4. Probabilities: discretize the implied move into 25 bps buckets centered on integer multiples (standard market convention). For a meeting where the implied move is `m` bps, with assumed std `σ` of the implied path (default 5 bps, configurable in advanced):
   - P(hike of n×25 bps) = Φ((n + 0.5)/σ ratio) − Φ((n − 0.5)/σ ratio)
   - Cut = sum of negative-n probabilities; hold = P(|m| < 12.5); hike = sum of positive-n
5. Terminal rate at 4 meetings out is taken directly from the implied curve.

If primary source is unavailable, the system falls back to a published "modeled" path (e.g. last-good curve + small drift) and marks `data_mode = "modeled"` with a prominent warning.

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| Implied policy rate (Fed) | `r_implied = 100 − P_future + adjustment_for_avg_vs_eom` | from SOFR future price |
| Expected move | `Δ_bps = (r_implied − r_current) · 100` | bps |
| Bucket probability | normal CDF on quantized move buckets at 25 bps spacing | σ default 5 bps |
| Cut/Hold/Hike probability | sum of bucket probs by sign | — |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| banks[].name | — | Display name (e.g. "Federal Reserve") | calendar |
| banks[].code | — | Short code (Fed/ECB/BoE/...) | calendar |
| banks[].current_rate | % | Current policy rate | FRED / official |
| banks[].next_meeting_date | UTC | Scheduled date | calendar |
| banks[].implied_path[].meeting_date | UTC | Forward meeting | calendar + futures |
| banks[].implied_path[].implied_rate | % | Implied policy rate at meeting | futures |
| banks[].implied_path[].p_cut | [0,1] | Probability of cut | derived |
| banks[].implied_path[].p_hold | [0,1] | Probability of hold | derived |
| banks[].implied_path[].p_hike | [0,1] | Probability of hike | derived |

## Provenance requirements
- Source list: required (`["cme_sofr", "fred", "modeled_fallback"]`)
- As-of: required
- Latency ms: required when mode == `live_official`

## Semantic tests
1. **wirp_probs_sum_to_one** — For every meeting in every bank's implied_path, assert `p_cut + p_hold + p_hike ≈ 1.0 ± 1e-6`.
2. **wirp_current_rate_from_fred_for_fed** — Mock FRED returning current Fed Funds rate. Assert `banks[Fed].current_rate` matches.
3. **wirp_modeled_mode_warns_explicitly** — Mock SOFR futures provider down. Assert `data_mode == "modeled"`, warning present mentioning "live futures unavailable".
4. **wirp_no_provider_returns_unavailable_not_synthetic** — Mock all providers down. Assert `data_mode == "provider_unavailable"`, NO synthetic probabilities. Banks array may still have `name`, `code`, `current_rate` from cache but `implied_path == []`.
5. **wirp_implied_path_monotonic_in_time** — Assert `implied_path` is sorted ascending by `meeting_date`.
6. **wirp_terminal_rate_matches_4th_implied** — Assert reported `terminal_rate` equals `implied_path[3].implied_rate` (or last entry if horizon < next_4).
