"""ACCT — Multi-Account Aggregation (position roll-up across accounts).

Groups saved or supplied positions by account, marks each one with a live
last price, and shows per-account and cross-account exposure. Positions
without a live mark stay visible, carry null market value, and are excluded
from totals; they are never valued at average cost.

This describes the served handler (engine/functions/portfolio/acct.py). It
does not read broker account() snapshots: equity, cash, margin and buying
power are not returned here.
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
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def acct() -> FunctionManifest:
    return FunctionManifest(
        code="ACCT",
        name="Multi-Account Aggregation",
        category=Category.PORTFOLIO,
        intent=(
            "Roll up saved or supplied positions by account, mark them at the "
            "live last price, and show per-account and cross-account exposure. "
            "Unpriced positions stay visible and are excluded from totals."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="positions",
                label="Positions (JSON)",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Optional JSON array of {symbol, asset_class, quantity, avg_cost, last, account}. "
                    "Used only when no saved portfolio positions exist. A row without last is unpriced."
                ),
            ),
            InputSpec(
                name="mark_timeout",
                label="Mark timeout",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-symbol live mark timeout; clamped to 8-12 s.",
                min=8,
                max=12,
                step=1,
                unit="s",
            ),
        ],
        defaults={
            "mark_timeout": 8,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "accounts", "cross", "summary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_market_value", label="Market Value", kind="big_number", unit="ccy"),
                CardSlot(key="accounts_count", label="Accounts", kind="kpi"),
                CardSlot(key="positions", label="Positions", kind="kpi"),
                CardSlot(key="unpriced_positions", label="Unpriced", kind="kpi"),
            ],
        ),
        methodology=(
            "ACCT groups positions by account and marks each one at its live last price "
            "(yfinance quote). Market value is quantity times last; unrealized P&L is "
            "(last minus average cost) times quantity. Positions with no live mark are "
            "listed with null market value and unrealized P&L, counted in unpriced_positions, "
            "and excluded from every total. Cross-account exposure sums priced positions by "
            "asset class and by symbol."
        ),
        formula_dict={
            "UnrealizedPnL": Formula(
                expression=r"upnl_i = (p_i - c_i) \times q_i",
                variables={
                    "p_i": "Live last price",
                    "c_i": "Average cost",
                    "q_i": "Quantity",
                },
                notes="Null when the position has no live mark.",
            ),
        },
        field_dict={
            "accounts[].positions[].market_value": FieldDef(
                unit="ccy",
                description="Quantity times live last price; null when unpriced.",
                source="computed",
            ),
            "accounts[].positions[].unrealized_pnl": FieldDef(
                unit="ccy",
                description="(last - avg_cost) times quantity; null when unpriced.",
                source="computed",
            ),
            "cross.unpriced_symbols": FieldDef(
                description="Symbols with no live mark, excluded from totals.",
                source="computed",
            ),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="acct_unpriced_position_never_valued_at_cost",
                description="A position with no live mark has null market value and is not added to totals.",
                inputs={"positions": "[{\"symbol\":\"TLT\",\"quantity\":10,\"avg_cost\":90}]"},
                assertions=[
                    "accounts[].positions[].market_value is null for unpriced rows",
                    "cross.total_mv excludes unpriced rows",
                ],
            ),
            SemanticTest(
                name="acct_totals_are_sum_of_priced_positions",
                description="Cross-account total equals the sum of priced market values.",
                inputs={},
                assertions=["cross.total_mv == sum(priced market_value)"],
            ),
            SemanticTest(
                name="acct_no_positions_reports_ready_no_positions",
                description="With no saved or supplied positions the status is ready_no_positions, not a zero portfolio.",
                inputs={},
                assertions=["status == 'ready_no_positions'", "accounts == []"],
            ),
        ],
    )


__all__ = ["acct"]
