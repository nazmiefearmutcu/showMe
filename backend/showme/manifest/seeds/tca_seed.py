"""TCA — Trade Cost Analysis (post-trade).

Analyses executed fills from the local order_history store for slippage,
implementation shortfall, opportunity cost, and benchmark-relative fill
quality. Always post-trade — never mutates broker state.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
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
    ChartKind,
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
def tca() -> FunctionManifest:
    return FunctionManifest(
        code="TCA",
        name="Trade Cost Analysis",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Post-trade analysis of executed fills: implementation shortfall, slippage vs "
            "benchmark (VWAP / TWAP / Arrival), opportunity cost, and per-broker fill quality."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.FUTURE,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="transactions",
                label="Transactions",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Optional inline transaction list (JSON or CSV) to analyse instead of the "
                    "local order_history store; useful for external fill-blotter imports."
                ),
            ),
            InputSpec(
                name="symbol",
                label="Symbol filter",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Restrict analysis to one instrument.",
            ),
            InputSpec(
                name="broker",
                label="Broker filter",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict analysis to one broker adapter.",
                options=["binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker"],
            ),
            InputSpec(
                name="benchmark",
                label="Benchmark",
                control=ControlKind.SELECT,
                required=True,
                description="Reference price stream for slippage attribution.",
                options=["VWAP", "TWAP", "ARRIVAL", "IMPLEMENTATION_SHORTFALL"],
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=False,
                description="Lookback window for the transaction tail.",
                options=["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"],
            ),
            InputSpec(
                name="limit",
                label="Max fills",
                control=ControlKind.NUMBER,
                required=False,
                description="Cap on transactions analysed.",
                min=1.0,
                max=10000.0,
                step=50.0,
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode for the reference price series.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "benchmark": "VWAP",
            "window": "1M",
            "limit": 200,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="ccxt_broker",
            fallbacks=["binance", "yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "benchmark", "rows", "summary"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.ATTRIBUTION_BAR,
            x_axis=AxisSpec(type="category", unit="", label="Order"),
            y_axis=AxisSpec(type="numeric", unit="bps", label="Slippage"),
            panes=[
                PaneGrammar(name="slippage", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="order_id", label="Order", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="broker", label="Broker", kind="tag"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%.4f"),
                ColumnSpec(key="avg_fill_px", label="Avg Fill", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="benchmark_px", label="Benchmark", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="arrival_px", label="Arrival", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="slippage_bps", label="Slip bps", kind="number", format="%.1f"),
                ColumnSpec(key="is_bps", label="IS bps", kind="number", format="%.1f"),
                ColumnSpec(key="opportunity_bps", label="Opp bps", kind="number", format="%.1f"),
                ColumnSpec(key="filled_at", label="Filled", kind="datetime"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="fill_count", label="Fills", kind="kpi"),
                CardSlot(key="avg_slippage_bps", label="Avg Slip", kind="big_number", unit="bps"),
                CardSlot(key="avg_is_bps", label="Avg IS", kind="kpi", unit="bps"),
                CardSlot(key="worst_slippage_bps", label="Worst Slip", kind="kpi", unit="bps"),
                CardSlot(key="total_cost_usd", label="Total Cost", kind="kpi", unit="USD"),
                CardSlot(key="benchmark", label="Benchmark", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TCA pulls executed fills from order_history (or the inline transactions payload), joins "
            "each fill against the chosen benchmark price series (VWAP / TWAP / Arrival / "
            "Implementation Shortfall) sourced from the market-data adapter for the order's window, "
            "and computes per-fill slippage bps = (avg_fill - benchmark) / benchmark × 10_000 × side_sign, "
            "implementation shortfall bps = (avg_fill - arrival) / arrival × 10_000 × side_sign, "
            "opportunity cost bps = (final_price - decision_price) / decision_price × 10_000 × side_sign × "
            "(1 - filled_qty / target_qty). Total-cost-USD aggregates slippage_bps × notional / 10_000. "
            "Summary KPIs are the count-weighted means across the analysed tail. TCA is strictly "
            "read-only — it never touches the broker."
        ),
        formula_dict={
            "SlippageBps": Formula(
                expression=r"slip_{bps} = \frac{avg\_fill - benchmark}{benchmark} \times 10000 \times sign(side)",
                variables={
                    "avg_fill": "Volume-weighted fill price",
                    "benchmark": "VWAP / TWAP / Arrival reference",
                    "sign(side)": "+1 BUY, -1 SELL",
                },
            ),
            "ImplementationShortfall": Formula(
                expression=r"IS_{bps} = \frac{avg\_fill - arrival}{arrival} \times 10000 \times sign(side)",
                variables={"arrival": "Mid at order arrival"},
            ),
            "OpportunityCost": Formula(
                expression=r"opp_{bps} = \frac{final - decision}{decision} \times 10000 \times sign(side) \times (1 - fill\_ratio)",
                variables={"fill_ratio": "filled_qty / target_qty"},
            ),
        },
        field_dict={
            "rows[].order_id": FieldDef(description="Broker order identifier.", source="order_history"),
            "rows[].avg_fill_px": FieldDef(unit="quote", description="Volume-weighted fill price.", source="computed"),
            "rows[].benchmark_px": FieldDef(unit="quote", description="VWAP/TWAP/Arrival reference.", source="market_data"),
            "rows[].arrival_px": FieldDef(unit="quote", description="Mid at order arrival.", source="order_history"),
            "rows[].slippage_bps": FieldDef(unit="bps", description="Signed slippage vs benchmark.", source="computed"),
            "rows[].is_bps": FieldDef(unit="bps", description="Implementation shortfall vs arrival.", source="computed"),
            "rows[].opportunity_bps": FieldDef(unit="bps", description="Cost of unfilled quantity.", source="computed"),
            "summary.avg_slippage_bps": FieldDef(unit="bps", description="Notional-weighted mean slippage.", source="computed"),
            "summary.total_cost_usd": FieldDef(unit="USD", description="Total execution cost across fills.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["avg_slippage_bps_above", "worst_slippage_bps_above"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="tca_returns_summary_with_benchmark",
                description="TCA result includes a summary block with the chosen benchmark echoed back.",
                inputs={"benchmark": "VWAP", "limit": 50},
                assertions=[
                    "summary.benchmark == 'VWAP'",
                    "summary.fill_count >= 0",
                ],
            ),
            SemanticTest(
                name="tca_per_fill_slippage_signed_by_side",
                description="A BUY filled above VWAP has positive slippage_bps; a SELL above VWAP is negative.",
                inputs={"benchmark": "VWAP"},
                assertions=[
                    "buy_above_vwap_slippage_positive",
                    "sell_above_vwap_slippage_negative",
                ],
            ),
            SemanticTest(
                name="tca_no_order_history_returns_empty",
                description="With no orders persisted, TCA returns rows=[] and summary.fill_count=0 (not synthetic rows).",
                inputs={},
                assertions=[
                    "rows == []",
                    "summary.fill_count == 0",
                ],
            ),
            SemanticTest(
                name="tca_read_only_no_broker_mutation",
                description="TCA runs without calling place_order, cancel_order, or any state-changing broker method.",
                inputs={},
                assertions=["no_broker_mutating_call_made"],
            ),
        ],
    )


__all__ = ["tca"]
