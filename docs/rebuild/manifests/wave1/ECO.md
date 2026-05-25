# ECO — Economic Event Calendar

**Category:** macro
**Asset classes:** rate, fx, equity, commodity, bond (cross-asset relevance)
**Professional intent:** A real economic event calendar with country, importance, consensus, previous, actual, surprise, and alerting — surfaces what's hitting the tape today and what's queued for the week, with surprise scoring and post-release reactions.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| countries | Countries | multiselect | no | [US, EZ, GB, JP, CN, TR] | ISO 3166-1 alpha-2 list | Filter; empty = all |
| importance | Importance | multiselect | yes | [high, medium] | low, medium, high | Releases by impact |
| date_range | Window | date_range | yes | today→+7d | -30d to +30d | Lookback + lookforward |
| categories | Categories | multiselect | no | [cpi, gdp, employment, central_bank, pmi, retail_sales, trade_balance] | full enum | Release type filter |
| show_only_with_actual | Only released | boolean | no | false | — | Hide unreleased rows |
| provider_mode | Data mode | provider_mode | no | live_official | live_official, delayed_reference | — |

## Provider chain
- Primary: `fred` (US macro releases with vintage support via FRED)
- Secondary: `economic_calendar_rss` (composite RSS-backed calendar, internal aggregator, for non-US)
- Fallbacks: `cached_snapshot`
- Acceptable modes: `live_official`, `delayed_reference`, `cached_snapshot`

## Output contract
- `must_have`: `["as_of", "events", "data_mode"]`
- `rows`: yes (events as table rows)
- `series`: no
- `cards`: yes (next high-impact, surprise leader today, biggest surprise last 24h)
- `warnings`: yes (e.g. "calendar feed partial for EZ")
- `next_actions`: yes (open ECST for the series, open WIRP if central bank event)

## Table schema

| Column | Label | Kind | Unit | Format |
|--------|-------|------|------|--------|
| time_utc | Time | datetime | — | yyyy-MM-dd HH:mm |
| country | Country | tag | — | — |
| importance | Imp | tag | — | high/med/low |
| name | Event | text | — | — |
| category | Cat | tag | — | — |
| previous | Prev | number | unit | %.2f |
| consensus | Cons | number | unit | %.2f |
| actual | Actual | number | unit | %.2f |
| surprise | Surprise | percent | σ | %.2f |
| surprise_class | — | tag | — | beat/in_line/miss |
| revision | Rev | number | unit | %.2f |
| series_id | Series | text | — | — |
| actions | — | action | — | — |

## Card schema

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| next_high_impact | Next High-Impact | big_number | — |
| countdown | In | kpi | duration |
| surprise_leader_today | Top Surprise (today) | trend_pill | σ |
| biggest_surprise_24h | Biggest 24h | trend_pill | σ |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
ECO pulls releases from FRED's `release_dates` and `series_observations` endpoints for series in a curated whitelist (CPI YoY, Core CPI, PCE, NFP, Unemployment, GDP QoQ saar, ISM Manufacturing, ISM Services, Retail Sales MoM, FOMC rate, ECB rate, BoE rate, BoJ rate, China CPI, China PMI, Turkey CPI, etc — see `ECO_SERIES.md` for the full mapping). For each series, the most recent observation becomes `actual`; the previous becomes `previous`; consensus is sourced from the calendar RSS aggregator when available (no fabrication if unavailable — leave null + warning). Surprise is computed as `(actual - consensus) / stdev_actual_last_24m` (standardized). `surprise_class` is `beat` if |surprise| < 0.5σ else direction-aware. Revisions to the previous print are flagged in `revision`. The unreleased portion of the window comes from the calendar feed (forward schedule only — no actual values).

## Formulas
| Name | Expression | Variables |
|------|------------|-----------|
| Surprise | `(actual - consensus) / σ_24m` where σ_24m = stdev of actual over last 24 months | — |
| Beat/Miss | `class = "beat" if (actual−consensus)>0 and importance bias positive, else "miss"` | depends on category |

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| events[].time_utc | UTC | Scheduled or released time | calendar feed / FRED release_dates |
| events[].importance | — | Editorial importance | curated whitelist |
| events[].actual | unit | Released value | FRED |
| events[].consensus | unit | Survey median | calendar RSS (null if unavailable) |
| events[].previous | unit | Prior period | FRED |
| events[].revision | unit | Δ to prior published previous value | FRED |
| events[].surprise | σ | Standardized surprise | computed |

## Provenance requirements
- Source list: required (`["fred", "economic_calendar_rss"]`)
- As-of: required
- Latency ms: required when mode == `live_official`

## Alerting
- Conditions: `release_in_15min`, `surprise_above_2sigma`, `revision_above_threshold`
- Delivery: `tray`, `notification`

## Semantic tests
1. **eco_today_us_returns_real_events** — Given `{countries: [US], date_range: today→+1d}`, asserts: response has ≥0 events, every event has `time_utc`, `name`, `category`, `importance`; no event has `actual` for a `time_utc > now`.
2. **eco_consensus_null_when_unavailable_with_warning** — Mock RSS down. Asserts events with no consensus have `consensus == null` and a warning is present saying "consensus unavailable for N events".
3. **eco_surprise_is_standardized** — For a series with known σ_24m, given a known actual + consensus, asserts surprise matches `(a-c)/σ` to within 1e-6.
4. **eco_filter_importance_high_excludes_low** — Given `{importance: [high]}`, asserts every returned event has `importance == "high"`.
5. **eco_no_silent_synthetic_consensus** — Asserts never that `consensus == previous` (a known synthetic shortcut); if `consensus == null` it must be explicit, not faked.
6. **eco_revision_field_populated_when_fred_shows_diff** — Mock FRED vintages showing a revised previous value. Asserts `revision` is non-zero and signed.
