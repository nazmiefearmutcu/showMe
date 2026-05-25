"""REBA — Rebalance workflow.

Given target weights + a drift tolerance, REBA shows the per-symbol
buy/sell trade list that closes the gap. Paper-safe by default — REBA
emits a preview, not orders. Hand-off to EMSX is an explicit user step.
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
def reba() -> FunctionManifest:
    return FunctionManifest(
        code="REBA",
        name="Rebalance Workflow",
        category=Category.PORTFOLIO,
        intent=(
            "Given target weights and a drift tolerance, compute the "
            "per-symbol buy/sell list that closes the gap between current "
            "and target. Outputs a trade preview only — REBA never fires "
            "live orders. EMSX hand-off is an explicit user action."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Account whose current weights drive the diff.",
            ),
            InputSpec(
                name="target_weights",
                label="Target weights",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Symbol → target weight map (decimals summing to 1). "
                    "From PORT_OPT, BLAK posterior, or manual."
                ),
            ),
            InputSpec(
                name="drift_tolerance_pct",
                label="Drift tolerance",
                control=ControlKind.NUMBER,
                required=True,
                description="Per-symbol absolute drift below which no trade is suggested.",
                min=0.0,
                max=10.0,
                step=0.1,
                unit="%",
            ),
            InputSpec(
                name="min_trade_size",
                label="Min trade size",
                control=ControlKind.NUMBER,
                required=False,
                description="Skip trades below this notional.",
                min=0,
                max=100000,
                step=10,
                unit="ccy",
            ),
            InputSpec(
                name="lot_rounding",
                label="Lot rounding",
                control=ControlKind.SELECT,
                required=False,
                description="Round qty to whole shares, fractional, or contract.",
                options=["whole", "fractional", "contract"],
            ),
            InputSpec(
                name="tax_aware",
                label="Tax-aware",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, prefer selling lots that minimize realized tax.",
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Preview-only by default. No live execution path from REBA.",
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
            "drift_tolerance_pct": 1.0,
            "min_trade_size": 100,
            "lot_rounding": "whole",
            "tax_aware": False,
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
                "credential_id",
                "current_weights",
                "target_weights",
                "trades",
                "total_turnover",
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
                ColumnSpec(key="current_weight", label="Now %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="target_weight", label="Target %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="drift_pct", label="Drift", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="qty_delta", label="ΔQty", kind="number", format="%.6g"),
                ColumnSpec(key="notional", label="Notional", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="suppressed_reason", label="Suppressed", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_turnover", label="Turnover", kind="big_number", unit="ccy"),
                CardSlot(key="buys_count", label="Buys", kind="kpi"),
                CardSlot(key="sells_count", label="Sells", kind="kpi"),
                CardSlot(key="max_drift_pct", label="Max drift", kind="kpi", unit="%"),
                CardSlot(key="estimated_tax_impact", label="Tax Δ", kind="kpi", unit="ccy"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "REBA computes the per-symbol weight drift = current_weight − "
            "target_weight from PORT for the chosen credential. Symbols "
            "with |drift| < drift_tolerance_pct are suppressed (with "
            "suppressed_reason='within_tolerance'). Remaining trades sized "
            "as qty_delta = -drift × total_equity / last_price; sign "
            "determines side (positive drift → sell, negative → buy). "
            "lot_rounding rounds qty to the venue's tradeable increment. "
            "Trades below min_trade_size are dropped with "
            "suppressed_reason='below_min'. tax_aware (when enabled) "
            "selects lots to sell that minimize estimated_tax_impact "
            "(prefers long-term lots and lots near zero gain). The output "
            "is strictly a preview — REBA does not submit. Users hand-off "
            "to EMSX explicitly, where paper_mode=false is required."
        ),
        formula_dict={
            "Drift": Formula(
                expression=r"d_i = w_i^{cur} - w_i^{tgt}",
                variables={},
            ),
            "QtyDelta": Formula(
                expression=r"\Delta q_i = -d_i \cdot E / p_i",
                variables={"E": "Total equity", "p_i": "Last price"},
            ),
            "Turnover": Formula(
                expression=r"T = \sum_i |\Delta q_i| \cdot p_i",
                variables={},
            ),
        },
        field_dict={
            "current_weights": FieldDef(unit="decimal", description="From PORT for the credential.", source="computed_from_broker"),
            "target_weights": FieldDef(unit="decimal", description="User-supplied targets.", source="input"),
            "trades[]": FieldDef(description="Per-symbol trade preview with side, qty_delta, notional.", source="computed"),
            "total_turnover": FieldDef(unit="ccy", description="Σ |notional| across the trade preview.", source="computed"),
            "trades[].suppressed_reason": FieldDef(description="Reason a symbol got no trade: within_tolerance | below_min.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="reba_paper_mode_defaults_true",
                description="REBA is preview-only by default; no live trade can fire from this surface.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="reba_within_tolerance_no_trade",
                description="Symbols whose drift is within tolerance are suppressed.",
                inputs={"drift_tolerance_pct": 1.0},
                assertions=["no trade for symbols with abs(drift) < 1.0"],
            ),
            SemanticTest(
                name="reba_buy_when_underweight",
                description="Symbol below target produces side=buy.",
                inputs={},
                assertions=["current < target implies side == 'buy'"],
            ),
            SemanticTest(
                name="reba_targets_must_sum_to_one",
                description="target_weights that do not sum to ~1.0 warn.",
                inputs={"target_weights": {"A": 0.4, "B": 0.4}},
                assertions=["warnings_non_empty"],
            ),
            SemanticTest(
                name="reba_zero_drift_zero_turnover",
                description="Current == target everywhere → total_turnover == 0.",
                inputs={},
                assertions=["total_turnover == 0.0 when no drift"],
            ),
        ],
    )


__all__ = ["reba"]
