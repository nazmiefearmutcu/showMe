"""PORT_WHATIF — Portfolio Scenario Calculator.

What-if planner: apply a list of buy/sell/add/remove actions on top of
the current PORT and re-compute weights, exposure, risk metrics, and
estimated tax impact. Paper-safe — outputs are scenario projections.
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
            "Apply a list of buy/sell/add/remove actions on top of the "
            "current PORT and re-compute weights, exposure, risk metrics, "
            "and estimated tax impact under the hypothetical post-trade "
            "book. Strictly research — no live execution path."
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
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Account whose current book is the baseline.",
            ),
            InputSpec(
                name="scenario_actions",
                label="Actions",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Ordered list of hypothetical actions: "
                    "[{action: buy|sell|add|remove, symbol, qty, price?}, ...]. "
                    "Applied sequentially to the baseline."
                ),
            ),
            InputSpec(
                name="cash_floor",
                label="Cash floor",
                control=ControlKind.NUMBER,
                required=False,
                description="Reject scenarios that drive cash below this floor.",
                min=0,
                max=10000000,
                step=100,
                unit="ccy",
            ),
            InputSpec(
                name="recompute_risk",
                label="Recompute risk",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Run a lightweight σ/VaR re-estimate on the post-trade book.",
            ),
            InputSpec(
                name="ccy",
                label="Display currency",
                control=ControlKind.SELECT,
                required=False,
                description="Reporting currency.",
                options=["native", "USD", "EUR", "GBP", "TRY", "JPY"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Research only. Scenario projections cannot fire orders.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for live quotes.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "cash_floor": 0,
            "recompute_risk": True,
            "ccy": "native",
            "paper_mode": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
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
                "as_of",
                "baseline",
                "scenario_actions_applied",
                "projected",
                "deltas",
                "data_mode",
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
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="qty_now", label="Qty now", kind="number", format="%.6g"),
                ColumnSpec(key="qty_after", label="Qty after", kind="number", format="%.6g"),
                ColumnSpec(key="weight_now", label="Weight now", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="weight_after", label="Weight after", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="delta_value", label="Δ value", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="realized_pnl", label="Realized PnL", kind="currency", unit="ccy", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="projected_equity", label="Projected Equity", kind="big_number", unit="ccy"),
                CardSlot(key="cash_delta", label="Cash Δ", kind="kpi", unit="ccy"),
                CardSlot(key="exposure_delta_pct", label="Exposure Δ", kind="kpi", unit="%"),
                CardSlot(key="vol_delta", label="σ Δ", kind="kpi", unit="%"),
                CardSlot(key="realized_pnl_total", label="Realized PnL", kind="trend_pill", unit="ccy"),
                CardSlot(key="estimated_tax_impact", label="Tax Δ", kind="kpi", unit="ccy"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PORT_WHATIF starts from the credential's current PORT "
            "snapshot, then applies scenario_actions sequentially: 'buy' "
            "and 'add' increase qty (and decrement cash by qty × price); "
            "'sell' and 'remove' decrement qty (and credit cash). 'price' "
            "defaults to current last when omitted. After each action, "
            "the projected book is re-aggregated: market_value, weights, "
            "and (optionally) realized σ + VaR are re-estimated from the "
            "historical Σ window. Realized PnL is computed FIFO against "
            "current lots for accuracy; estimated_tax_impact uses the "
            "term flag on each sold lot. cash_floor protects the user "
            "from running cash negative — a violation surfaces as a "
            "warning, not a hard rejection. Strictly research; the "
            "scenario_actions payload never reaches a broker."
        ),
        formula_dict={
            "QtyAfter": Formula(
                expression=r"q_i^{after} = q_i^{base} + \sum_a \delta_{a,i}",
                variables={"δ_a,i": "Action a's qty delta on symbol i (signed)"},
            ),
            "RealizedPnL": Formula(
                expression=r"R = \sum_{sold} (p_{sell} - basis_{lot}) \cdot qty_{sold}",
                variables={},
                notes="FIFO lot matching for accuracy.",
            ),
            "WeightAfter": Formula(
                expression=r"w_i^{after} = q_i^{after} p_i / \sum_j q_j^{after} p_j",
                variables={},
            ),
        },
        field_dict={
            "baseline": FieldDef(description="Snapshot of PORT before applying actions.", source="computed_from_broker"),
            "scenario_actions_applied[]": FieldDef(description="Echo of actions with per-action result + warnings.", source="computed"),
            "projected": FieldDef(description="Post-trade book under the scenario.", source="computed"),
            "deltas": FieldDef(description="Equity, cash, exposure, σ deltas vs baseline.", source="computed"),
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
                name="port_whatif_empty_actions_no_delta",
                description="Empty scenario_actions yields projected == baseline.",
                inputs={"scenario_actions": []},
                assertions=["projected == baseline", "deltas.all_zero"],
            ),
            SemanticTest(
                name="port_whatif_actions_applied_in_order",
                description="Sequential actions accumulate; final qty matches running sum.",
                inputs={},
                assertions=["final_qty == baseline_qty + sum(action_deltas)"],
            ),
            SemanticTest(
                name="port_whatif_cash_floor_violation_warns",
                description="Scenario that drives cash below floor surfaces a warning.",
                inputs={"cash_floor": 1000},
                assertions=["warnings_non_empty when projected_cash < 1000"],
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
