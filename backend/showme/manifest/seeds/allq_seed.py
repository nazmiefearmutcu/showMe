"""ALLQ — Dealer quote ladder (TRACE-proxy).

Bloomberg ``ALLQ<GO>`` analogue: a dealer-quote ladder for a bond with
per-dealer bid, ask, mid, size, quote time, and the spread in basis
points of the price. Without an authenticated dealer/TRACE feed the rows
are explicitly composite/proxy quotes marked ``trace_proxy_model`` so
they are never confused with executable dealer prices.
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
def allq() -> FunctionManifest:
    return FunctionManifest(
        code="ALLQ",
        name="Dealer Quote Ladder",
        category=Category.BONDS_RATES,
        intent=(
            "Show a dealer-quote ladder for a bond with per-dealer bid, ask, mid,"
            " size, quote time, and the spread in basis points of price, so an"
            " operator can read indicative liquidity."
        ),
        asset_classes=[AssetClass.BOND],
        inputs=[
            InputSpec(
                name="symbol",
                label="Bond",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Bond identifier (CUSIP/ISIN/internal alias).",
            ),
            InputSpec(
                name="mid",
                label="Composite mid",
                control=ControlKind.NUMBER,
                required=False,
                description="Composite mid price used to anchor the proxy ladder.",
                min=0.01,
                max=1000.0,
                step=0.001,
            ),
            InputSpec(
                name="spread",
                label="Spread (points)",
                control=ControlKind.NUMBER,
                required=False,
                description="Bid/ask spread expressed in price points.",
                min=0.0,
                max=10.0,
                step=0.0001,
            ),
            InputSpec(
                name="size",
                label="Indicative size",
                control=ControlKind.NUMBER,
                required=False,
                description="Indicative notional per quote (USD).",
                min=1_000.0,
                max=1_000_000_000.0,
                step=1_000.0,
                unit="USD",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "mid": 99.75,
            "spread": 0.18,
            "size": 1_000_000.0,
            "provider_mode": DataMode.MODELED.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows", "spread_curve", "summary", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.DEPTH_LADDER,
            x_axis=AxisSpec(type="category", label="Dealer"),
            y_axis=[
                AxisSpec(type="numeric", unit="price", label="Bid/Ask"),
                AxisSpec(type="numeric", unit="bp", label="Spread of price"),
            ],
            panes=[
                PaneGrammar(name="ladder", series_kind="bar", height_pct=60),
                PaneGrammar(name="spread_curve", series_kind="bar", height_pct=40),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="dealer", label="Dealer", kind="text", width_hint=140),
                ColumnSpec(key="bid", label="Bid", kind="number", format="%.4f"),
                ColumnSpec(key="ask", label="Ask", kind="number", format="%.4f"),
                ColumnSpec(key="mid", label="Mid", kind="number", format="%.4f"),
                ColumnSpec(key="spread_points", label="Spread (pts)", kind="number", format="%.4f"),
                ColumnSpec(key="spread_bps_of_price", label="Spread (bp)", kind="number", format="%.1f", unit="bp"),
                ColumnSpec(key="size", label="Size", kind="currency", unit="USD", format="%.0f"),
                ColumnSpec(key="quote_time", label="Quoted at", kind="datetime"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="best_bid", label="Best bid", kind="big_number"),
                CardSlot(key="best_ask", label="Best ask", kind="big_number"),
                CardSlot(key="mid", label="Mid", kind="kpi"),
                CardSlot(key="quoted_dealers", label="Dealers", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ALLQ is a dealer-quote-style view. Without an authenticated dealer/TRACE feed the engine"
            " builds three composite/proxy rows from the operator's ``mid`` and ``spread`` inputs"
            " (composite A: spread/2 around mid; composite B: asymmetric ~0.7/0.8; TRACE proxy:"
            " full spread either side). For every row mid, spread_points, and spread_bps_of_price"
            " are derived client-side as (bid+ask)/2, ask−bid, and (spread/mid)·10 000 respectively."
            " Rows are explicitly labelled ``source_mode=trace_proxy_model`` and a warning is set so"
            " they are never confused with executable dealer prices."
        ),
        formula_dict={
            "spread_bps_of_price": Formula(
                expression=r"spread_{bp} = \frac{ask - bid}{(bid + ask)/2} \times 10{,}000",
                variables={"bid": "Dealer bid price", "ask": "Dealer ask price"},
                notes="Spread expressed in basis points of price (not yield).",
            ),
        },
        field_dict={
            "rows[].dealer": FieldDef(description="Dealer name or composite tag.", source="catalog"),
            "rows[].bid": FieldDef(description="Indicative bid price.", source="adapter"),
            "rows[].ask": FieldDef(description="Indicative ask price.", source="adapter"),
            "rows[].mid": FieldDef(description="Average of bid and ask.", source="computed"),
            "rows[].size": FieldDef(unit="USD", description="Indicative notional size.", source="adapter"),
            "rows[].spread_points": FieldDef(description="Bid/ask spread in price points.", source="computed"),
            "rows[].spread_bps_of_price": FieldDef(unit="bp", description="Bid/ask spread expressed in bp of mid.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["spread_above", "spread_below", "size_above"],
            delivery=["log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="allq_proxy_quotes_are_labelled",
                description=(
                    "Without a live dealer feed the response is marked source_mode=trace_proxy_model"
                    " and a warning explains the row is a composite proxy, not an executable price."
                ),
                inputs={"symbol": "US10Y"},
                assertions=[
                    "source_mode_equals_trace_proxy_model",
                    "warning_mentions_proxy_or_composite",
                ],
            ),
            SemanticTest(
                name="allq_spread_bps_matches_formula",
                description="For every row spread_bps_of_price equals (ask − bid) / mid × 10 000 within 0.01 bp.",
                inputs={"symbol": "US10Y", "mid": 100.0, "spread": 0.20},
                assertions=["every_row_spread_bps_matches_formula_within_0_01"],
            ),
            SemanticTest(
                name="allq_best_bid_ask_are_extrema",
                description="summary.best_bid equals max(row.bid) and summary.best_ask equals min(row.ask).",
                inputs={"symbol": "US10Y"},
                assertions=[
                    "summary_best_bid_equals_max_row_bid",
                    "summary_best_ask_equals_min_row_ask",
                ],
            ),
            SemanticTest(
                name="allq_three_proxy_dealers_present",
                description="Without a live feed the ladder ships three composite/proxy rows so the layout stays stable.",
                inputs={"symbol": "US10Y"},
                assertions=["rows_length_equals_3"],
            ),
        ],
    )


__all__ = ["allq"]
