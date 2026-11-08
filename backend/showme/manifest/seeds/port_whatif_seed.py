"""PORT_WHATIF — Portfolio What-If (one hypothetical trade on the current book).

Applies one hypothetical buy or sell of a symbol, at the quantity and cost per
share the user typed, on top of the current PORT book. Re-prices the book
before and after, debits or credits cash at the typed cost, and reports the
change in market value, unrealized P&L, total equity and position count.
Paper-safe: scenario projections only, nothing is sent to a broker.
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
    CachingPolicy,
    CardSchema,
    CardSlot,
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
def port_whatif() -> FunctionManifest:
    return FunctionManifest(
        code="PORT_WHATIF",
        name="Portfolio What-If",
        category=Category.PORTFOLIO,
        intent=(
            "Price one hypothetical buy or sell of a symbol against the current "
            "PORT book: the change in market value, unrealized P&L, total equity, "
            "cash and position count. Strictly research, no live execution path."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.OPTION,
            AssetClass.FUTURE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="quantity",
                label="Quantity",
                control=ControlKind.NUMBER,
                required=True,
                description=(
                    "Shares to buy (positive) or sell (negative). Required and non-zero; "
                    "no default is assumed."
                ),
                step=1,
            ),
            InputSpec(
                name="cost",
                label="Cost per share",
                control=ControlKind.NUMBER,
                required=True,
                description=(
                    "Price per share the trade is booked at. Required and positive; "
                    "no default is assumed."
                ),
                min=0,
                step=0.01,
                unit="ccy",
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Research only. Scenario projections cannot fire orders.",
            ),
        ],
        defaults={
            "paper_mode": True,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["ccxt_broker", "yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "hypothetical_added",
                "before",
                "after",
                "delta",
                "summary",
                "rows",
                "methodology",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="before", label="Before", kind="number", format="%.2f"),
                ColumnSpec(key="after", label="After", kind="number", format="%.2f"),
                ColumnSpec(key="value", label="Change", kind="number", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_equity_delta", label="Total equity Δ", kind="big_number", unit="ccy"),
                CardSlot(key="market_value_delta", label="Market value Δ", kind="kpi", unit="ccy"),
                CardSlot(key="unrealized_pnl_delta", label="Unrealized P&L Δ", kind="kpi", unit="ccy"),
                CardSlot(key="cash_delta", label="Cash Δ", kind="kpi", unit="ccy"),
            ],
        ),
        methodology=(
            "PORT_WHATIF prices the current PORT book twice: once as it stands, "
            "and once with one hypothetical trade applied. A buy merges into the "
            "held lot of the same symbol at a weighted-average cost, or opens a "
            "lot. A sell reduces the lot first-in-first-out and realizes P&L "
            "against the lot cost. Cash is debited (buy) or credited (sell) at the "
            "typed cost; a book that tracks no cash reports no equity change. A "
            "sell larger than the holding is refused, because shorts are not "
            "modelled. Quotes are fetched once and shared by both runs. Strictly "
            "research; the trade never reaches a broker."
        ),
        formula_dict={
            "CashDelta": Formula(
                expression=r"\Delta C = -q \cdot c",
                variables={
                    "q": "Signed quantity (negative for a sell)",
                    "c": "Cost per share",
                },
            ),
            "WeightedCost": Formula(
                expression=r"\bar{c}' = (q_0 \bar{c}_0 + q\,c) / (q_0 + q)",
                variables={
                    "q_0": "Quantity held in the lot before the buy",
                    "\\bar{c}_0": "Lot average cost before the buy",
                },
                notes="Applies to a buy into a held lot.",
            ),
            "RealizedPnL": Formula(
                expression=r"R = \sum_{sold} (c - \bar{c}_{lot}) \cdot q_{sold}",
                variables={},
                notes="FIFO over lots of the same symbol and currency.",
            ),
            "TotalEquityDelta": Formula(
                expression=r"\Delta E = (MV^{after} + C^{after}) - (MV^{before} + C^{before})",
                variables={},
                notes="Withheld (None) when the book tracks no cash.",
            ),
        },
        field_dict={
            "hypothetical_added": FieldDef(description="The trade applied: symbol, quantity, cost per share.", source="computed"),
            "before": FieldDef(description="PORT output for the current book.", source="computed"),
            "after": FieldDef(description="PORT output for the book with the trade applied.", source="computed"),
            "delta": FieldDef(description="Change in market value, unrealized P&L, position count and total equity.", source="computed"),
            "summary": FieldDef(description="Trade cash effect, equity and P&L changes in the trade currency.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="port_whatif_paper_mode_defaults_true",
                description="What-if surfaces are paper-safe.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="port_whatif_missing_cost_needs_input",
                description="A missing cost is an explicit needs_input state, never a zero-cost gain.",
                inputs={"quantity": 100},
                assertions=["status == 'needs_input'", "'cost' in missing"],
            ),
            SemanticTest(
                name="port_whatif_buy_debits_cash",
                description="A buy debits cash at quantity x cost and moves equity by the price gain.",
                inputs={"quantity": 100, "cost": 100},
                assertions=[
                    "summary.cash_delta == -quantity * cost",
                    "summary.total_equity_delta == summary.market_value_delta + summary.cash_delta when cash is tracked",
                ],
            ),
            SemanticTest(
                name="port_whatif_sell_beyond_holding_refused",
                description="A sell larger than the holding is refused, never booked as a short.",
                inputs={"quantity": -50},
                assertions=["status == 'input_error' when fewer than 50 shares are held"],
            ),
            SemanticTest(
                name="port_whatif_no_broker_calls_for_scenario",
                description="Scenario evaluation never hits the broker's order endpoints.",
                inputs={},
                assertions=["broker_order_call_count == 0"],
            ),
        ],
    )


__all__ = ["port_whatif"]
