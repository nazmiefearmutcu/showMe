"""BGAS — Benchmark Gasoline / refined-product futures monitor.

Tracks the benchmark RBOB / heating oil / refined-product futures
contracts that anchor the gasoline complex. yfinance-style futures
tickers (RB=F, HO=F, etc.) are the primary source. Field dictionary
declares the contract unit (USD/gal) and delivery month so the user
cannot mistake a $/gal print for $/bbl.
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
def bgas() -> FunctionManifest:
    return FunctionManifest(
        code="BGAS",
        name="Benchmark Gasoline Futures",
        category=Category.COMMODITIES,
        intent=(
            "Track the benchmark RBOB / heating-oil / refined-product futures "
            "contracts with explicit contract unit, expiry month, and front-"
            "month roll context."
        ),
        asset_classes=[AssetClass.COMMODITY, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="contract",
                label="Contract",
                control=ControlKind.SELECT,
                required=True,
                description="Refined-product futures contract.",
                options=["RB=F", "HO=F", "BZ=F", "CL=F"],
            ),
            InputSpec(
                name="range",
                label="Range",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window.",
                options=["1M", "3M", "6M", "1Y", "5Y"],
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval.",
                options=["1h", "1d", "1wk"],
                depends_on=["range"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "contract": "RB=F",
            "range": "6M",
            "interval": "1d",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "contract",
                "candles",
                "as_of",
                "contract_unit",
                "expiry_month",
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
                AxisSpec(type="numeric", unit="$/gal", label="Price"),
                AxisSpec(type="numeric", unit="contracts", label="Volume"),
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
                CardSlot(key="last", label="Last", kind="big_number", unit="$/gal"),
                CardSlot(key="change_pct", label="Δ %", kind="trend_pill", unit="%"),
                CardSlot(key="contract_unit", label="Unit", kind="badge"),
                CardSlot(key="expiry_month", label="Expiry", kind="badge"),
                CardSlot(key="open_interest", label="OI", kind="kpi", unit="contracts"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BGAS pulls the chosen refined-product futures contract from "
            "yfinance using futures-style tickers (RB=F for RBOB, HO=F for "
            "heating oil, etc.). The handler resolves the active front-month "
            "expiry, exposes contract_unit ($/gal for RB/HO, $/bbl for CL/BZ) "
            "explicitly, and renders an OHLCV chart with the volume sub-pane. "
            "Roll context (days to expiry, prior contract close) is exposed "
            "on the card row so operators never confuse a fresh roll for a "
            "real gap."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior session close"},
            ),
        },
        field_dict={
            "contract": FieldDef(description="Futures contract ticker (e.g. RB=F).", source="input"),
            "contract_unit": FieldDef(description="Quoted unit (USD/gal for RBOB/HO, USD/bbl for CL/BZ).", source="curated"),
            "expiry_month": FieldDef(description="Front-month delivery (e.g. 2026-06).", source="provider"),
            "candles[].o": FieldDef(unit="USD/unit", description="Open price in contract unit.", source="provider"),
            "candles[].c": FieldDef(unit="USD/unit", description="Close price in contract unit.", source="provider"),
            "open_interest": FieldDef(unit="contracts", description="Listed open interest.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "change_pct_above"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="bgas_rbob_returns_candles_with_unit",
                description="BGAS RB=F daily returns candles plus contract_unit and expiry_month.",
                inputs={"contract": "RB=F", "range": "6M", "interval": "1d"},
                assertions=[
                    "candles_non_empty",
                    "contract_unit_is_usd_per_gallon",
                    "expiry_month_present",
                ],
            ),
            SemanticTest(
                name="bgas_no_synthetic_zero_candles",
                description="A failing contract returns warnings, not fabricated zero bars.",
                inputs={"contract": "RB=F", "range": "MAX", "interval": "1m"},
                assertions=[
                    "candles_empty_or_warnings_present",
                    "no_synthetic_zero_candle",
                ],
            ),
        ],
    )


__all__ = ["bgas"]
