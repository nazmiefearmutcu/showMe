"""NGAS — Natural Gas (Henry Hub) futures monitor.

Tracks the Henry Hub natural gas futures contract (NG=F) and its
European TTF cousin as a price-action pane. Contract unit
(USD/MMBtu) and front-month expiry are declared explicitly so the
viewer never confuses a $/MMBtu print for a per-therm or per-mcf
price.
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
def ngas() -> FunctionManifest:
    return FunctionManifest(
        code="NGAS",
        name="Natural Gas Futures",
        category=Category.COMMODITIES,
        intent=(
            "Monitor the Henry Hub natural-gas futures benchmark (and TTF "
            "European cousin) with explicit USD/MMBtu unit, front-month "
            "expiry, and seasonal context."
        ),
        asset_classes=[AssetClass.COMMODITY, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="contract",
                label="Contract",
                control=ControlKind.SELECT,
                required=True,
                description="Benchmark natural-gas contract.",
                options=["NG=F", "TTF=F"],
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
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "contract": "NG=F",
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
            "NGAS pulls Henry Hub natural-gas (NG=F) or TTF (TTF=F) futures "
            "candles from yfinance, resolves the active front-month expiry, "
            "and exposes contract_unit (USD/MMBtu) and expiry_month on the "
            "card row. Seasonality matters: NG has strong winter-heating and "
            "summer-cooling demand signatures; the methodology footer notes "
            "the active season and links to the HDD/CDD context from WETR. "
            "No silent unit conversions — if a feed returns therms or mcf "
            "they are not converted in place; a warning is emitted instead."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior session close"},
            ),
            "mmbtu_to_therm": Formula(
                expression=r"price_{therm} = price_{MMBtu} \div 10",
                variables={"price_MMBtu": "USD per MMBtu"},
                notes="Reference-only conversion; NGAS never silently flips units.",
            ),
        },
        field_dict={
            "contract": FieldDef(description="Natural-gas futures ticker (NG=F or TTF=F).", source="input"),
            "contract_unit": FieldDef(description="Quoted unit (USD/MMBtu for both NG and TTF).", source="curated"),
            "expiry_month": FieldDef(description="Front-month delivery (e.g. 2026-06).", source="provider"),
            "candles[].c": FieldDef(unit="USD/MMBtu", description="Close price.", source="provider"),
            "open_interest": FieldDef(unit="contracts", description="Listed open interest.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["price_above", "price_below", "change_pct_above", "change_pct_below"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="ngas_henry_hub_unit_is_mmbtu",
                description="NGAS for NG=F declares USD/MMBtu as the contract unit on the card.",
                inputs={"contract": "NG=F", "range": "6M", "interval": "1d"},
                assertions=[
                    "candles_non_empty",
                    "contract_unit_is_usd_per_mmbtu",
                    "expiry_month_present",
                ],
            ),
            SemanticTest(
                name="ngas_no_silent_unit_flip",
                description="If provider returns therms, NGAS warns instead of dividing by 10 silently.",
                inputs={"contract": "NG=F", "_mock": "unit_therm_return"},
                assertions=["warning_mentions_unit_mismatch"],
            ),
        ],
    )


__all__ = ["ngas"]
