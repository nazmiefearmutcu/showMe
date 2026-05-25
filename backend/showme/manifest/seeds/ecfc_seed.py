"""ECFC — Economic Forecasts.

IMF/OECD-style multi-indicator multi-year forecast table for a given
country. Surfaces both the forecast vintage and the source mode so an
analyst can tell at a glance whether a 2027 GDP growth row is an IMF
WEO Oct vintage, an OECD interim projection, or a modeled fallback.
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
def ecfc() -> FunctionManifest:
    return FunctionManifest(
        code="ECFC",
        name="Economic Forecasts",
        category=Category.MACRO,
        intent=(
            "IMF/OECD-style multi-indicator multi-year forecast table per country — "
            "GDP growth, inflation, unemployment, current account, fiscal balance — "
            "with explicit forecast vintage and source-mode chips so analysts can "
            "tell a live IMF WEO row from an internally modeled fallback."
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
                description="ISO 3166-1 alpha-3 country code (USA, EUR, GBR, TUR, CHN, JPN, BRA, IND, ...).",
                options=["USA", "EUR", "GBR", "TUR", "CHN", "JPN", "BRA", "IND"],
            ),
            InputSpec(
                name="indicators",
                label="Indicators",
                control=ControlKind.MULTISELECT,
                required=False,
                description="IMF WEO / OECD indicator codes; empty = curated default set.",
                options=[
                    "NGDP_RPCH",
                    "PCPIPCH",
                    "LUR",
                    "BCA_NGDPD",
                    "GGXCNL_NGDP",
                    "NGDPD",
                ],
            ),
            InputSpec(
                name="years",
                label="Years",
                control=ControlKind.NUMBER,
                required=False,
                description="How many forecast years to render (1-6).",
                min=1,
                max=6,
                step=1,
            ),
            InputSpec(
                name="vintage",
                label="Vintage",
                control=ControlKind.SELECT,
                required=False,
                description="Forecast publication vintage to pin (latest = newest available).",
                options=["latest", "weo_oct", "weo_apr", "oecd_jun", "oecd_nov"],
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
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "country": "USA",
            "indicators": ["NGDP_RPCH", "PCPIPCH", "LUR"],
            "years": 5,
            "vintage": "latest",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["internal", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["country", "rows", "vintage", "source_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="indicator", label="Indicator", kind="tag"),
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="year", label="Year", kind="number", format="%d"),
                ColumnSpec(key="forecast_value", label="Forecast", kind="number", format="%.2f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
                ColumnSpec(key="vintage", label="Vintage", kind="tag"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="country", label="Country", kind="badge"),
                CardSlot(key="vintage", label="Vintage", kind="badge"),
                CardSlot(key="indicator_count", label="Indicators", kind="kpi"),
                CardSlot(key="year_count", label="Years", kind="kpi"),
                CardSlot(key="source_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ECFC builds the forecast table by querying FRED's IMF WEO + OECD release series for "
            "the requested country and indicator set, then aligning every (indicator, year) row "
            "to a single vintage label so the analyst can pin the publication batch. The vintage "
            "is read straight from the FRED release_dates metadata — never inferred from row "
            "values. When FRED has no row for a (country, indicator, year) tuple the internal "
            "fallback fills the cell with a modeled projection AND tags source_mode='modeled'; "
            "the response also surfaces a warning naming every modeled row so it can't pass as "
            "a live IMF row. Cards summarise indicator + year coverage and surface the dominant "
            "source_mode and as_of timestamp. The forecast vintage is visible in the payload as "
            "both the top-level `vintage` field and per-row `vintage` cell."
        ),
        field_dict={
            "country": FieldDef(description="Country code echoed back (ISO 3166-1 alpha-3).", source="input"),
            "vintage": FieldDef(description="Top-level forecast vintage label (e.g. weo_oct_2025).", source="fred release_dates"),
            "rows[].indicator": FieldDef(description="IMF WEO / OECD indicator code.", source="fred"),
            "rows[].metric": FieldDef(description="Human-readable label.", source="reference"),
            "rows[].year": FieldDef(description="Forecast year (integer).", source="fred"),
            "rows[].forecast_value": FieldDef(unit="varies", description="Forecast value in the indicator's native unit.", source="fred / internal"),
            "rows[].unit": FieldDef(description="Display unit (% YoY, % of GDP, etc.).", source="reference"),
            "rows[].vintage": FieldDef(description="Per-row forecast vintage (matches top-level vintage for live rows).", source="fred"),
            "rows[].source_mode": FieldDef(description="Per-row source mode (imf_oecd / modeled / cached_snapshot).", source="derived"),
            "source_mode": FieldDef(description="Dominant source mode for the payload.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ecfc_vintage_visible_in_payload",
                description="Asserts the response payload exposes both a top-level `vintage` field and per-row `vintage` cells, so the forecast batch is identifiable without round-tripping to the provider.",
                inputs={"country": "USA"},
                assertions=[
                    "payload_has_top_level_vintage",
                    "every_row_has_vintage_field",
                ],
            ),
            SemanticTest(
                name="ecfc_modeled_rows_are_tagged",
                description="When FRED has no live row for a tuple, asserts the modeled fallback row carries source_mode='modeled' and a warning names the modeled row count.",
                inputs={"country": "USA", "_mock": "fred_partial"},
                assertions=[
                    "modeled_rows_carry_source_mode_modeled",
                    "warning_mentions_modeled_row_count",
                ],
            ),
            SemanticTest(
                name="ecfc_year_count_matches_input",
                description="With years=5, asserts each indicator yields at most 5 forecast rows.",
                inputs={"country": "USA", "years": 5},
                assertions=["year_count_per_indicator_le_input"],
            ),
        ],
    )


__all__ = ["ecfc"]
