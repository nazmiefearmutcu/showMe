"""BTMM — Country Rate Environment (monetary policy regime view).

Focused manifest for the central-bank policy-rate monitor. Renders the
current policy rate, last move, and 3-month basis-point trend per bank,
with an implied-path overlay from WIRP so the analyst sees today's
policy stance against what the market is pricing forward.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    ColumnSpec,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def btmm() -> FunctionManifest:
    return FunctionManifest(
        code="BTMM",
        name="Country Rate Environment",
        category=Category.MACRO,
        intent=(
            "Show every major central bank's current policy rate, last move, and "
            "3-month basis-point trend in one matrix, with an optional implied-path "
            "overlay so the analyst sees today's policy stance against what the "
            "market is pricing forward."
        ),
        asset_classes=[AssetClass.RATE, AssetClass.BOND, AssetClass.FX],
        inputs=[
            InputSpec(
                name="country",
                label="Country",
                control=ControlKind.SELECT,
                required=False,
                description="ALL or a specific BIS-coded country (US, EU, GB, JP, TR, ...).",
                options=["ALL", "US", "EU", "GB", "JP", "TR"],
            ),
            InputSpec(
                name="region",
                label="Region",
                control=ControlKind.SELECT,
                required=False,
                description="Region or universe filter (g10, em, americas, europe, asia_pacific, mea, all).",
                options=["all", "g10", "em", "americas", "europe", "asia_pacific", "mea"],
            ),
            InputSpec(
                name="limit",
                label="Limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum rows to return after filtering and sorting.",
                min=1,
                max=100,
                step=1,
            ),
            InputSpec(
                name="overlay_implied_path",
                label="Implied path overlay",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, overlay WIRP-style market-implied policy path on the rate history pane.",
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
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "country": "ALL",
            "region": "all",
            "limit": 80,
            "overlay_implied_path": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=21600,
            scope="global",
            persist=True,
        ),
        output_contract=OutputContract(
            must_have=["rows", "summary", "as_of"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="iso8601", label="Date"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Policy rate"),
            panes=[
                PaneGrammar(name="policy_rate_history", series_kind="area", height_pct=100),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="country_code", label="Code", kind="tag"),
                ColumnSpec(key="country", label="Country", kind="text"),
                ColumnSpec(key="central_bank", label="Central bank", kind="text"),
                ColumnSpec(key="currency", label="Ccy", kind="tag"),
                ColumnSpec(key="policy_rate", label="Rate", kind="percent", unit="%", format="%.4f"),
                ColumnSpec(key="change_bp", label="Last move", kind="number", unit="bp", format="%.0f"),
                ColumnSpec(key="trend_3m_bp", label="3M bp", kind="number", unit="bp", format="%.0f"),
                ColumnSpec(key="last_move", label="Class", kind="tag"),
                ColumnSpec(key="as_of", label="As of", kind="date"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="average_policy_rate", label="Avg policy rate", kind="big_number", unit="%"),
                CardSlot(key="range", label="Range", kind="kpi", unit="%"),
                CardSlot(key="tilt", label="Tilt (H − C)", kind="trend_pill"),
                CardSlot(key="largest_last_move", label="Largest move", kind="badge", unit="bp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BTMM reads central-bank policy-rate series from BIS CBPOL (cached six hours) and "
            "augments each row with a 'last move' (latest rate minus the previous distinct rate, "
            "in basis points) and a '3M bp' (latest rate minus the observation on or before "
            "roughly 90 calendar days earlier). Country/region filters narrow the universe to "
            "G10, EM, Americas, Europe, APAC, or MEA. The summary KPIs include the average policy "
            "rate, the fresh-only min/max range (rows older than ~6 months excluded so a stale "
            "observation does not anchor the range), and a hike-vs-cut tilt. When "
            "overlay_implied_path is true, the chart overlays a market-implied forward policy "
            "path from the WIRP source so today's stance can be read against what futures price."
        ),
        formula_dict={
            "change_bp": Formula(
                expression=r"change_{bp} = (rate_{latest} - rate_{previous distinct}) \times 100",
                variables={
                    "rate_latest": "Latest BIS CBPOL observation (%)",
                    "rate_previous_distinct": "Most recent prior rate that differs from latest (%)",
                },
                notes="Last policy move in basis points.",
            ),
            "trend_3m_bp": Formula(
                expression=r"trend_{3m,bp} = (rate_{latest} - rate_{t-90d}) \times 100",
                variables={
                    "rate_latest": "Latest BIS CBPOL observation (%)",
                    "rate_{t-90d}": "Observation on or before ~90 calendar days earlier (%)",
                },
                notes="3-month change in basis points.",
            ),
        },
        field_dict={
            "country_code": FieldDef(description="Display country code (e.g. US, EU, GB).", source="curated"),
            "central_bank": FieldDef(description="Central bank name (e.g. Federal Reserve).", source="curated"),
            "currency": FieldDef(description="ISO 4217 currency code.", source="curated"),
            "policy_rate": FieldDef(unit="%", description="Latest central-bank policy rate.", source="BIS CBPOL"),
            "change_bp": FieldDef(unit="bp", description="Latest move vs prior distinct rate.", source="computed"),
            "trend_3m_bp": FieldDef(unit="bp", description="Change over roughly 90 calendar days.", source="computed"),
            "last_move": FieldDef(description="hike/cut/hold classification of the last change.", source="computed"),
            "as_of": FieldDef(unit="iso8601", description="Latest observation date from BIS CBPOL.", source="BIS CBPOL"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="btmm_returns_rows_for_all_countries_default",
                description="Default BTMM call returns at least one row with policy_rate, central_bank, and as_of.",
                inputs={"country": "ALL", "region": "all"},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_policy_rate",
                    "every_row_has_central_bank",
                    "every_row_has_as_of",
                ],
            ),
            SemanticTest(
                name="btmm_country_filter_isolates_single_bank",
                description="Filtering by country=US returns only the Fed row.",
                inputs={"country": "US"},
                assertions=[
                    "every_row_country_code_is_us",
                    "central_bank_is_federal_reserve",
                ],
            ),
            SemanticTest(
                name="btmm_last_move_classification_matches_change_bp_sign",
                description="last_move == 'hike' iff change_bp > 0, 'cut' iff <0, 'hold' iff ≈0.",
                inputs={"country": "ALL"},
                assertions=["last_move_sign_matches_change_bp"],
            ),
            SemanticTest(
                name="btmm_implied_path_overlay_present_when_requested",
                description=(
                    "When overlay_implied_path=true, the chart payload includes an implied_path "
                    "series alongside the historical policy_rate."
                ),
                inputs={"country": "US", "overlay_implied_path": True},
                assertions=["payload_includes_implied_path_when_overlay_true"],
            ),
            SemanticTest(
                name="btmm_summary_range_excludes_stale_rows",
                description=(
                    "Summary min/max policy rate ignores rows whose as_of is older than ~6 months, "
                    "so a forgotten 2022 observation does not anchor the range."
                ),
                inputs={"country": "ALL"},
                assertions=["summary_min_max_only_from_rows_fresher_than_183d"],
            ),
        ],
    )


__all__ = ["btmm"]
