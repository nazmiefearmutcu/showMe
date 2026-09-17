"""MEET — Meeting Briefings: world-events tracker.

The pane tracks scheduled world events (central-bank decisions, CPI, GDP,
… for every country on the keyless calendar) and country-tagged world
headlines (wars, elections, summits) in one grouped list: upcoming events
ascending with live countdowns, past events descending, a country index,
and spot alerts for rate decisions / wars. Primary provider is
``internal`` because the function orchestrates other adapters rather than
hitting a single feed.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AlertingSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def meet() -> FunctionManifest:
    return FunctionManifest(
        code="MEET",
        name="Meeting Briefings — World Events",
        category=Category.COMMS_PEOPLE,
        intent=(
            "Track the world's scheduled events in one pane — every country's"
            " calendar (rate decisions, CPI, GDP) plus country-tagged headlines"
            " (wars, elections, summits) — with UTC timestamps, affected FX"
            " pairs, live countdowns and spot alerts so nothing market-moving"
            " escapes the radar."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.INDEX,
            AssetClass.FX,
        ],
        inputs=[
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Comma-separated ISO codes / currency codes / country names"
                    " (e.g. \"TR,US,EU\"). A headline may concern several countries;"
                    " filtering keeps every row that touches any selected country."
                ),
            ),
            InputSpec(
                name="kind",
                label="Event kind",
                control=ControlKind.SELECT,
                required=False,
                options=["all", "economic", "world"],
                description="Restrict to scheduled calendar events, world headlines, or both.",
            ),
            InputSpec(
                name="mode",
                label="Mode",
                control=ControlKind.SELECT,
                required=False,
                options=["all", "calendar", "wire"],
                description="calendar=sadece ekonomik takvim (dünya teli çekilmez), wire=sadece dünya haber teli. Verilirse kind'i ezer (backward-compat).",
            ),
            InputSpec(
                name="tags",
                label="Tags",
                control=ControlKind.TEXT,
                required=False,
                description="Virgüllü etiket filtresi (BTC, FOMC...); title/summary/matched_assets/pairs içinde aranır.",
            ),
            InputSpec(
                name="data_filter",
                label="Data filter",
                control=ControlKind.SELECT,
                required=False,
                options=["all", "with_forecast", "with_actual", "surprise_only"],
                description="Sadece calendar satırlarına uygulanır.",
            ),
            InputSpec(
                name="symbols",
                label="Symbols",
                control=ControlKind.TEXT,
                required=False,
                description="Takip edilen semboller (BTCUSDT...); ülke/kind filtrelerinden bağımsız symbol_rows üretir. calendar modunda symbol feed çekilmez.",
            ),
            InputSpec(
                name="impact",
                label="Impact",
                control=ControlKind.MULTISELECT,
                required=False,
                options=["high", "medium", "low", "holiday"],
                description="Impact buckets to keep (empty = all).",
            ),
            InputSpec(
                name="query",
                label="Search",
                control=ControlKind.TEXT,
                required=False,
                description="Substring filter over titles, country names and affected pairs.",
            ),
            InputSpec(
                name="days_ahead",
                label="Days ahead",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Forward window. Upcoming events are always listed from now"
                    " until at least the nearest high-impact event; the keyless"
                    " weekly calendar publishes one week at a time."
                ),
                min=1,
                max=365,
                step=1,
                unit="d",
            ),
            InputSpec(
                name="days_back",
                label="Days back",
                control=ControlKind.NUMBER,
                required=False,
                description="Backward window for already-printed events.",
                min=0,
                max=90,
                step=1,
                unit="d",
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum rows returned after filtering.",
                min=10,
                max=1000,
                step=10,
            ),
            InputSpec(
                name="include_world",
                label="World headlines",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "Fetch the keyless world headline stream (GDELT, RSS fallback)"
                    " and tag it with the country gazetteer. Off = calendar only."
                ),
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
            InputSpec(
                name="since",
                label="Since",
                control=ControlKind.TEXT,
                required=False,
                description="Realtime delta cursor: the previous payload's as_of (ISO). Informational echo only; the diff is computed from known_ids.",
            ),
            InputSpec(
                name="known_ids",
                label="Known IDs",
                control=ControlKind.TEXT,
                required=False,
                description="Realtime delta baseline: comma-separated row ids the client already shows (cap 1000). Rows outside this set ship in new_rows (cap 50); baseline ids missing from the window ship in removed_ids (cap 200).",
            ),
        ],
        defaults={
            "kind": "all",
            "mode": "all",
            "tags": "",
            "data_filter": "all",
            "symbols": "",
            "since": "",
            "known_ids": "",
            "days_ahead": 90,
            "days_back": 7,
            "limit": 250,
            "include_world": True,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["forex_factory", "gdelt", "rss"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "rows", "country_index", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="when_utc", label="When (UTC)", kind="datetime", width_hint=170),
                ColumnSpec(key="kind", label="Kind", kind="tag", width_hint=80),
                ColumnSpec(key="impact", label="Impact", kind="tag", width_hint=90),
                ColumnSpec(key="countries", label="Countries", kind="text", width_hint=140),
                ColumnSpec(key="title", label="Event", kind="text"),
                ColumnSpec(key="pairs", label="Affected", kind="text", width_hint=180),
                ColumnSpec(key="source", label="Source", kind="tag", width_hint=110),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="next_high_impact", label="Next high impact", kind="big_number"),
                CardSlot(key="upcoming_count", label="Upcoming", kind="kpi"),
                CardSlot(key="past_count", label="Past", kind="kpi"),
                CardSlot(key="alerts_count", label="Spot alerts", kind="kpi"),
                CardSlot(key="countries_tracked", label="Countries", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MEET composes a WORLD-EVENTS TRACKER from the repo's existing keyless"
            " providers. Scheduled rows come from the ForexFactory weekly calendar"
            " (reused from ECO): every country on the calendar is listed with its"
            " offset-aware timestamp parsed to UTC, impact bucket, and affected FX"
            " pairs derived country → currency → majors (e.g. TR → USDTRY/EURTRY,"
            " US → DXY/EURUSD/USDJPY). World rows come from the keyless GDELT"
            " headline stream (English-language wire; RSS fallback), tagged with"
            " a country gazetteer; a"
            " headline may concern several countries and carries the exact matched"
            " terms in details.matched_terms so every attribution is auditable."
            " The window lists upcoming events ascending (from now until at least"
            " the nearest high-impact event) plus past events descending;"
            " seconds_to_event and age_minutes are computed server-side for UI"
            " parity while the live countdown ticks client-side. Central-bank"
            " decisions (Fed/TCMB/ECB/…) and wars are spot-flagged and exposed in"
            " alerts[] with default lead times the UI can override. When every"
            " provider fails the payload is a provider_unavailable envelope with"
            " EMPTY rows and a reason — no events are invented. mode selects"
            " calendar-only (the world wire is never fetched), wire-only or both"
            " and wins over kind; tags filters titles/summaries/matched assets"
            " and pairs; data_filter narrows calendar rows to prints carrying"
            " forecast/actual values."
        ),
        formula_dict={},
        field_dict={
            "rows[].when_utc": FieldDef(description="Event time in UTC, parsed from the provider's offset-aware timestamp.", source="forex_factory"),
            "rows[].seconds_to_event": FieldDef(unit="s", description="Server-computed seconds from as_of (negative = past); the UI renders the live countdown.", source="computed"),
            "rows[].countries": FieldDef(description="ISO codes; a row may concern several countries.", source="computed"),
            "rows[].pairs": FieldDef(description="Quoted FX pairs / indices affected via the country currency.", source="computed"),
            "rows[].spot": FieldDef(description="True for central-bank decisions and wars — the alert-worthy class.", source="computed"),
            "rows[].impact": FieldDef(description="high | medium | low | holiday.", source="forex_factory"),
            "rows[].details.matched_terms": FieldDef(description="Exact gazetteer terms that tagged a world headline.", source="computed"),
            "rows[].details.actual": FieldDef(description="Released value when available (Actual).", source="forex_factory"),
            "rows[].details.forecast": FieldDef(description="Consensus estimate when available (Forecast).", source="forex_factory"),
            "rows[].asset_tags": FieldDef(description="Asset tags (BTC, ETH, ETF...) matched in title/summary/provider tags and pairs.", source="computed"),
            "rows[].event_type": FieldDef(description="Classified event type (etf_flow, rate_decision, inflation_print, ...).", source="computed"),
            "rows[].details.asset_tags": FieldDef(description="Asset tags (BTC, ETH, ETF...) matched in title/summary/provider tags and pairs.", source="computed"),
            "rows[].details.event_type": FieldDef(description="Classified event type (etf_flow, rate_decision, inflation_print, ...).", source="computed"),
            "country_index[].state": FieldDef(description="local status pill: live | imminent | soon | scheduled | quiet.", source="computed"),
            "alerts[]": FieldDef(description="Upcoming spot/pinned events with default lead times (minutes).", source="computed"),
            "country_catalog[]": FieldDef(description="Static country reference (ISO + name) so filters are complete even when a provider is down.", source="reference"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "spot_event_lead_time_hit",
                "rate_decision_within_24h",
                "war_headline_high_impact",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="meet_country_filter_pins_rate_decisions",
                description=(
                    "Given {countries: ['TR']}, every economic row concerns TR and the"
                    " TCMB interest-rate decision is present with spot=true and the"
                    " affected pairs (USDTRY/EURTRY) — selecting a country never loses"
                    " its central-bank decision."
                ),
                inputs={"countries": ["TR"]},
                assertions=[
                    "every_economic_row_country_is_TR",
                    "tcmb_rate_decision_present",
                    "spot_flag_on_rate_decision",
                    "affected_pairs_include_usdtry",
                ],
            ),
            SemanticTest(
                name="meet_upcoming_and_past_ordering_with_server_countdowns",
                description=(
                    "Upcoming rows are ascending with seconds_to_event >= 0 and match"
                    " when_utc − as_of within tolerance; past rows are descending with"
                    " negative seconds_to_event and positive age_minutes."
                ),
                inputs={},
                assertions=[
                    "upcoming_ascending",
                    "past_descending",
                    "seconds_to_event_matches_when_utc",
                    "age_minutes_positive_for_past",
                ],
            ),
            SemanticTest(
                name="meet_world_rows_carry_matched_terms",
                description=(
                    "A world headline concerning several countries is tagged with every"
                    " country and each attribution carries the exact gazetteer term in"
                    " details.matched_terms — a headline never crosses into another"
                    " country's filter without a matched term."
                ),
                inputs={"_fixture": "multi_country_headline"},
                assertions=[
                    "multi_country_tags_allowed",
                    "every_country_has_matched_term",
                    "war_headlines_are_spot",
                ],
            ),
            SemanticTest(
                name="meet_empty_window_is_honest",
                description=(
                    "When every provider fails, the payload is provider_unavailable with"
                    " EMPTY rows and an explicit reason — the pane says so instead of"
                    " inventing events."
                ),
                inputs={"_mock": "all_providers_down"},
                assertions=[
                    "status_provider_unavailable",
                    "rows_empty",
                    "reason_mentions_provider",
                    "metadata_live_false",
                ],
            ),
            SemanticTest(
                name="meet_mode_calendar_hides_world",
                description=(
                    "Given {mode: 'calendar'}, the world wire is never fetched and only"
                    " economic calendar rows are listed — mode wins over kind."
                ),
                inputs={"mode": "calendar"},
                assertions=[
                    "world_provider_untouched",
                    "only_economic_rows",
                    "mode_wins_over_kind",
                ],
            ),
            SemanticTest(
                name="meet_tags_and_data_filter_narrow_rows",
                description=(
                    "Given {tags: 'BTC', data_filter: 'with_actual'}, rows carrying the"
                    " BTC tag remain and calendar rows without a released actual value"
                    " are dropped."
                ),
                inputs={"tags": "BTC", "data_filter": "with_actual"},
                assertions=[
                    "btc_tagged_rows_kept",
                    "actual_less_calendar_rows_dropped",
                ],
            ),
        ],
    )


__all__ = ["meet"]
