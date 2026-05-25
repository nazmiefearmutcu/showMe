"""MICRO — Market microstructure (depth, spread, queue).

L2 order-book microstructure tile: bid/ask spread, top-of-book size,
cumulative depth ladder, and microprice. Only Binance in our adapter
list exposes real L2 depth — every other asset class must surface as
"explicit_unavailable" rather than render a synthetic ladder. The
manifest test pins ``explicit_unavailable_when_no_depth_provider``.
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
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def micro() -> FunctionManifest:
    return FunctionManifest(
        code="MICRO",
        name="Market Microstructure",
        category=Category.SCREENING,
        intent=(
            "Show live L2 microstructure for a single symbol — bid/ask spread, top-of-book size, "
            "cumulative depth ladder, microprice, and queue imbalance — sourced from a real depth "
            "feed (Binance). When no depth provider is configured for the asset class, MICRO is "
            "explicit_unavailable rather than rendering a fabricated ladder."
        ),
        asset_classes=[AssetClass.CRYPTO],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Symbol with an L2 depth feed (Binance spot, e.g. BTCUSDT).",
            ),
            InputSpec(
                name="depth_levels",
                label="Depth levels",
                control=ControlKind.SELECT,
                required=True,
                description="How many price levels per side to surface.",
                options=[5, 10, 20, 50, 100],
            ),
            InputSpec(
                name="aggregation_bps",
                label="Price agg (bps)",
                control=ControlKind.NUMBER,
                required=False,
                description="Aggregate ladder rows into buckets this many basis points wide.",
                min=0,
                max=100,
                step=1,
                unit="bps",
            ),
            InputSpec(
                name="refresh_ms",
                label="Refresh (ms)",
                control=ControlKind.NUMBER,
                required=False,
                description="Snapshot refresh interval.",
                min=100,
                max=5000,
                step=100,
                unit="ms",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "symbol": "BTCUSDT",
            "depth_levels": 20,
            "aggregation_bps": 0,
            "refresh_ms": 500,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        # Binance is the only adapter in showme.providers that exposes a real
        # L2 depth feed. cached_snapshot is the only legitimate fallback —
        # any other path must return explicit_unavailable per the wave2 spec.
        provider_chain=ProviderChain(
            primary="binance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=1, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "symbol", "bids", "asks", "spread_bps", "microprice", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.DEPTH_LADDER,
            x_axis=AxisSpec(type="numeric", unit="size", label="Cumulative size"),
            y_axis=AxisSpec(type="numeric", unit="quote_ccy", label="Price"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="price", label="Price", kind="currency", format="%.4f"),
                ColumnSpec(key="size", label="Size", kind="number", format="%.6f"),
                ColumnSpec(key="cum_size", label="Cum.", kind="number", format="%.6f"),
                ColumnSpec(key="notional", label="Notional", kind="currency", format="si"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="badge"),
                CardSlot(key="bid", label="Bid", kind="big_number", unit="quote_ccy"),
                CardSlot(key="ask", label="Ask", kind="big_number", unit="quote_ccy"),
                CardSlot(key="spread_bps", label="Spread", kind="kpi", unit="bps"),
                CardSlot(key="microprice", label="Microprice", kind="big_number", unit="quote_ccy"),
                CardSlot(key="imbalance", label="Imbalance", kind="trend_pill"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MICRO pulls a snapshot from the Binance REST depth endpoint at refresh_ms cadence — "
            "GET /api/v3/depth?symbol={SYMBOL}&limit={depth_levels}. Bids and asks are returned "
            "sorted (best on top). spread_bps = (best_ask - best_bid) / mid * 10000. microprice = "
            "(best_bid * ask_size + best_ask * bid_size) / (bid_size + ask_size) — the size-weighted "
            "mid that better tracks the next trade. imbalance = (bid_size - ask_size) / "
            "(bid_size + ask_size) in [-1, 1]. aggregation_bps optionally buckets adjacent price "
            "levels. Asset classes without a configured L2 provider (equity, ETF, fx, commodity, "
            "future, index, bond) are returned as explicit_unavailable with a next_action pointing "
            "to the QUOTE pane — MICRO never renders a synthetic ladder."
        ),
        formula_dict={
            "spread_bps": Formula(
                expression=r"\text{spread}_{bps} = \frac{a_1 - b_1}{(a_1 + b_1) / 2} \times 10000",
                variables={"a_1": "Best ask price", "b_1": "Best bid price"},
            ),
            "microprice": Formula(
                expression=r"\mu = \frac{b_1 \cdot s_a + a_1 \cdot s_b}{s_a + s_b}",
                variables={
                    "b_1": "Best bid price",
                    "a_1": "Best ask price",
                    "s_b": "Best-bid size",
                    "s_a": "Best-ask size",
                },
                notes="Size-weighted mid; better predictor of next trade than mid.",
            ),
            "imbalance": Formula(
                expression=r"I = \frac{s_b - s_a}{s_b + s_a}",
                variables={"s_b": "Best-bid size", "s_a": "Best-ask size"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Canonical symbol with depth feed.", source="input"),
            "bids[].price": FieldDef(unit="quote_ccy", description="Bid level price.", source="binance"),
            "bids[].size": FieldDef(unit="base_ccy", description="Bid level resting size.", source="binance"),
            "asks[].price": FieldDef(unit="quote_ccy", description="Ask level price.", source="binance"),
            "asks[].size": FieldDef(unit="base_ccy", description="Ask level resting size.", source="binance"),
            "spread_bps": FieldDef(unit="bps", description="(ask - bid) / mid in basis points.", source="computed"),
            "microprice": FieldDef(unit="quote_ccy", description="Size-weighted mid.", source="computed"),
            "imbalance": FieldDef(unit="[-1,1]", description="Top-of-book size imbalance.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="micro_btcusdt_returns_real_l2_ladder",
                description="MICRO for BTCUSDT returns bids and asks of length=depth_levels with strictly monotonic prices.",
                inputs={"symbol": "BTCUSDT", "depth_levels": 20},
                assertions=[
                    "bids_length_equals_20",
                    "asks_length_equals_20",
                    "bids_prices_strictly_decreasing",
                    "asks_prices_strictly_increasing",
                ],
            ),
            SemanticTest(
                name="micro_spread_bps_positive_and_consistent",
                description="spread_bps is positive and equals the documented formula within float tolerance.",
                inputs={"symbol": "BTCUSDT"},
                assertions=[
                    "spread_bps_is_positive",
                    "spread_bps_matches_formula_within_tolerance",
                ],
            ),
            SemanticTest(
                name="micro_explicit_unavailable_when_no_depth_provider",
                description="For asset classes without an L2 depth provider (AAPL equity), MICRO returns explicit_unavailable rather than a synthetic ladder.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_is_explicit_unavailable",
                    "bids_is_empty_array",
                    "asks_is_empty_array",
                    "no_synthetic_ladder",
                    "next_action_points_to_quote_pane",
                ],
            ),
            SemanticTest(
                name="micro_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={"symbol": "BTCUSDT"},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="micro_provider_unavailable_returns_empty_ladder_not_synthetic",
                description="When Binance is unreachable, bids=[] asks=[] and data_mode=provider_unavailable, no fabricated levels.",
                inputs={"symbol": "BTCUSDT"},
                assertions=[
                    "bids_is_empty_array_on_provider_failure",
                    "asks_is_empty_array_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["micro"]
