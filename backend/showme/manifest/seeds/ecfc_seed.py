"""ECFC — Economic Forecasts.

Multi-indicator, multi-year IMF World Economic Outlook projection table for a
given country, read from the keyless IMF DataMapper API. Every row is an IMF
projection; no value is modeled or filled in. The DataMapper publishes no WEO
edition or release date, so the vintage field names the source family only.
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
            "IMF World Economic Outlook forecast table per country from the keyless IMF "
            "DataMapper: GDP growth, inflation, unemployment, fiscal balance, government "
            "debt, with source and retrieval-time labels on every payload."
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
                    "GGXWDG_NGDP",
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
        ],
        defaults={
            "country": "USA",
            "indicators": ["NGDP_RPCH", "PCPIPCH", "LUR", "GGXCNL_NGDP", "GGXWDG_NGDP"],
            "years": 5,
        },
        provider_chain=ProviderChain(
            primary="imf",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.PROVIDER_UNAVAILABLE,
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
            "ECFC reads the IMF World Economic Outlook projection series for the requested "
            "country from the keyless IMF DataMapper API "
            "(imf.org/external/datamapper/api/v1/{indicator}/{country}). For each requested "
            "indicator the full per-country series is fetched and the forward years (current "
            "year onward, up to the requested horizon) are sliced out as rows. A year the API "
            "does not list for the country is omitted, never filled with a modeled value. Rows "
            "carry source_mode='imf_weo'. The DataMapper publishes no WEO edition or release "
            "date, so the top-level vintage names the source family only and as_of is the "
            "retrieval time. When the IMF request fails the pane reports provider_unavailable "
            "with the reason. Cards summarise the nearest-year forecast per indicator."
        ),
        field_dict={
            "country": FieldDef(description="Country code echoed back (ISO 3166-1 alpha-3 or IMF group code).", source="input"),
            "vintage": FieldDef(description="Source family 'imf_weo' (IMF WEO projections via DataMapper). No WEO edition or release date is exposed, so a forecast batch cannot be pinned.", source="imf datamapper"),
            "as_of": FieldDef(description="UTC time the IMF response was retrieved. This is a fetch time, not a WEO release date.", source="derived"),
            "rows[].indicator": FieldDef(description="IMF WEO indicator code.", source="imf datamapper"),
            "rows[].metric": FieldDef(description="Human-readable label.", source="reference"),
            "rows[].year": FieldDef(description="Forecast year (integer).", source="imf datamapper"),
            "rows[].forecast_value": FieldDef(unit="varies", description="IMF projection in the indicator's unit (see rows[].unit).", source="imf datamapper"),
            "rows[].unit": FieldDef(description="Display unit (% y/y, % of GDP, USD bn).", source="reference"),
            "rows[].vintage": FieldDef(description="Same source family as the top-level vintage ('imf_weo').", source="imf datamapper"),
            "rows[].source_mode": FieldDef(description="Always 'imf_weo' for returned rows; no modeled rows exist.", source="derived"),
            "source_mode": FieldDef(description="'imf_weo' for live rows, 'provider_unavailable' otherwise.", source="derived"),
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
                name="ecfc_missing_year_is_omitted_not_modeled",
                description="When the IMF series has no value for a forecast year, asserts no row is produced for that (indicator, year) and no modeled value is filled in.",
                inputs={"country": "USA", "_mock": "imf_missing_year"},
                assertions=[
                    "missing_year_absent_from_rows",
                    "no_row_has_modeled_source_mode",
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
