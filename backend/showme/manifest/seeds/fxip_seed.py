"""FXIP — FX Information + Price.

Main FX-pair pane: mirrors GP's shape but specialized for FX. Returns
OHLCV candles plus the FX-specific reference card (pair, base/quote
ccy, spot, bid/ask, mid, change %, day range, 52w range, last 10
deltas) with a candle chart pane + volume sub-pane.
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
def fxip() -> FunctionManifest:
    return FunctionManifest(
        code="FXIP",
        name="FX Information + Price",
        category=Category.FX,
        intent=(
            "Main FX pane for a single pair: OHLCV candles, bid/ask/mid, "
            "day range, 52w range, and a curated FX-specific reference "
            "card. Same chart grammar as GP but specialized for FX."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="pair",
                label="Pair",
                control=ControlKind.SELECT,
                required=True,
                description="FX pair (BASEQUOTE).",
                options=[
                    "EURUSD",
                    "USDJPY",
                    "GBPUSD",
                    "AUDUSD",
                    "USDCAD",
                    "USDCHF",
                    "USDTRY",
                    "EURJPY",
                    "EURGBP",
                ],
            ),
            InputSpec(
                name="range",
                label="Range",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window.",
                options=["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y"],
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval (validated against range).",
                options=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"],
                depends_on=["range"],
            ),
            InputSpec(
                name="chart_kind",
                label="Chart",
                control=ControlKind.SELECT,
                required=True,
                description="Render style for the price pane.",
                options=["candles", "line", "area"],
            ),
            InputSpec(
                name="compare",
                label="Compare with",
                control=ControlKind.SELECT,
                required=False,
                description="Second pair pinned as an overlay normalized to 100 at range start.",
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
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "pair": "EURUSD",
            "range": "1Y",
            "interval": "1d",
            "chart_kind": "candles",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "pair",
                "base_ccy",
                "quote_ccy",
                "candles",
                "spot",
                "as_of",
                "data_mode",
            ],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_CANDLES,
            x_axis=AxisSpec(type="time", unit="ms", label="Time"),
            y_axis=[
                AxisSpec(type="numeric", unit="quote_ccy", label="Rate"),
                AxisSpec(type="numeric", unit="ticks", label="Volume"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="candle", height_pct=70),
                PaneGrammar(name="volume", series_kind="histogram", height_pct=30),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="t", label="Time", kind="datetime", format="yyyy-MM-dd HH:mm"),
                ColumnSpec(key="o", label="Open", kind="number", format="%.4f"),
                ColumnSpec(key="h", label="High", kind="number", format="%.4f"),
                ColumnSpec(key="l", label="Low", kind="number", format="%.4f"),
                ColumnSpec(key="c", label="Close", kind="number", format="%.4f"),
                ColumnSpec(key="v", label="Volume", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number"),
                CardSlot(key="bid", label="Bid", kind="kpi"),
                CardSlot(key="ask", label="Ask", kind="kpi"),
                CardSlot(key="change_pct", label="Δ %", kind="trend_pill", unit="%"),
                CardSlot(key="day_range", label="Day Range", kind="kpi"),
                CardSlot(key="week_52_range", label="52w Range", kind="kpi"),
                CardSlot(key="base_ccy", label="Base", kind="badge"),
                CardSlot(key="quote_ccy", label="Quote", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FXIP is the FX-equivalent of GP. The handler resolves the "
            "pair to its yfinance ticker (BASEQUOTE=X for major pairs) and "
            "fetches OHLCV for the chosen range and interval. base_ccy / "
            "quote_ccy are parsed from the pair label and surfaced on the "
            "card as badges so the user always knows which currency is in "
            "the numerator. Compare overlays normalize both pairs to 100 at "
            "the first visible bar (cross-pair comparison only makes sense "
            "after normalization). The pane respects user pan/zoom across "
            "data refresh using the first-seed-focus pattern."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{rate - prev\_close}{prev\_close} \times 100",
                variables={"rate": "Latest rate", "prev_close": "Previous session close"},
            ),
            "mid": Formula(
                expression=r"mid = \frac{bid + ask}{2}",
                variables={"bid": "Best bid", "ask": "Best ask"},
                notes="Fallback to last when bid/ask are missing.",
            ),
        },
        field_dict={
            "pair": FieldDef(description="FX pair label (BASEQUOTE).", source="input"),
            "base_ccy": FieldDef(description="Base currency code (first 3 chars).", source="parsed"),
            "quote_ccy": FieldDef(description="Quote currency code (last 3 chars).", source="parsed"),
            "candles[].c": FieldDef(unit="quote_ccy", description="Close rate.", source="provider"),
            "spot": FieldDef(unit="quote_ccy", description="Latest spot rate.", source="provider"),
            "bid": FieldDef(unit="quote_ccy", description="Best bid.", source="provider"),
            "ask": FieldDef(unit="quote_ccy", description="Best ask.", source="provider"),
            "day_range": FieldDef(unit="quote_ccy", description="Session low → high.", source="computed"),
            "week_52_range": FieldDef(unit="quote_ccy", description="52-week low → high.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "price_above",
                "price_below",
                "change_pct_above",
                "change_pct_below",
                "new_52w_high",
                "new_52w_low",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="fxip_eurusd_returns_candles_and_ccy_split",
                description="FXIP for EURUSD returns candles plus base_ccy=EUR and quote_ccy=USD.",
                inputs={"pair": "EURUSD", "range": "1Y", "interval": "1d"},
                assertions=[
                    "candles_non_empty",
                    "base_ccy_equals_EUR",
                    "quote_ccy_equals_USD",
                ],
            ),
            SemanticTest(
                name="fxip_chart_grammar_is_candles_not_row_index",
                description="FXIP chart_grammar.kind is time_series_candles (time axis).",
                inputs={},
                assertions=["chart_grammar_kind_is_time_series_candles"],
            ),
            SemanticTest(
                name="fxip_no_silent_zero_candles_on_failure",
                description="A failing pair returns an empty candle array with warnings, never fabricated zeros.",
                inputs={"pair": "EURUSD", "_mock": "provider_down"},
                assertions=[
                    "candles_empty_or_warnings_present",
                    "no_synthetic_zero_candle",
                ],
            ),
        ],
    )


__all__ = ["fxip"]
