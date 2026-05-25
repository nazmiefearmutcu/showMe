"""FXFC — FX Scenario Forecast.

Renders consensus + scenario forecasts for a chosen FX pair across
horizons (3M/6M/1Y/2Y). Bull/base/bear scenarios are explicit
columns and rendered as time-series line bands.
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
def fxfc() -> FunctionManifest:
    return FunctionManifest(
        code="FXFC",
        name="FX Scenario Forecast",
        category=Category.FX,
        intent=(
            "Consensus + scenario (bull/base/bear) forecasts for an FX pair "
            "across horizons (3M/6M/1Y/2Y), with the consensus vintage "
            "labelled so a stale survey cannot pass as a live view."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="pair",
                label="Pair",
                control=ControlKind.SELECT,
                required=True,
                description="FX pair (e.g. EURUSD, USDJPY, USDTRY).",
                options=[
                    "EURUSD",
                    "USDJPY",
                    "GBPUSD",
                    "AUDUSD",
                    "USDCAD",
                    "USDCHF",
                    "USDTRY",
                ],
            ),
            InputSpec(
                name="horizon",
                label="Horizon",
                control=ControlKind.SELECT,
                required=True,
                description="Forecast horizon.",
                options=["3M", "6M", "1Y", "2Y"],
            ),
            InputSpec(
                name="scenarios",
                label="Scenarios",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which scenario bands to render.",
                options=["bull", "base", "bear"],
            ),
            InputSpec(
                name="show_actual_history",
                label="Show actual history",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Render the trailing actual spot underneath the forecast.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "pair": "EURUSD",
            "horizon": "1Y",
            "scenarios": ["base"],
            "show_actual_history": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["fred", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "pair",
                "actual",
                "forecast",
                "consensus_vintage",
                "horizon",
                "as_of",
                "data_mode",
            ],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="iso8601", label="Date"),
            y_axis=AxisSpec(type="numeric", unit="quote_ccy", label="Rate"),
            panes=[
                PaneGrammar(name="actual_and_forecast", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="kind", label="Kind", kind="tag"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="scenario", label="Scenario", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number"),
                CardSlot(key="forecast_base", label="Base forecast", kind="big_number"),
                CardSlot(key="forecast_bull", label="Bull forecast", kind="kpi"),
                CardSlot(key="forecast_bear", label="Bear forecast", kind="kpi"),
                CardSlot(key="consensus_vintage", label="Vintage", kind="badge"),
                CardSlot(key="horizon", label="Horizon", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FXFC layers a labelled scenario forecast on top of trailing "
            "actual spot. Actual is pulled from yfinance (BASEQUOTE=X). "
            "Forecast vintage is anchored to the most-recent consensus "
            "survey aggregation date — exposed on the card so a six-month-"
            "old survey cannot pass as a live view. Bull / base / bear "
            "scenario bands come from the survey aggregation when available "
            "or from a labelled internal model when not (data_mode flips to "
            "modeled). The chart renders each requested scenario as its own "
            "line; values beyond `horizon` are clipped. No silent zero-fill "
            "for missing dates; gaps are warned."
        ),
        formula_dict={
            "scenario_band_width": Formula(
                expression=r"width = forecast_{bull} - forecast_{bear}",
                variables={"forecast_bull": "Upper scenario", "forecast_bear": "Lower scenario"},
                notes="Quick measure of dispersion across bull/bear scenarios.",
            ),
        },
        field_dict={
            "pair": FieldDef(description="FX pair (BASEQUOTE).", source="input"),
            "actual": FieldDef(description="Array of {date, value} historical observations.", source="provider"),
            "forecast": FieldDef(description="Array of {date, value, scenario} forecast points.", source="aggregator"),
            "consensus_vintage": FieldDef(unit="iso8601", description="Publication date of the loaded consensus.", source="aggregator"),
            "horizon": FieldDef(description="Forecast horizon label.", source="input"),
            "forecast_base": FieldDef(description="Base-scenario forecast at the horizon end.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fxfc_consensus_vintage_present_when_forecast_present",
                description="If the forecast array is non-empty, consensus_vintage must be a valid date.",
                inputs={"pair": "EURUSD", "horizon": "1Y"},
                assertions=[
                    "forecast_present_or_warning",
                    "consensus_vintage_is_iso_date",
                ],
            ),
            SemanticTest(
                name="fxfc_no_silent_actual_extension",
                description="FXFC never appends synthetic 'actual' points beyond today.",
                inputs={"pair": "EURUSD"},
                assertions=["no_actual_after_today"],
            ),
            SemanticTest(
                name="fxfc_bull_geq_bear_at_horizon",
                description="At the horizon, the bull scenario must be ≥ the bear scenario.",
                inputs={"pair": "EURUSD", "horizon": "1Y", "scenarios": ["bull", "base", "bear"]},
                assertions=["bull_forecast_geq_bear_forecast"],
            ),
        ],
    )


__all__ = ["fxfc"]
