"""ECO — Economic Event Calendar.

Encodes the wave1 ECO spec verbatim: cross-asset calendar with country,
importance, consensus, previous, actual, surprise, and alerting. The
events array is the core deliverable, with cards summarising the next
high-impact, today's surprise leader, and the biggest 24h surprise.
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
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def eco() -> FunctionManifest:
    return FunctionManifest(
        code="ECO",
        name="Economic Event Calendar",
        category=Category.MACRO,
        intent=(
            "A real economic event calendar with country, importance, "
            "consensus, previous, actual, surprise, and alerting — surfaces "
            "what's hitting the tape today and what's queued for the week, "
            "with surprise scoring and post-release reactions."
        ),
        asset_classes=[
            AssetClass.RATE,
            AssetClass.FX,
            AssetClass.EQUITY,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.MULTISELECT,
                required=False,
                description="ISO 3166-1 alpha-2 list. Empty = all countries.",
                options=["US", "EZ", "GB", "JP", "CN", "TR"],
            ),
            InputSpec(
                name="importance",
                label="Importance",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Filter releases by editorial impact.",
                options=["low", "medium", "high"],
            ),
            InputSpec(
                name="date_range",
                label="Window",
                control=ControlKind.DATE_RANGE,
                required=True,
                description="Lookback + lookforward window (-30d to +30d).",
            ),
            InputSpec(
                name="categories",
                label="Categories",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Release type filter.",
                options=[
                    "cpi",
                    "gdp",
                    "employment",
                    "central_bank",
                    "pmi",
                    "retail_sales",
                    "trade_balance",
                ],
            ),
            InputSpec(
                name="show_only_with_actual",
                label="Only released",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Hide unreleased rows.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                ],
            ),
        ],
        defaults={
            "countries": ["US", "EZ", "GB", "JP", "CN", "TR"],
            "importance": ["high", "medium"],
            "date_range": "today_to_plus_7d",
            "categories": [
                "cpi",
                "gdp",
                "employment",
                "central_bank",
                "pmi",
                "retail_sales",
                "trade_balance",
            ],
            "show_only_with_actual": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["economic_calendar_rss", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=300,
            scope="per_input",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["as_of", "events", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="time_utc", label="Time", kind="datetime", format="yyyy-MM-dd HH:mm"),
                ColumnSpec(key="country", label="Country", kind="tag"),
                ColumnSpec(key="importance", label="Imp", kind="tag"),
                ColumnSpec(key="name", label="Event", kind="text"),
                ColumnSpec(key="category", label="Cat", kind="tag"),
                ColumnSpec(key="previous", label="Prev", kind="number", unit="unit", format="%.2f"),
                ColumnSpec(key="consensus", label="Cons", kind="number", unit="unit", format="%.2f"),
                ColumnSpec(key="actual", label="Actual", kind="number", unit="unit", format="%.2f"),
                ColumnSpec(key="surprise", label="Surprise", kind="percent", unit="σ", format="%.2f"),
                ColumnSpec(key="surprise_class", label="Class", kind="tag"),
                ColumnSpec(key="revision", label="Rev", kind="number", unit="unit", format="%.2f"),
                ColumnSpec(key="series_id", label="Series", kind="text"),
                ColumnSpec(key="actions", label="Actions", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="next_high_impact", label="Next High-Impact", kind="big_number"),
                CardSlot(key="countdown", label="In", kind="kpi", unit="duration"),
                CardSlot(key="surprise_leader_today", label="Top Surprise (today)", kind="trend_pill", unit="σ"),
                CardSlot(key="biggest_surprise_24h", label="Biggest 24h", kind="trend_pill", unit="σ"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ECO pulls releases from FRED's release_dates and series_observations endpoints "
            "for series in a curated whitelist (CPI YoY, Core CPI, PCE, NFP, Unemployment, "
            "GDP QoQ saar, ISM Manufacturing, ISM Services, Retail Sales MoM, FOMC rate, "
            "ECB rate, BoE rate, BoJ rate, China CPI, China PMI, Turkey CPI, etc — see "
            "ECO_SERIES.md for the full mapping). For each series, the most recent observation "
            "becomes `actual`; the previous becomes `previous`; consensus is sourced from the "
            "calendar RSS aggregator when available (no fabrication if unavailable — leave null "
            "+ warning). Surprise is computed as (actual - consensus) / stdev_actual_last_24m "
            "(standardized). `surprise_class` is `beat` if |surprise| < 0.5σ else direction-aware. "
            "Revisions to the previous print are flagged in `revision`. The unreleased portion of "
            "the window comes from the calendar feed (forward schedule only — no actual values)."
        ),
        formula_dict={
            "surprise": Formula(
                expression=r"surprise = \frac{actual - consensus}{\sigma_{24m}}",
                variables={
                    "actual": "Released value",
                    "consensus": "Survey median",
                    "sigma_{24m}": "Standard deviation of actual over last 24 months",
                },
                notes="Standardized surprise in units of historical σ.",
            ),
            "beat_miss": Formula(
                expression=(
                    r"class = \begin{cases} \text{beat} & (actual-consensus) > 0 \text{ and importance bias positive} "
                    r"\\ \text{miss} & \text{otherwise} \end{cases}"
                ),
                variables={
                    "actual": "Released value",
                    "consensus": "Survey median",
                },
                notes="Beat/miss classification depends on the release category's directional bias.",
            ),
        },
        field_dict={
            "events[].time_utc": FieldDef(
                unit="UTC",
                description="Scheduled or released time.",
                source="calendar feed / FRED release_dates",
            ),
            "events[].importance": FieldDef(
                description="Editorial importance.",
                source="curated whitelist",
            ),
            "events[].actual": FieldDef(unit="unit", description="Released value.", source="fred"),
            "events[].consensus": FieldDef(
                unit="unit",
                description="Survey median (null if unavailable).",
                source="economic_calendar_rss",
            ),
            "events[].previous": FieldDef(unit="unit", description="Prior period.", source="fred"),
            "events[].revision": FieldDef(
                unit="unit",
                description="Delta to prior published previous value.",
                source="fred",
            ),
            "events[].surprise": FieldDef(
                unit="σ",
                description="Standardized surprise.",
                source="computed",
            ),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "release_in_15min",
                "surprise_above_2sigma",
                "revision_above_threshold",
            ],
            delivery=["tray", "notification"],
        ),
        semantic_tests=[
            SemanticTest(
                name="eco_today_us_returns_real_events",
                description=(
                    "Given {countries: [US], date_range: today→+1d}, asserts response has ≥0 "
                    "events, every event has time_utc, name, category, importance; no event "
                    "has actual for a time_utc > now."
                ),
                inputs={"countries": ["US"], "date_range": "today_to_plus_1d"},
                assertions=[
                    "events_array_present",
                    "every_event_has_time_utc",
                    "every_event_has_name",
                    "every_event_has_category",
                    "every_event_has_importance",
                    "no_actual_for_future_time_utc",
                ],
            ),
            SemanticTest(
                name="eco_consensus_null_when_unavailable_with_warning",
                description=(
                    "Mock RSS down. Asserts events with no consensus have consensus == null and "
                    "a warning is present saying 'consensus unavailable for N events'."
                ),
                inputs={"_mock": "rss_down"},
                assertions=[
                    "consensus_null_when_unavailable",
                    "warning_mentions_consensus_unavailable",
                ],
            ),
            SemanticTest(
                name="eco_surprise_is_standardized",
                description=(
                    "For a series with known σ_24m, given a known actual + consensus, asserts "
                    "surprise matches (a-c)/σ to within 1e-6."
                ),
                inputs={"_fixture": "known_sigma_series"},
                assertions=["surprise_matches_formula_within_1e-6"],
            ),
            SemanticTest(
                name="eco_filter_importance_high_excludes_low",
                description="Given {importance: [high]}, asserts every returned event has importance == 'high'.",
                inputs={"importance": ["high"]},
                assertions=["every_event_importance_is_high"],
            ),
            SemanticTest(
                name="eco_no_silent_synthetic_consensus",
                description=(
                    "Asserts never that consensus == previous (a known synthetic shortcut); if "
                    "consensus == null it must be explicit, not faked."
                ),
                inputs={},
                assertions=["consensus_never_equals_previous_silently"],
            ),
            SemanticTest(
                name="eco_revision_field_populated_when_fred_shows_diff",
                description=(
                    "Mock FRED vintages showing a revised previous value. Asserts revision is "
                    "non-zero and signed."
                ),
                inputs={"_mock": "fred_revised_previous"},
                assertions=["revision_non_zero", "revision_is_signed"],
            ),
        ],
    )


__all__ = ["eco"]
