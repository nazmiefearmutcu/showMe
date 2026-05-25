"""BOIL — Brent / WTI crude oil futures benchmark monitor.

Tracks Brent (BZ=F) and WTI (CL=F) crude-oil benchmarks as a paired
chart pane. Contract unit (USD/bbl) and front-month delivery are
declared so users never confuse spot oil with a futures print, and a
Brent-WTI spread card surfaces the regional differential at a glance.
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
def boil() -> FunctionManifest:
    return FunctionManifest(
        code="BOIL",
        name="Brent / WTI Crude Oil",
        category=Category.COMMODITIES,
        intent=(
            "Track Brent (BZ=F) and WTI (CL=F) crude-oil futures benchmarks "
            "with explicit USD/bbl unit, front-month expiry, and the Brent-"
            "WTI spread for regional context."
        ),
        asset_classes=[AssetClass.COMMODITY, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="contract",
                label="Contract",
                control=ControlKind.SELECT,
                required=True,
                description="Crude-oil benchmark contract.",
                options=["BZ=F", "CL=F"],
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
                name="show_spread",
                label="Show Brent-WTI spread",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Render the Brent-WTI differential as a comparison overlay.",
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
            "contract": "BZ=F",
            "range": "6M",
            "interval": "1d",
            "show_spread": True,
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
                AxisSpec(type="numeric", unit="USD/bbl", label="Price"),
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
                CardSlot(key="last", label="Last", kind="big_number", unit="USD/bbl"),
                CardSlot(key="change_pct", label="Δ %", kind="trend_pill", unit="%"),
                CardSlot(key="contract_unit", label="Unit", kind="badge"),
                CardSlot(key="expiry_month", label="Expiry", kind="badge"),
                CardSlot(key="brent_wti_spread", label="BZ-CL", kind="kpi", unit="USD/bbl"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BOIL pulls Brent (BZ=F) or WTI (CL=F) crude-oil futures from "
            "yfinance, resolves the active front-month expiry, and exposes "
            "contract_unit (USD/bbl) explicitly. When show_spread is on, the "
            "handler fetches the sister contract and computes the Brent-WTI "
            "differential bar-by-bar (spread = BZ.close - CL.close). The "
            "spread is rendered as a comparison overlay and surfaced as a "
            "single kpi card. No synthetic backfill: if either leg is "
            "missing for a given bar, the spread for that bar is null and "
            "a warning enumerates the missing dates."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior session close"},
            ),
            "brent_wti_spread": Formula(
                expression=r"spread = BZ_{close} - CL_{close}",
                variables={"BZ_close": "Brent close USD/bbl", "CL_close": "WTI close USD/bbl"},
                notes="Positive when Brent trades above WTI (typical Atlantic premium).",
            ),
        },
        field_dict={
            "contract": FieldDef(description="Crude-oil futures ticker (BZ=F or CL=F).", source="input"),
            "contract_unit": FieldDef(description="Quoted unit (USD/bbl).", source="curated"),
            "expiry_month": FieldDef(description="Front-month delivery (e.g. 2026-06).", source="provider"),
            "brent_wti_spread": FieldDef(unit="USD/bbl", description="BZ close minus CL close (current bar).", source="computed"),
            "candles[].c": FieldDef(unit="USD/bbl", description="Close price.", source="provider"),
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
                "brent_wti_spread_above",
                "brent_wti_spread_below",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="boil_brent_unit_is_usd_per_bbl",
                description="BOIL for BZ=F declares USD/bbl as the contract unit on the card.",
                inputs={"contract": "BZ=F", "range": "6M", "interval": "1d"},
                assertions=[
                    "candles_non_empty",
                    "contract_unit_is_usd_per_bbl",
                    "expiry_month_present",
                ],
            ),
            SemanticTest(
                name="boil_spread_present_when_show_spread_true",
                description="show_spread=true populates brent_wti_spread on the card.",
                inputs={"contract": "BZ=F", "show_spread": True},
                assertions=["brent_wti_spread_present_or_null_with_warning"],
            ),
        ],
    )


__all__ = ["boil"]
