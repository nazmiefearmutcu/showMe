"""BGAS — Natural Gas Spot (Henry Hub).

Tracks the Henry Hub natural-gas spot price. The live leg is the NYMEX
natural-gas front-month futures ticker (NG=F, USD/MMBtu) from yfinance; when
the EIA adapter is configured the EIA Henry Hub spot series is served instead.
BGAS serves NG=F only: any other contract is refused with an explicit
input_error rather than served under this natural-gas identity. Expiry is the
computed NYMEX front-month delivery, so a roll is never mistaken for a gap.
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
        name="Natural Gas Spot",
        category=Category.COMMODITIES,
        intent=(
            "Track the Henry Hub natural gas spot price: the NG=F front-month "
            "futures contract in USD/MMBtu with its computed delivery month, or "
            "the EIA Henry Hub spot series when configured."
        ),
        asset_classes=[AssetClass.COMMODITY, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="contract",
                label="Contract",
                control=ControlKind.SELECT,
                required=True,
                description="Henry Hub natural gas futures contract. BGAS serves NG=F only.",
                options=["NG=F"],
            ),
            InputSpec(
                name="range",
                label="Range",
                control=ControlKind.SELECT,
                required=True,
                description="Lookback window for the daily history.",
                options=["1M", "3M", "6M", "1Y"],
            ),
            InputSpec(
                name="interval",
                label="Interval",
                control=ControlKind.SELECT,
                required=True,
                description="Bar interval. BGAS serves daily bars only.",
                options=["1d"],
            ),
        ],
        defaults={
            "contract": "NG=F",
            "range": "1Y",
            "interval": "1d",
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
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
                AxisSpec(type="numeric", unit="USD/MMBtu", label="Price"),
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
                CardSlot(key="last", label="Last", kind="big_number", unit="USD/MMBtu"),
                CardSlot(key="change_pct", label="Δ %", kind="trend_pill", unit="%"),
                CardSlot(key="contract_unit", label="Unit", kind="badge"),
                CardSlot(key="expiry_month", label="Expiry", kind="badge"),
                CardSlot(key="open_interest", label="OI", kind="kpi", unit="contracts"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BGAS pulls the Henry Hub natural gas front-month futures contract "
            "(NG=F) from yfinance, or the EIA Henry Hub spot series when EIA is "
            "configured. Quotes are in USD/MMBtu. The delivery month is computed "
            "from the NYMEX natural-gas last-trade rule (exchange holidays are not "
            "modelled) and reported as expiry_month; EIA spot prints carry none. "
            "Other contracts are refused with an explicit input_error."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior session close"},
            ),
        },
        field_dict={
            "contract": FieldDef(description="Natural gas futures contract ticker (NG=F only).", source="input"),
            "contract_unit": FieldDef(description="Quoted unit: USD/MMBtu (Henry Hub).", source="curated"),
            "expiry_month": FieldDef(
                description="Front-month NYMEX delivery (e.g. 2026-12), computed from the last-trade rule; null for EIA spot.",
                source="curated",
            ),
            "candles[].o": FieldDef(unit="USD/MMBtu", description="Open price in USD/MMBtu.", source="provider"),
            "candles[].c": FieldDef(unit="USD/MMBtu", description="Close price in USD/MMBtu.", source="provider"),
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
                name="bgas_ng_returns_candles_with_unit",
                description="BGAS NG=F daily returns candles plus contract_unit and expiry_month.",
                inputs={"contract": "NG=F", "range": "6M", "interval": "1d"},
                assertions=[
                    "candles_non_empty",
                    "contract_unit_is_usd_per_mmbtu",
                    "expiry_month_present",
                ],
            ),
            SemanticTest(
                name="bgas_no_synthetic_zero_candles",
                description="A non-natural-gas contract returns an explicit input_error, not fabricated bars.",
                inputs={"contract": "RB=F", "range": "1Y", "interval": "1d"},
                assertions=[
                    "candles_empty_or_warnings_present",
                    "no_synthetic_zero_candle",
                ],
            ),
        ],
    )


__all__ = ["bgas"]
