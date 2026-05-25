"""COUN — Country Workbook.

One-page macro view per country: policy rate, inflation, unemployment,
GDP growth, fiscal balance, debt-to-GDP, 10y yield, currency. Combines a
curated country reference profile with live FRED series and the BTMM
policy row for the country's central bank.
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
            "currency — combining a curated reference profile with live FRED "
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
                description="ISO 3166-1 alpha-2 country code. Unknown codes fall back to a generic reference profile with a warning.",
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
                description="When true, overlay live FRED + BTMM data on the reference profile.",
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
            "country": "US",
            "metrics": [],
            "live": True,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["country_reference_profile", "cached_snapshot"],
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
            "COUN composes the workbook from three layers. (1) A curated country reference "
            "profile in showme.engine.functions.macro.coun ships baseline values for US, EU, GB, "
            "and TR; unknown countries get a generic fallback plus a warning that the profile is "
            "non-curated. (2) When live=true, BTMM's policy row is fetched for the country's "
            "central bank and overlays the reference policy_rate. (3) FRED series mapped per "
            "country (US: GDPC1/CPIAUCSL/UNRATE/DGS10; EU: LRHUTTTTEZQ156S; GB: GBRCPIALLMINMEI; "
            "TR: TURGDPRQDSMEI) are normalized via ECST and overlay the matching rows. Each row "
            "carries its actual source_mode so the analyst can see which numbers came from live "
            "FRED, which from BTMM, and which from the reference profile. Provider errors are "
            "captured in warnings and do not silently downgrade a row to the reference value."
        ),
        field_dict={
            "country": FieldDef(description="Country code echoed back.", source="input"),
            "rows[].section": FieldDef(description="Logical grouping (rates / prices / labor / growth / fiscal).", source="reference"),
            "rows[].metric": FieldDef(description="Human-readable label.", source="reference"),
            "rows[].value": FieldDef(unit="varies", description="Latest normalized value in the row's unit.", source="fred / btmm / reference"),
            "rows[].as_of": FieldDef(unit="iso8601", description="Provider date when available.", source="fred"),
            "rows[].source_mode": FieldDef(description="Which layer produced the row (live_fred / btmm / country_reference_profile).", source="derived"),
            "source_mode": FieldDef(description="Top-level mode for the workbook payload.", source="derived"),
            "country_known": FieldDef(description="True when the requested country has a curated reference profile.", source="derived"),
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
                description="With live=true, asserts source_mode is live_macro when any FRED/BTMM provider returns data; never silently relabels the reference profile as live.",
                inputs={"country": "US", "live": True},
                assertions=[
                    "source_mode_reflects_actual_provider",
                    "no_silent_reference_relabel",
                ],
            ),
        ],
    )


__all__ = ["coun"]
