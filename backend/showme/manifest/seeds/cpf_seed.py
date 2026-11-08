"""CPF — Commodity Price Forecast.

Plots a live actual leg (a keyless Yahoo futures proxy for the chosen series
id) and a trend-extrapolated forward leg. The forecast is not an EIA, World
Bank or other published forecast. The handler returns the forecast vintage
(the last realized actual date) so a projection is never mistaken for a live
print.
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
def cpf() -> FunctionManifest:
    return FunctionManifest(
        code="CPF",
        name="Commodity Price Forecast",
        category=Category.COMMODITIES,
        intent=(
            "Plot the live actual price of a benchmark commodity futures proxy "
            "with a trend-extrapolated forward forecast. The forecast vintage "
            "(last realized actual date) is labelled so a projection cannot "
            "masquerade as a live print. This is a trend model, not a published "
            "EIA or World Bank forecast."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="series_id",
                label="Series",
                control=ControlKind.SELECT,
                required=True,
                description=(
                    "Benchmark commodity id. Each id is served from a Yahoo futures "
                    "proxy, not from the FRED series of that name (see series_note)."
                ),
                options=[
                    "WTISPLC",
                    "DCOILWTICO",
                    "DHHNGSP",
                    "PCOPPUSDM",
                    "PGOLD",
                ],
            ),
            InputSpec(
                name="horizon",
                label="Forecast horizon",
                control=ControlKind.SELECT,
                required=True,
                description="Forward window for the forecast overlay.",
                options=["6M", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="show_actual_history",
                label="Show actual history",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Render the historical actual series underneath the forecast.",
            ),
        ],
        defaults={
            "series_id": "WTISPLC",
            "horizon": "1Y",
            "show_actual_history": True,
        },
        # CPF#3/#7: the only source is the keyless Yahoo futures chart. There is
        # no cached snapshot or official source, and no provider_mode input.
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[DataMode.DELAYED_REFERENCE],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "series_id",
                "actual",
                "forecast",
                "forecast_vintage",
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
            y_axis=AxisSpec(type="numeric", unit="USD/unit", label="Price"),
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
                ColumnSpec(key="vintage", label="Vintage", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="latest_actual", label="Latest actual", kind="big_number", unit="USD/unit"),
                CardSlot(key="forecast_1y", label="Forecast 1Y", kind="big_number", unit="USD/unit"),
                CardSlot(key="forecast_vintage", label="Vintage", kind="badge"),
                CardSlot(key="forecast_horizon", label="Horizon", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CPF reads the daily Yahoo futures history for the futures proxy "
            "behind each series id (WTISPLC and DCOILWTICO use CL=F, DHHNGSP "
            "uses NG=F, PCOPPUSDM uses HG=F, PGOLD uses GC=F). No FRED series "
            "is fetched. The forward leg is a trend extrapolation of that "
            "history (a clamped log-linear growth rate), not a published EIA "
            "or World Bank forecast. forecast_vintage is the last realized "
            "actual date. Forecast points are calendar months after it and "
            "are clipped to `horizon`. Cache TTL is 15 minutes."
        ),
        formula_dict={
            "forecast_error_pct": Formula(
                expression=r"err\_pct = \frac{actual - forecast}{forecast} \times 100",
                variables={"actual": "Realized print", "forecast": "Prior vintage forecast"},
                notes="Backtest helper; positive when realized exceeds the prior forecast.",
            ),
        },
        field_dict={
            "series_id": FieldDef(description="FRED series identifier.", source="input"),
            "actual": FieldDef(description="Array of {date, value} daily futures-proxy closes.", source="yfinance"),
            "forecast": FieldDef(description="Array of {date, value} trend-extrapolated points.", source="derived"),
            "forecast_vintage": FieldDef(unit="iso8601", description="Last realized actual date the forecast is anchored to.", source="yfinance"),
            "forecast_horizon": FieldDef(description="User-selected forward window.", source="input"),
            "latest_actual": FieldDef(unit="USD/unit", description="Most recent realized value.", source="derived"),
            "forecast_1y": FieldDef(unit="USD/unit", description="Forecast at ~12-month horizon.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="cpf_forecast_vintage_present_when_forecast_present",
                description="If the forecast array is non-empty, forecast_vintage must be a valid date.",
                inputs={"series_id": "WTISPLC", "horizon": "1Y"},
                assertions=[
                    "forecast_present_or_warning",
                    "forecast_vintage_is_iso_date",
                ],
            ),
            SemanticTest(
                name="cpf_no_silent_actual_extension",
                description="CPF never appends synthetic 'actual' points beyond today.",
                inputs={"series_id": "WTISPLC"},
                assertions=["no_actual_after_today"],
            ),
        ],
    )


__all__ = ["cpf"]
