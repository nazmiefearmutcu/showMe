"""CPF — Commodity Price Forecast.

Surfaces forward-looking commodity price forecasts pulled from FRED
series (e.g. WTI futures curves, Henry Hub forecasts published by the
EIA in FRED). The handler returns the historical actual + the forward
forecast vintage with an explicit forecast_vintage date so users
never mistake a stale projection for a live print.
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
            "Plot actual + forecast price for a benchmark commodity series "
            "from FRED (EIA forecasts, World Bank commodity outlooks) with "
            "the publication vintage labelled so stale forecasts cannot "
            "masquerade as live data."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="series_id",
                label="Series",
                control=ControlKind.SELECT,
                required=True,
                description="FRED commodity series with a published forecast vintage.",
                options=[
                    "WTISPLC",
                    "DCOILWTICO",
                    "DHHNGSP",
                    "PCOPPUSDM",
                    "PGOLD",
                    "PNGASEUUSDM",
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
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "series_id": "WTISPLC",
            "horizon": "1Y",
            "show_actual_history": True,
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
            "CPF fetches the chosen FRED commodity series (e.g. WTISPLC for "
            "WTI monthly average, DHHNGSP for Henry Hub spot, PGOLD for "
            "gold) along with its companion forecast series when FRED "
            "publishes one. The forecast vintage (the date the EIA / World "
            "Bank published the forecast) is captured from the FRED "
            "series metadata and surfaced on the card as a badge — a six-"
            "month-old EIA forecast must never silently render alongside a "
            "today-stamped actual. Forecast points beyond `horizon` are "
            "clipped. Cache TTL is 15 minutes since EIA vintages rarely "
            "change intraday."
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
            "actual": FieldDef(description="Array of {date, value} historical observations.", source="fred"),
            "forecast": FieldDef(description="Array of {date, value} forecast observations.", source="fred"),
            "forecast_vintage": FieldDef(unit="iso8601", description="Publication date of the loaded forecast vintage.", source="fred"),
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
