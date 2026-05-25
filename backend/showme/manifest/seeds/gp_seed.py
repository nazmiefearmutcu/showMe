"""GP — Generic Price Chart.

Per wave1/GP.md: the workspace's default price chart for any tradable
instrument with candles/line, overlays, sub-pane studies, compare mode,
and a fast symbol switcher.
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
def gp() -> FunctionManifest:
    return FunctionManifest(
        code="GP",
        name="Generic Price",
        category=Category.CHARTS_TECH,
        intent=(
            "Inspect price action for any tradable instrument with candles/line, "
            "overlays, indicator studies, compare mode, and a fast symbol switcher."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.FUTURE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Canonical security identifier (AAPL, BTCUSDT, EURUSD=X).",
            ),
            InputSpec(
                name="range",
                label="Range",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window.",
                options=["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"],
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval (validated against range).",
                options=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo"],
                depends_on=["range"],
            ),
            InputSpec(
                name="chart_kind",
                label="Chart",
                control=ControlKind.SELECT,
                required=True,
                description="Render style.",
                options=["candles", "line", "area", "hollow_candles"],
            ),
            InputSpec(
                name="overlays",
                label="Overlays",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Price overlays computed client-side from the OHLCV series.",
                options=[
                    "SMA20", "SMA50", "SMA200",
                    "EMA20", "EMA50", "EMA200",
                    "BB20_2", "VWAP", "IchimokuCloud",
                ],
            ),
            InputSpec(
                name="studies",
                label="Sub-pane studies",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Lower-pane indicators rendered as their own panes.",
                options=[
                    "VOLUME", "RSI14", "MACD_12_26_9", "ATR14",
                    "OBV", "STOCH_14_3_3", "ADX14", "ROC10",
                ],
            ),
            InputSpec(
                name="compare",
                label="Compare with",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Second instrument pinned as overlay, normalized to 100 at range start.",
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
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "symbol": "AAPL",
            "range": "1Y",
            "interval": "1d",
            "chart_kind": "candles",
            "overlays": ["SMA20", "SMA50"],
            "studies": ["VOLUME"],
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["symbol", "candles", "as_of", "provider", "data_mode", "interval"],
            rows=False,
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
                AxisSpec(type="numeric", unit="", label="Volume"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="candle", height_pct=60),
                PaneGrammar(name="volume", series_kind="histogram", height_pct=15),
                PaneGrammar(name="study", series_kind="line", height_pct=25),
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
                CardSlot(key="last_price", label="Last", kind="big_number", unit="quote_ccy"),
                CardSlot(key="change", label="Change", kind="trend_pill", unit="quote_ccy"),
                CardSlot(key="change_pct", label="Change %", kind="trend_pill", unit="%"),
                CardSlot(key="day_range", label="Day Range", kind="kpi", unit="quote_ccy"),
                CardSlot(key="volume_24h", label="Volume", kind="kpi", unit="shares"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GP fetches OHLCV bars from the primary provider for the chosen interval and range. "
            "Overlays are computed client-side from the returned candle series (SMA/EMA/BB/VWAP/Ichimoku "
            "are O(n) deterministic). Sub-pane studies share the same series (RSI uses Wilder's smoothing; "
            "MACD uses 12/26/9 EMA; ATR uses Wilder; STOCH uses %K=14 %D=3 SMA; ADX uses 14-period DMI; "
            "OBV uses signed-volume cumsum). Compare mode normalizes both series to 100 at the first "
            "visible candle. The pane respects user pan/zoom across data refresh (first-seed-focus pattern). "
            "Live mode listens on the provider's WS stream and patches the last candle on tick."
        ),
        formula_dict={
            "SMA": Formula(
                expression=r"SMA_t = \frac{1}{n} \sum_{i=0}^{n-1} close_{t-i}",
                variables={"n": "period"},
            ),
            "EMA": Formula(
                expression=r"EMA_t = \alpha \cdot close_t + (1-\alpha) \cdot EMA_{t-1}, \alpha = \frac{2}{n+1}",
                variables={"n": "period"},
            ),
            "RSI": Formula(
                expression=r"RSI = 100 - \frac{100}{1+RS}, RS = \frac{avg\_gain}{avg\_loss}",
                variables={"period": "14"},
                notes="Wilder's smoothing.",
            ),
            "MACD": Formula(
                expression=r"MACD = EMA_{12} - EMA_{26}; signal = EMA_9(MACD)",
                variables={"fast": "12", "slow": "26", "signal": "9"},
            ),
            "ATR": Formula(
                expression=r"TR = \max(H-L, |H-C_{prev}|, |L-C_{prev}|); ATR = EMA(TR, 14)",
                variables={"period": "14"},
                notes="Wilder smoothing.",
            ),
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={
                    "last": "Latest price",
                    "prev_close": "Previous session close",
                },
            ),
        },
        field_dict={
            "candles[].t": FieldDef(unit="epoch_ms", description="Bar open time.", source="provider"),
            "candles[].o": FieldDef(unit="quote_ccy", description="Open price.", source="provider"),
            "candles[].h": FieldDef(unit="quote_ccy", description="High price.", source="provider"),
            "candles[].l": FieldDef(unit="quote_ccy", description="Low price.", source="provider"),
            "candles[].c": FieldDef(unit="quote_ccy", description="Close price.", source="provider"),
            "candles[].v": FieldDef(unit="base_or_quote", description="Volume.", source="provider"),
            "quote_ccy": FieldDef(description="Quote currency (USD, USDT, EUR).", source="provider"),
            "change": FieldDef(unit="quote_ccy", description="last - prev_close.", source="computed"),
            "change_pct": FieldDef(unit="%", description="change / prev_close * 100.", source="computed"),
            "day_range": FieldDef(unit="quote_ccy", description="L-H of current session.", source="computed"),
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
                "volume_spike",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="gp_aapl_1y_1d_returns_real_candles",
                description="GP returns ≥200 monotonic OHLC candles for AAPL 1Y daily, no zero closes, no h<l.",
                inputs={"symbol": "AAPL", "range": "1Y", "interval": "1d"},
                assertions=[
                    "candles_length_at_least_200",
                    "candles_time_monotonic",
                    "candles_have_ohlc_fields",
                    "no_candle_close_zero",
                    "no_candle_high_below_low",
                    "provider_in_known_set",
                ],
            ),
            SemanticTest(
                name="gp_btcusdt_1d_5m_uses_binance",
                description="GP for crypto routes to binance with live_exchange mode and ≥250 5m bars.",
                inputs={"symbol": "BTCUSDT", "range": "1D", "interval": "5m"},
                assertions=[
                    "provider_equals_binance",
                    "data_mode_equals_live_exchange",
                    "candles_length_at_least_250",
                ],
            ),
            SemanticTest(
                name="gp_invalid_interval_for_range_rejected",
                description="GP rejects nonsensical interval/range combos rather than silently succeed.",
                inputs={"symbol": "AAPL", "range": "1D", "interval": "1d"},
                assertions=["http_422_or_degraded_with_warning"],
            ),
            SemanticTest(
                name="gp_compare_overlay_normalized",
                description="Compare overlay starts at 100 and matches candle series length.",
                inputs={"symbol": "AAPL", "compare": "MSFT", "range": "1Y"},
                assertions=[
                    "compare_series_present",
                    "compare_series_length_equals_candles",
                    "compare_first_value_equals_100",
                ],
            ),
            SemanticTest(
                name="gp_overlay_sma20_matches_formula",
                description="SMA20 overlay equals the rolling mean of close from bar 20 onwards.",
                inputs={"symbol": "AAPL", "range": "6M", "overlays": ["SMA20"]},
                assertions=["overlay_sma20_matches_rolling_mean_within_1e-9"],
            ),
            SemanticTest(
                name="gp_chart_grammar_is_candles_not_row_index",
                description="Manifest chart_grammar.kind is time_series_candles (time axis, not row-index).",
                inputs={},
                assertions=["chart_grammar_kind_is_time_series_candles"],
            ),
        ],
    )


__all__ = ["gp"]
