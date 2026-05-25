"""HP — Historical Price (Bloomberg HP<GO> analogue).

Server-side this is an alias for the price-history pipeline (server.py
``_execute_price_history_alias``) — same underlying OHLCV fetcher as GP
but with deeper bars, range/interval/depth/chart-style controls, and a
key-levels right-rail in the UI. Asset coverage matches GP.
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
def hp() -> FunctionManifest:
    return FunctionManifest(
        code="HP",
        name="Historical Price",
        category=Category.CHARTS_TECH,
        intent=(
            "Drill into deep historical OHLCV for a single instrument with "
            "configurable depth, chart style, and key-level overlays."
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
                description="Canonical security identifier.",
            ),
            InputSpec(
                name="range",
                label="Range",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window.",
                options=["1M", "3M", "6M", "1Y", "5Y", "max"],
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval (validated against range).",
                options=["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
                depends_on=["range"],
            ),
            InputSpec(
                name="depth",
                label="Bar depth",
                control=ControlKind.SELECT,
                required=False,
                description="Max bars to request from the provider chain.",
                options=["300", "1000", "3000", "10000"],
            ),
            InputSpec(
                name="chart_style",
                label="Chart style",
                control=ControlKind.SELECT,
                required=False,
                description="Render style for the price pane.",
                options=["candle", "line", "area"],
            ),
            InputSpec(
                name="compare",
                label="Compare with",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Overlay a second instrument normalized to 100 at range start.",
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
            "range": "1Y",
            "interval": "1d",
            "depth": "1000",
            "chart_style": "candle",
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
        # The price-history alias actually returns ``ohlcv``/``bars``/``rows``
        # keys (server.py:_execute_price_history_alias). Pin ``ohlcv`` as the
        # canonical contract field so downstream callers can rely on it.
        output_contract=OutputContract(
            must_have=["ohlcv", "winner", "resolution", "bar_count"],
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
                AxisSpec(type="numeric", unit="quote_ccy", label="Price"),
                AxisSpec(type="numeric", unit="", label="Volume"),
            ],
            panes=[
                PaneGrammar(name="price", series_kind="candle", height_pct=75),
                PaneGrammar(name="volume", series_kind="histogram", height_pct=25),
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
                CardSlot(key="last", label="Last", kind="big_number", unit="quote_ccy"),
                CardSlot(key="bar_count", label="Bars", kind="kpi"),
                CardSlot(key="winner", label="Source", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "HP is the deep-history alias: server.py:_execute_price_history_alias races the configured "
            "OHLCV adapters per asset class (binance/coingecko for CRYPTO, then yfinance) and returns "
            "the longest, oldest-first-bar history. Compare overlays normalize to 100 at the first "
            "visible bar. Key levels (52w high/low, ATH, prior close) are computed on the returned "
            "series. Pan/zoom is preserved across refresh via the first-seed-focus pattern."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior close"},
            ),
            "fifty_two_week_high": Formula(
                expression=r"\max(close_{t-252..t})",
                variables={"close": "Daily close series"},
            ),
        },
        field_dict={
            "ohlcv[].t": FieldDef(unit="epoch_ms", description="Bar open time.", source="provider"),
            "ohlcv[].o": FieldDef(unit="quote_ccy", description="Open price.", source="provider"),
            "ohlcv[].h": FieldDef(unit="quote_ccy", description="High price.", source="provider"),
            "ohlcv[].l": FieldDef(unit="quote_ccy", description="Low price.", source="provider"),
            "ohlcv[].c": FieldDef(unit="quote_ccy", description="Close price.", source="provider"),
            "ohlcv[].v": FieldDef(unit="base_or_quote", description="Volume.", source="provider"),
            "winner": FieldDef(description="Adapter that returned the longest history.", source="alias"),
            "resolution": FieldDef(description="Normalized interval string.", source="alias"),
            "bar_count": FieldDef(unit="bars", description="Number of returned bars.", source="alias"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "new_52w_high", "new_52w_low"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="hp_aapl_1y_1d_returns_deep_history",
                description="HP returns a non-empty ohlcv array with bar_count > 0 and a winner source.",
                inputs={"symbol": "AAPL", "range": "1Y", "interval": "1d", "depth": "1000"},
                assertions=[
                    "ohlcv_non_empty",
                    "bar_count_positive",
                    "winner_is_non_empty_string",
                    "candles_time_monotonic",
                ],
            ),
            SemanticTest(
                name="hp_btcusdt_5m_uses_crypto_adapter",
                description="HP for crypto sources from binance/coingecko, not yfinance, for intraday bars.",
                inputs={"symbol": "BTCUSDT", "range": "1M", "interval": "5m"},
                assertions=[
                    "winner_in_crypto_adapter_set",
                    "ohlcv_non_empty",
                ],
            ),
            SemanticTest(
                name="hp_no_silent_zero_bars_on_failure",
                description="HP returns an empty ohlcv array with warnings rather than fabricating zeros.",
                inputs={"symbol": "ZZZZZZ", "range": "1Y", "interval": "1d"},
                assertions=[
                    "ohlcv_empty_or_warnings_present",
                    "no_synthetic_zero_candle",
                ],
            ),
        ],
    )


__all__ = ["hp"]
