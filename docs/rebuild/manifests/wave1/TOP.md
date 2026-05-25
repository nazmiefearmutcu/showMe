# TOP — Top News (Cross-Asset, Freshness-Aware, Deduped, Impact-Scored)

**Category:** news_intel
**Asset classes:** equity, etf, crypto, fx, commodity, bond, rate, index
**Professional intent:** A live top-news pane that surfaces what's actually moving markets right now across all asset classes, with deduplication, freshness windows, source provenance, optional sentiment/impact scoring, and one-click drilldowns into CN/DES/GP per ticker.

## Inputs

| Name | Label | Control | Required | Default | Range/Options | Description |
|------|-------|---------|----------|---------|---------------|-------------|
| freshness | Freshness | select | yes | 6h | 15m, 1h, 6h, 24h, 7d | Max age of items to surface |
| asset_filter | Asset classes | multiselect | no | [all] | equity, crypto, fx, commodity, bond, rate, macro | Filter feed by tagged asset class |
| topic_filter | Topics | multiselect | no | [] | earnings, m&a, central_bank, geopolitics, regulatory, macro, crypto_protocol | Editorial topic filter |
| min_impact | Min impact | select | no | low | low, medium, high | Filter by computed market-impact score |
| dedupe | Dedupe similar | boolean | yes | true | — | Cluster near-duplicate stories |
| sentiment_overlay | Sentiment | boolean | no | true | — | Show FinBERT pos/neu/neg labels |
| provider_mode | Data mode | provider_mode | no | live_official | live_official, delayed_reference, cached_snapshot | — |

## Provider chain
- Primary: `gdelt` (DOC 2.0, last 24h artlist mode)
- Secondary: `rss_news` (aggregated official feeds: SEC, Federal Reserve, ECB, BoE, BoJ, IMF, BIS, Reuters business, Bloomberg, Financial Times, CoinDesk, etc — curated whitelist in `news_sources.yml`)
- Tertiary: `cached_snapshot`
- Acceptable modes: `live_official`, `delayed_reference`, `cached_snapshot`

## Output contract
- `must_have`: `["as_of", "items", "data_mode"]`
- `rows`: yes (items as table-style cards)
- `series`: no
- `cards`: yes (item count by freshness bucket, sources active count, top-impact summary)
- `warnings`: yes (e.g. "GDELT rate-limited; using RSS only")
- `next_actions`: yes (open CN for tagged ticker, open ASK to summarize)

## Table schema (items rendered as feed)

| Column | Label | Kind | Unit | Format |
|--------|-------|------|------|--------|
| published_utc | Time | datetime | — | rel-time |
| source | Source | tag | — | — |
| title | Title | text | — | — |
| tickers | Tickers | tag | — | comma list |
| asset_class | Class | tag | — | — |
| topic | Topic | tag | — | — |
| sentiment | Sentiment | tag | — | pos/neu/neg |
| sentiment_score | Score | number | [-1,1] | %.2f |
| impact | Impact | tag | — | high/med/low |
| dedupe_cluster_size | Dup × | number | — | %d |
| link | — | action | — | — |

## Card schema

| Slot | Label | Kind | Unit |
|------|-------|------|------|
| total_items | Total | kpi | — |
| high_impact_count | High Impact | kpi | — |
| sources_active | Sources | kpi | — |
| top_topic | Top Topic | badge | — |
| data_mode | Mode | mode_pill | — |
| as_of | As of | timestamp | — |

## Methodology
TOP runs a unified ingestion pipeline:
1. **Fetch** — GDELT DOC search (English, top-domain whitelist), then parallel RSS pulls from a curated list of official + reputable financial sources.
2. **Normalize** — every item becomes `{published_utc, source, title, body_snippet, url, raw_tickers, raw_topics}`.
3. **Ticker tagging** — fast NER-lite (regex + cashtag detection + known-symbol dictionary maintained in DuckDB).
4. **Asset class tagging** — symbol → asset_class map (OpenFIGI-backed for ambiguous cases).
5. **Topic tagging** — keyword classifier on title+snippet (e.g. "FOMC", "ECB", "merger" → topic).
6. **Sentiment** — FinBERT inference on title + first 200 chars; outputs pos/neu/neg + score.
7. **Impact score** — heuristic combining: source authority weight (e.g. Fed press release > random blog), topic weight (central bank > earnings preview), sentiment magnitude, freshness decay. Returns `low|medium|high`.
8. **Dedupe** — SimHash on title (4-shingle) + URL-domain check; near-duplicates collapse into a cluster, surfaced count `dedupe_cluster_size`.
9. **Freshness gate** — drop items older than `freshness` input.
10. **Filter** — by asset class, topic, impact.
11. **Sort** — by `published_utc desc` (tie-break by `impact desc`).

No item is surfaced without a verifiable source URL. Items where ticker tagging is uncertain show empty `tickers` rather than guessing.

## Field dictionary
| Field | Unit | Description | Source |
|-------|------|-------------|--------|
| items[].published_utc | UTC | Original publication time | feed |
| items[].source | — | Source domain (e.g. reuters.com) | derived |
| items[].title | — | Headline | feed |
| items[].tickers | — | Detected tickers (canonicalized) | NER + dictionary |
| items[].sentiment | — | FinBERT label | FinBERT |
| items[].sentiment_score | [-1,1] | (pos − neg) normalized | FinBERT |
| items[].impact | — | Heuristic impact bucket | scorer |
| items[].dedupe_cluster_size | count | How many near-duplicates merged into this representative | SimHash |
| items[].link | URL | Original article URL | feed |

## Provenance requirements
- Source list: required (list of feed domains contributing to current window)
- As-of: required (oldest item time, newest item time)
- Latency ms: required when mode == `live_official`

## Alerting
- Conditions: `new_high_impact_for_tickers`, `central_bank_press_release`, `regulatory_action_for_tickers`
- Delivery: `tray`, `notification`, `log`

## Semantic tests
1. **top_returns_items_within_freshness_window** — Given `{freshness: 6h}`, asserts every returned item has `published_utc >= now - 6h`.
2. **top_dedupe_collapses_duplicates** — Mock two near-identical headlines from different sources. Asserts single representative item with `dedupe_cluster_size == 2`.
3. **top_no_silent_ticker_guess** — Mock an item with ambiguous "Apple of his eye" text. Asserts `tickers == []` (not `["AAPL"]` guessed wrongly).
4. **top_sentiment_uses_finbert_not_placeholder** — Asserts `sentiment_score` distribution across a known set of bull/bear test headlines matches FinBERT reference scores.
5. **top_filter_impact_high_excludes_low** — Given `{min_impact: high}`, asserts every item has `impact == "high"`.
6. **top_no_stale_or_synthetic_rows_when_providers_down** — Mock both GDELT and RSS down. Asserts `items == []`, `data_mode == "provider_unavailable"`, warning explains both providers failed — NOT a synthetic placeholder feed.
