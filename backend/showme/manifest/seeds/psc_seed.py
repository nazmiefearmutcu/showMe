"""PSC — Position Sizing Calculator.

Risk-based sizing from account size, per-trade risk fraction, entry,
stop and target: risk budget = account × risk_pct; unit risk =
|entry − stop|; shares = risk budget / unit risk; R multiple and a
simple Kelly fraction from win-rate assumptions. Resynced to the
shipped handler (``engine/functions/portfolio/psc.py``) by fix lane
F14 — the previous seed described an unimplemented "Price Scenario
Center" shock-propagation contract.
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
def psc() -> FunctionManifest:
    return FunctionManifest(
        code="PSC",
        name="Position Sizing Calculator",
        category=Category.PORTFOLIO,
        intent=(
            "Size a trade from account equity, per-trade risk, entry, stop and target — "
            "returning the risk budget, share count, notional, R multiple and a simple "
            "Kelly fraction so the operator can compare fixed-risk versus Kelly sizing."
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
                name="account",
                label="Account size",
                control=ControlKind.NUMBER,
                required=False,
                description="Equity used for the risk budget.",
                min=1.0,
                step=100.0,
            ),
            InputSpec(
                name="risk_pct",
                label="Risk per trade",
                control=ControlKind.NUMBER,
                required=False,
                description="Fraction of account equity risked if the stop is hit (0.01 = 1%).",
                min=0.0,
                max=1.0,
                step=0.001,
            ),
            InputSpec(
                name="entry",
                label="Entry",
                control=ControlKind.NUMBER,
                required=False,
                description="Planned entry price.",
                min=0.0,
                step=0.01,
            ),
            InputSpec(
                name="stop",
                label="Stop",
                control=ControlKind.NUMBER,
                required=False,
                description="Stop price; unit risk = |entry − stop|.",
                min=0.0,
                step=0.01,
            ),
            InputSpec(
                name="target",
                label="Target",
                control=ControlKind.NUMBER,
                required=False,
                description="Target price; reward per share = |target − entry|.",
                min=0.0,
                step=0.01,
            ),
            InputSpec(
                name="win_rate",
                label="Win rate (Kelly)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Assumed win probability used by the simple Kelly fraction.",
                min=0.0,
                max=1.0,
                step=0.01,
            ),
            InputSpec(
                name="side",
                label="Side",
                control=ControlKind.SELECT,
                required=False,
                description="Trade direction echoed into the summary.",
                options=["LONG", "SHORT"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Research-only: PSC is compute-only and never fires a live order.",
            ),
        ],
        defaults={
            "account": 10000.0,
            "risk_pct": 0.01,
            "entry": 100.0,
            "stop": 95.0,
            "target": 115.0,
            "win_rate": 0.55,
            "side": "LONG",
            "paper_mode": True,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.MODELED,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "side",
                "account",
                "risk_pct",
                "risk_dollars",
                "entry",
                "stop",
                "target",
                "per_share_risk",
                "shares",
                "notional",
                "r_multiple",
                "kelly_fraction",
                "rows",
                "summary",
                "methodology",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", unit="", label="Metric"),
            y_axis=AxisSpec(type="numeric", unit="", label="Value"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4g"),
                ColumnSpec(key="meaning", label="Meaning", kind="text"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="shares", label="Shares", kind="big_number"),
                CardSlot(key="risk_dollars", label="Risk $", kind="kpi", unit="ccy"),
                CardSlot(key="notional", label="Notional", kind="kpi", unit="ccy"),
                CardSlot(key="r_multiple", label="R multiple", kind="kpi"),
                CardSlot(key="kelly_fraction", label="Kelly", kind="kpi", unit="%"),
                CardSlot(key="leverage_implied", label="Leverage (implied)", kind="kpi", unit="x"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
            ],
        ),
        methodology=(
            "PSC is pure computation over operator-supplied inputs — no provider call. "
            "risk budget = account × risk_pct; unit risk = |entry − stop|; shares = risk "
            "budget / unit risk; notional = shares × entry; implied leverage = notional / "
            "account. R multiple = |target − entry| / unit risk. The simple Kelly fraction "
            "= max(0, (win_rate × R − (1 − win_rate)) / R) using the same R multiple. When "
            "entry == stop the handler returns an empty payload with a 'can't size' warning "
            "instead of dividing by zero. paper_mode defaults true: PSC never executes."
        ),
        formula_dict={
            "RiskBudget": Formula(
                expression=r"risk\_dollars = account \times risk\_pct",
                variables={"account": "Account equity", "risk_pct": "Fraction risked"},
            ),
            "Shares": Formula(
                expression=r"shares = \frac{risk\_dollars}{|entry - stop|}",
                variables={"entry": "Planned entry", "stop": "Stop price"},
            ),
            "RMultiple": Formula(
                expression=r"R = \frac{|target - entry|}{|entry - stop|}",
                variables={},
            ),
            "Kelly": Formula(
                expression=r"kelly = \max\left(0, \frac{w \cdot R - (1 - w)}{R}\right)",
                variables={"w": "Assumed win rate", "R": "R multiple"},
            ),
        },
        field_dict={
            "risk_pct": FieldDef(description="Fraction of account equity risked if the stop is hit.", source="input"),
            "risk_dollars": FieldDef(unit="ccy", description="account × risk_pct.", source="computed"),
            "per_share_risk": FieldDef(description="Absolute distance between entry and stop.", source="computed"),
            "reward_per_share": FieldDef(description="Absolute distance between target and entry.", source="computed"),
            "r_multiple": FieldDef(description="Reward divided by risk per unit.", source="computed"),
            "shares": FieldDef(description="risk_dollars / unit risk.", source="computed"),
            "notional": FieldDef(unit="ccy", description="shares × entry.", source="computed"),
            "leverage_implied": FieldDef(unit="x", description="notional / account.", source="computed"),
            "kelly_fraction": FieldDef(unit="fraction", description="Simple Kelly from win-rate and R multiple.", source="computed"),
            "kelly_dollars": FieldDef(unit="ccy", description="account × kelly_fraction.", source="computed"),
            "kelly_shares": FieldDef(description="kelly_dollars / entry.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="psc_shares_match_risk_budget_over_unit_risk",
                description="shares == (account × risk_pct) / |entry − stop| within tolerance.",
                inputs={"account": 10000, "risk_pct": 0.01, "entry": 100, "stop": 95},
                assertions=["shares_equals_risk_dollars_over_unit_risk"],
            ),
            SemanticTest(
                name="psc_entry_equals_stop_refuses_with_warning",
                description="entry == stop returns an empty payload with a 'can't size' warning — never a divide-by-zero size.",
                inputs={"entry": 100, "stop": 100},
                assertions=[
                    "payload_empty",
                    "warning_mentions_cant_size",
                ],
            ),
            SemanticTest(
                name="psc_kelly_is_never_negative",
                description="kelly_fraction is clamped at 0 when the win-rate × R edge is negative.",
                inputs={"win_rate": 0.2, "target": 101},
                assertions=["kelly_fraction_gte_0"],
            ),
            SemanticTest(
                name="psc_paper_mode_is_declared_safe",
                description="PSC declares paper_mode=true by default and has no order-execution path.",
                inputs={},
                assertions=[
                    "defaults.paper_mode == True",
                    "no_orders_emitted",
                ],
            ),
        ],
    )


__all__ = ["psc"]
