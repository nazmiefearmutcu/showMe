"""CHGS — Chart Studies (preset TECH bundle / quick-launch).

A study-focused chart launcher that wraps TECH with a fixed preset of
overlays + sub-pane studies and a faster turnaround for the workspace's
"throw a chart up with sensible defaults" need. CHGS aliases TECH on the
live path; the offline path returns a small template so the pane still
renders when no data adapter is wired.
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
def chgs() -> FunctionManifest:
    return FunctionManifest(
        code="CHGS",
        name="Chart Studies",
        category=Category.CHARTS_TECH,
        intent=(
            "Study-focused chart launcher: render a price chart with a fixed"
            " preset of overlays + indicators (SMA20/SMA50 + RSI14) so the"
            " operator can drop a chart into the workspace without picking inputs."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument identifier (AAPL, BTCUSDT, EURUSD=X).",
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=False,
                description="Bar interval; default daily for quick launch.",
                options=["1h", "4h", "1d", "1wk", "1mo"],
            ),
            InputSpec(
                name="chart_kind",
                label="Chart",
                control=ControlKind.SELECT,
                required=False,
                description="Render style for the price pane.",
                options=["candles", "line"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "symbol": "AAPL",
            "interval": "1d",
            "chart_kind": "candles",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["symbol", "rows", "last", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_CANDLES,
            x_axis=AxisSpec(type="time", unit="ms", label=""),
            y_axis=[
                AxisSpec(type="numeric", unit="quote_ccy", label="Price"),
                AxisSpec(type="numeric", unit="", label="RSI"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="candle", height_pct=70),
                PaneGrammar(name="rsi", series_kind="line", height_pct=30),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Time", kind="datetime", format="yyyy-MM-dd"),
                ColumnSpec(key="open", label="Open", kind="number", format="%.4f"),
                ColumnSpec(key="high", label="High", kind="number", format="%.4f"),
                ColumnSpec(key="low", label="Low", kind="number", format="%.4f"),
                ColumnSpec(key="close", label="Close", kind="number", format="%.4f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="last", label="Last", kind="big_number", unit="quote_ccy"),
                CardSlot(key="rsi_14", label="RSI(14)", kind="kpi"),
                CardSlot(key="sma_20", label="SMA(20)", kind="kpi"),
                CardSlot(key="sma_50", label="SMA(50)", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CHGS is a quick-launch alias for TECH with a fixed preset of overlays (SMA20/SMA50) and"
            " a single RSI(14) sub-pane. The handler defers to the live TECH path by default"
            " (``metadata.alias_of=TECH``); when the provider is unavailable it returns an explicit"
            " ``no_price_history`` status with a reason — never a synthetic chart template. The"
            " chart_grammar pins ``TIME_SERIES_CANDLES`` with a 70/30 price/RSI split."
        ),
        formula_dict={},
        field_dict={
            "symbol": FieldDef(description="Instrument symbol echoed from the request.", source="adapter"),
            "last": FieldDef(unit="quote_ccy", description="Last close price (from the live TECH alias).", source="adapter"),
            "rsi_14": FieldDef(description="Wilder RSI(14) reading at last close.", source="computed"),
            "sma_20": FieldDef(unit="quote_ccy", description="Simple 20-period close average.", source="computed"),
            "sma_50": FieldDef(unit="quote_ccy", description="Simple 50-period close average.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "rsi_above", "rsi_below"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="chgs_default_defers_to_live_tech",
                description=(
                    "The default path forwards to TECHFunction (metadata.alias_of=TECH); with no"
                    " provider it returns an explicit no_price_history status and a reason, never a"
                    " chart template."
                ),
                inputs={"symbol": "AAPL"},
                assertions=[
                    "metadata_alias_of_equals_TECH",
                ],
            ),
            SemanticTest(
                name="chgs_live_aliases_tech",
                description="The live path forwards to TECHFunction and inherits its sources.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "metadata_alias_of_equals_TECH",
                    "sources_include_yfinance_or_binance",
                ],
            ),
            SemanticTest(
                name="chgs_chart_grammar_is_candles_with_rsi",
                description=(
                    "chart_grammar.kind is time_series_candles and the panes include a dedicated RSI"
                    " band — CHGS must not collapse the indicator onto the price axis."
                ),
                inputs={},
                assertions=[
                    "chart_grammar_kind_is_time_series_candles",
                    "panes_include_rsi_band",
                ],
            ),
            SemanticTest(
                name="chgs_requires_instrument",
                description="A call with no symbol raises ValueError instead of silently returning empty rows.",
                inputs={},
                assertions=["missing_symbol_raises_value_error"],
            ),
        ],
    )


__all__ = ["chgs"]
