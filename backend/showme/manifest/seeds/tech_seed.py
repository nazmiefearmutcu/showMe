"""TECH — Multi-pane technical indicator lab.

Full indicator workbench for any tradable instrument: candle pane plus
sub-pane studies (RSI/MACD/ATR/ADX/Stoch/OBV) and overlays (SMA/EMA/BB/
Ichimoku). Indicator math (Wilder RSI, EMA-based MACD/ATR, Bollinger with
ddof=0 std, etc.) is pinned by ``formula_dict`` so the handler can never
silently drift. The chart_grammar is ``TIME_SERIES_CANDLES`` with one
pane per family so the renderer paints each study in its own band.
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
def tech() -> FunctionManifest:
    return FunctionManifest(
        code="TECH",
        name="Technical Indicators",
        category=Category.CHARTS_TECH,
        intent=(
            "Multi-pane technical workbench: price candles plus sub-pane studies"
            " (RSI / MACD / ATR / ADX / Stochastic / OBV) and price overlays"
            " (SMA / EMA / Bollinger / Ichimoku) so an operator can drive a full"
            " indicator screen from a single function."
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
                description="Instrument identifier (AAPL, BTCUSDT, EURUSD=X).",
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval; validated against the history fetch.",
                options=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1mo"],
            ),
            InputSpec(
                name="days",
                label="Look-back",
                control=ControlKind.NUMBER,
                required=False,
                description="Days of history to request from the provider.",
                min=7,
                max=3650,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="tail",
                label="Visible bars",
                control=ControlKind.NUMBER,
                required=False,
                description="Number of trailing bars surfaced to the chart.",
                min=60,
                max=5000,
                step=1,
                unit="bars",
            ),
            InputSpec(
                name="studies",
                label="Studies",
                control=ControlKind.MULTISELECT,
                required=True,
                description=(
                    "Indicator families to compute. Each family becomes its own"
                    " sub-pane (RSI/MACD/ATR/ADX/Stochastic/OBV) or price overlay"
                    " (SMA/EMA/Bollinger/Ichimoku)."
                ),
                options=[
                    "SMA", "EMA", "BB", "Ichimoku",
                    "RSI", "MACD", "ATR", "ADX", "Stochastic", "OBV",
                ],
            ),
            InputSpec(
                name="rsi_period",
                label="RSI period",
                control=ControlKind.NUMBER,
                required=False,
                description="Wilder RSI period.",
                min=2,
                max=200,
                step=1,
                depends_on=["studies"],
            ),
            InputSpec(
                name="macd_fast",
                label="MACD fast",
                control=ControlKind.NUMBER,
                required=False,
                description="Fast EMA length for MACD.",
                min=2,
                max=100,
                step=1,
                depends_on=["studies"],
            ),
            InputSpec(
                name="macd_slow",
                label="MACD slow",
                control=ControlKind.NUMBER,
                required=False,
                description="Slow EMA length for MACD.",
                min=2,
                max=200,
                step=1,
                depends_on=["studies"],
            ),
            InputSpec(
                name="macd_signal",
                label="MACD signal",
                control=ControlKind.NUMBER,
                required=False,
                description="Signal EMA length for MACD.",
                min=2,
                max=50,
                step=1,
                depends_on=["studies"],
            ),
            InputSpec(
                name="bb_period",
                label="BB period",
                control=ControlKind.NUMBER,
                required=False,
                description="Rolling period for Bollinger bands.",
                min=2,
                max=200,
                step=1,
                depends_on=["studies"],
            ),
            InputSpec(
                name="bb_std",
                label="BB std",
                control=ControlKind.NUMBER,
                required=False,
                description="Number of standard deviations for the Bollinger envelope.",
                min=0.5,
                max=5.0,
                step=0.1,
                depends_on=["studies"],
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
            "interval": "1d",
            "days": 365,
            "tail": 1000,
            "studies": ["SMA", "EMA", "BB", "RSI", "MACD"],
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "bb_period": 20,
            "bb_std": 2.0,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
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
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["ohlcv", "rows", "indicators", "summary", "data_mode"],
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
                AxisSpec(type="numeric", unit="", label="Volume"),
                AxisSpec(type="numeric", unit="", label="Study"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="candle", height_pct=50),
                PaneGrammar(name="volume", series_kind="histogram", height_pct=10),
                PaneGrammar(name="rsi", series_kind="line", height_pct=10),
                PaneGrammar(name="macd", series_kind="histogram", height_pct=15),
                PaneGrammar(name="atr_adx", series_kind="line", height_pct=15),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="date", label="Time", kind="datetime", format="yyyy-MM-dd HH:mm"),
                ColumnSpec(key="open", label="Open", kind="number", format="%.4f"),
                ColumnSpec(key="high", label="High", kind="number", format="%.4f"),
                ColumnSpec(key="low", label="Low", kind="number", format="%.4f"),
                ColumnSpec(key="close", label="Close", kind="number", format="%.4f"),
                ColumnSpec(key="volume", label="Volume", kind="number", format="%.0f"),
                ColumnSpec(key="rsi", label="RSI", kind="number", format="%.2f"),
                ColumnSpec(key="macd", label="MACD", kind="number", format="%.4f"),
                ColumnSpec(key="atr", label="ATR", kind="number", format="%.4f"),
                ColumnSpec(key="adx", label="ADX", kind="number", format="%.2f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="last_price", label="Last", kind="big_number", unit="quote_ccy"),
                CardSlot(key="rsi", label="RSI(14)", kind="kpi"),
                CardSlot(key="macd", label="MACD", kind="kpi"),
                CardSlot(key="atr", label="ATR(14)", kind="kpi"),
                CardSlot(key="adx", label="ADX(14)", kind="kpi"),
                CardSlot(key="samples", label="Bars", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TECH pulls OHLCV from the primary provider (yfinance for equities/ETFs/FX/commodities,"
            " binance for crypto) over the requested look-back window and runs an indicator suite"
            " against the close series. RSI uses Wilder smoothing with α=1/period; MACD is"
            " EMA(fast) − EMA(slow) with an EMA(signal) histogram; ATR is Wilder EWM of the true"
            " range; Bollinger uses rolling mean ± n·std (ddof=0); Stochastic %K = 100·(close −"
            " low_K) / (high_K − low_K) with %D = SMA(%K); ADX uses EWM-smoothed DI from"
            " directional movement; OBV cumulates signed volume from close-to-close direction;"
            " Ichimoku tenkan/kijun are 9/26-period midpoints with senkou_a/_b projected 26 periods"
            " forward. Each requested family becomes its own sub-pane band so the chart never"
            " collapses multiple oscillators onto the price axis."
        ),
        formula_dict={
            "RSI_wilder": Formula(
                expression=r"RSI = 100 - \frac{100}{1 + RS}, \quad RS = \frac{\bar{gain}}{\bar{loss}}",
                variables={"period": "default 14"},
                notes="Wilder smoothing via EWM with α=1/period (matches handler).",
            ),
            "MACD": Formula(
                expression=r"MACD = EMA_{fast} - EMA_{slow}; \quad signal = EMA_{signal}(MACD)",
                variables={"fast": "12", "slow": "26", "signal": "9"},
            ),
            "ATR_wilder": Formula(
                expression=r"TR_t = \max(H-L, |H-C_{t-1}|, |L-C_{t-1}|); \quad ATR = EWM_{1/period}(TR)",
                variables={"period": "14"},
            ),
            "ADX_wilder": Formula(
                expression=r"DX = 100 \cdot \frac{|+DI - -DI|}{+DI + -DI}; \quad ADX = EWM_{1/period}(DX)",
                variables={"period": "14"},
            ),
            "Bollinger": Formula(
                expression=r"BB_{upper/lower} = SMA_{period} \pm n \cdot \sigma_{period}",
                variables={"period": "20", "n": "std multiplier (default 2)"},
                notes="Population std (ddof=0) to match the handler.",
            ),
            "Stochastic": Formula(
                expression=r"\%K = 100 \cdot \frac{close - L_K}{H_K - L_K}; \quad \%D = SMA_d(\%K)",
                variables={"K": "default 14", "d": "default 3"},
            ),
            "OBV": Formula(
                expression=r"OBV_t = OBV_{t-1} + sign(close_t - close_{t-1}) \cdot volume_t",
                variables={},
            ),
        },
        field_dict={
            "ohlcv[]": FieldDef(description="Price candles used for the chart.", source="yfinance"),
            "indicators.rsi": FieldDef(description="Wilder RSI series.", source="computed"),
            "indicators.macd": FieldDef(description="MACD line series.", source="computed"),
            "indicators.bb_upper": FieldDef(description="Bollinger upper band.", source="computed"),
            "indicators.bb_lower": FieldDef(description="Bollinger lower band.", source="computed"),
            "indicators.atr": FieldDef(description="ATR series.", source="computed"),
            "indicators.adx": FieldDef(description="ADX series.", source="computed"),
            "indicators.stoch_k": FieldDef(description="Stochastic %K.", source="computed"),
            "indicators.obv": FieldDef(description="On-Balance Volume cumulative series.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["rsi_above", "rsi_below", "macd_cross_up", "macd_cross_down", "adx_above", "bb_breakout"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="tech_studies_multiselect_present",
                description=(
                    "The studies multiselect control must be declared so the UI can drive the"
                    " indicator lab without the operator typing into JSON."
                ),
                inputs={},
                assertions=[
                    "input_studies_present",
                    "input_studies_control_is_multiselect",
                    "input_studies_options_include_rsi_macd_bb_ichimoku",
                ],
            ),
            SemanticTest(
                name="tech_rsi_in_zero_one_hundred",
                description="Computed RSI samples on any non-empty close series must lie in [0, 100].",
                inputs={"symbol": "AAPL", "studies": ["RSI"]},
                assertions=["every_rsi_sample_between_0_and_100"],
            ),
            SemanticTest(
                name="tech_macd_signal_lag_matches_ema",
                description="MACD signal equals EMA(signal_period) of MACD line within numerical tolerance.",
                inputs={"symbol": "AAPL", "studies": ["MACD"], "macd_signal": 9},
                assertions=["macd_signal_matches_ema_within_1e-6"],
            ),
            SemanticTest(
                name="tech_no_history_returns_no_price_history_status",
                description=(
                    "When the provider returns an empty frame the response carries"
                    " status=no_price_history with an explicit next_actions list rather than blank rows."
                ),
                inputs={"symbol": "DOES_NOT_EXIST"},
                assertions=[
                    "status_equals_no_price_history",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="tech_crypto_routes_to_binance",
                description="A USDT-quoted crypto symbol routes through the binance fallback.",
                inputs={"symbol": "BTCUSDT", "studies": ["RSI"]},
                assertions=["provider_chain_used_binance"],
            ),
        ],
    )


__all__ = ["tech"]
