"""COUN — Country Workbook.

One-page macro view per country: policy rate, inflation, unemployment,
GDP growth, fiscal balance, debt-to-GDP, 10y yield, currency. Combines a
curated country reference profile with live FRED series and the BTMM
policy row for the country's central bank. Every metric is live or an
explicit unavailable row with its reason; no reference values are served.
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
def coun() -> FunctionManifest:
    return FunctionManifest(
        code="COUN",
        name="Country Workbook",
        category=Category.MACRO,
        intent=(
            "One-page macro workbook per country — policy rate, inflation, "
            "unemployment, GDP growth, fiscal balance, debt-to-GDP, 10y yield, "
            "currency — combining live FRED "
            "series and the BTMM policy row for the country's central bank."
        ),
        asset_classes=[
            AssetClass.RATE,
            AssetClass.BOND,
            AssetClass.FX,
        ],
        inputs=[
            InputSpec(
                name="country",
                label="Country",
                control=ControlKind.SELECT,
                required=True,
                description="ISO 3166-1 alpha-2 country code. Unknown codes get no reference values and an explicit needs_input state.",
                options=["US", "EU", "GB", "TR", "JP", "CN", "BR", "IN"],
            ),
            InputSpec(
                name="metrics",
                label="Metrics",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Subset of metrics to render; empty = all sections.",
                options=[
                    "policy_rate",
                    "inflation",
                    "unemployment",
                    "gdp_growth",
                    "debt_to_gdp",
                    "fiscal_balance",
                    "ten_year_yield",
                    "currency",
                ],
            ),
            InputSpec(
                name="live",
                label="Live overlay",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true (default), fetch the live BTMM policy row and FRED series. When false, every metric is an explicit unavailable row.",
            ),
        ],
        defaults={
            "country": "US",
            "metrics": [],
            "live": True,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["country", "rows", "cards", "source_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="section", label="Section", kind="tag"),
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.2f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
                ColumnSpec(key="as_of", label="As of", kind="date"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="policy_rate", label="Policy Rate", kind="big_number", unit="%"),
                CardSlot(key="inflation", label="Inflation", kind="kpi", unit="% y/y"),
                CardSlot(key="unemployment", label="Unemployment", kind="kpi", unit="%"),
                CardSlot(key="gdp_growth", label="GDP Growth", kind="kpi", unit="%"),
                CardSlot(key="ten_year_yield", label="10Y Yield", kind="kpi", unit="%"),
                CardSlot(key="currency", label="Currency", kind="badge"),
                CardSlot(key="source_mode", label="Mode", kind="mode_pill"),
            ],
        ),
        methodology=(
            "COUN composes the workbook from live providers only. (1) BTMM's policy row is fetched "
            "for the country's central bank. (2) FRED series mapped per country (US: GDPC1, CPIAUCSL, "
            "UNRATE, DGS10; EU: LRHUTTTTEZQ156S, the euro-area aggregate; GB: GBRCPIALLMINMEI; "
            "TR: NGDPRSAXDCTRQ) are normalized via ECST. Inflation and real GDP growth are computed "
            "as year-over-year changes from the level series. (3) A metric with no live series, or a "
            "provider that failed, is an explicit row with value null, source_mode provider_unavailable "
            "and a reason. An observation older than its series limit is flagged stale, keeps its "
            "as-of date and is not counted as live. Unknown countries get no reference values, only an "
            "explicit needs_input state with a reason."
        ),
        field_dict={
            "country": FieldDef(description="Country code echoed back.", source="input"),
            "rows[].section": FieldDef(description="Logical grouping (rates / prices / labor / growth / fiscal).", source="reference"),
            "rows[].metric": FieldDef(description="Human-readable label.", source="reference"),
            "rows[].value": FieldDef(unit="varies", description="Latest live value in the row's unit; null when unavailable.", source="fred / btmm"),
            "rows[].as_of": FieldDef(unit="iso8601", description="Provider date when available.", source="fred"),
            "rows[].source_mode": FieldDef(description="Which provider produced the row (fred / btmm), or provider_unavailable with a reason.", source="derived"),
            "rows[].stale": FieldDef(description="True when the latest observation is older than its series limit; shown with its as-of date, not live.", source="derived"),
            "source_mode": FieldDef(description="Top-level mode for the workbook payload.", source="derived"),
            "country_known": FieldDef(description="True when the requested country is in the curated country set (US, EU, GB, TR).", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="coun_us_returns_rows_with_section_and_unit",
                description="Given country=US, asserts rows contains policy/inflation/unemployment/growth entries with section, metric, value, unit, source_mode.",
                inputs={"country": "US"},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_section",
                    "every_row_has_unit",
                    "every_row_has_source_mode",
                ],
            ),
            SemanticTest(
                name="coun_unknown_country_warns_fallback",
                description="Given an unknown country code, asserts a warning is present mentioning fallback and country_known is false.",
                inputs={"country": "ZZ"},
                assertions=[
                    "warning_mentions_fallback_profile",
                    "country_known_is_false",
                ],
            ),
            SemanticTest(
                name="coun_live_overlay_uses_real_provider",
                description="With live=true, asserts source_mode is live_macro when any FRED/BTMM provider returns fresh data; never relabels a gap or a stale row as live.",
                inputs={"country": "US", "live": True},
                assertions=[
                    "source_mode_reflects_actual_provider",
                    "no_silent_reference_relabel",
                ],
            ),
        ],
    )


__all__ = ["coun"]
