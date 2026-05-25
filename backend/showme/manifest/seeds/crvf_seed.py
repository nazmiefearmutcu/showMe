"""CRVF — Sovereign Yield Curve.

Renders the maturity curve for a chosen sovereign with tenor on the
x-axis and yield on the y-axis. The chart_grammar pins
``ChartKind.TENOR_CURVE`` so the renderer cannot regress to a row-index
line (a real bug in the 2026-05 redesign). FRED is the primary live
source for US; non-US sovereigns currently route through the curve_model
fallback with an explicit label.
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
    AlertingSpec,
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
def crvf() -> FunctionManifest:
    return FunctionManifest(
        code="CRVF",
        name="Yield Curve",
        category=Category.BONDS_RATES,
        intent=(
            "Plot the sovereign yield curve ordered by maturity so the user can"
            " read steepening / flattening / inversion at a glance. Tenor lives"
            " on the x-axis; yield on the y-axis."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="country",
                label="Country",
                control=ControlKind.SELECT,
                required=True,
                description="Sovereign issuer whose curve is rendered.",
                options=["US", "DE", "JP", "GB", "FR", "IT", "ES", "AU", "CA", "TR"],
            ),
            InputSpec(
                name="tenors",
                label="Tenors",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Curve points to include on the x-axis (filters the catalog).",
                options=["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
            ),
            InputSpec(
                name="live_curve",
                label="Live FRED",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "When true and country=US, pull yields from FRED's DGS* series."
                    " Otherwise the curve_model template is returned with an explicit"
                    " source_mode label."
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
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "country": "US",
            "tenors": ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"],
            "live_curve": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "curve", "summary", "as_of", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TENOR_CURVE,
            x_axis=AxisSpec(type="numeric", unit="years", label="Tenor"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Yield"),
            panes=[
                PaneGrammar(name="curve", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="tenor", label="Tenor", kind="tag", width_hint=72),
                ColumnSpec(key="tenor_years", label="Years", kind="number", format="%.2f"),
                ColumnSpec(key="yield", label="Yield", kind="percent", unit="%", format="%.3f"),
                ColumnSpec(key="as_of", label="As of", kind="date"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="latest_10y", label="10Y", kind="big_number", unit="%"),
                CardSlot(key="slope_2s10s", label="2s10s", kind="kpi", unit="bp"),
                CardSlot(key="slope_3m10y", label="3M-10Y", kind="kpi", unit="bp"),
                CardSlot(key="inverted", label="Inverted", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CRVF fans out FRED DGS* series for the requested tenors when ``live_curve=true`` and"
            " ``country=US``; for non-US countries (or with live off) the engine returns a labelled"
            " ``computed_model`` template so the pane never silently fakes live data. Rows are sorted"
            " by ``tenor_years`` ascending — the renderer reads ``tenor_years`` as the x value, never"
            " the row index, so the chart shape reflects real maturity geometry. Slope KPIs are"
            " computed client-side from the visible curve (2s10s = 10Y - 2Y; 3M-10Y = 10Y - 3M)."
        ),
        formula_dict={
            "slope_2s10s": Formula(
                expression=r"slope_{2s10s} = (y_{10Y} - y_{2Y}) \times 100",
                variables={"y_2Y": "2Y yield", "y_10Y": "10Y yield"},
                notes="Slope expressed in basis points; negative = inverted.",
            ),
        },
        field_dict={
            "rows[].tenor": FieldDef(description="Curve maturity label.", source="catalog"),
            "rows[].tenor_years": FieldDef(unit="years", description="Numeric maturity used for the x-axis.", source="catalog"),
            "rows[].yield": FieldDef(unit="%", description="Annualized yield for that tenor.", source="fred"),
            "rows[].as_of": FieldDef(unit="date", description="Date of the yield observation.", source="fred"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["yield_above", "yield_below", "curve_inverted", "slope_breach"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="crvf_chart_grammar_tenor_curve_not_row_index",
                description=(
                    "Manifest chart_grammar.kind is tenor_curve and x-axis unit is years, so the"
                    " renderer cannot regress to a row-index line — a real bug in the 2026-05 redesign."
                ),
                inputs={},
                assertions=[
                    "tenor_curve_not_row_index",
                    "chart_grammar_kind_is_tenor_curve",
                    "x_axis_unit_is_years",
                ],
            ),
            SemanticTest(
                name="crvf_rows_sorted_by_tenor_years",
                description="Rows must be sorted ascending by tenor_years before the renderer reads them.",
                inputs={"country": "US"},
                assertions=["rows_sorted_ascending_by_tenor_years"],
            ),
            SemanticTest(
                name="crvf_live_us_routes_to_fred",
                description="With live_curve=true and country=US the chain hits FRED.",
                inputs={"country": "US", "live_curve": True},
                assertions=["provider_chain_used_fred"],
            ),
            SemanticTest(
                name="crvf_non_us_live_falls_back_with_warning",
                description=(
                    "Live request for a non-US sovereign falls back to curve_model and surfaces a"
                    " warning explaining the gap rather than silently faking a FRED row."
                ),
                inputs={"country": "TR", "live_curve": True},
                assertions=[
                    "source_mode_equals_computed_model_or_curve_model",
                    "warning_present_about_non_us_fred_gap",
                ],
            ),
        ],
    )


__all__ = ["crvf"]
