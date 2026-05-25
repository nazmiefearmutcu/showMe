"""OSA — Option Strategy Analyzer (multi-leg).

Takes a list of option legs (call/put × long/short × strike × expiry
× quantity) plus the model assumption block (r, q, vol per leg) and
returns: aggregate price, aggregate Greeks, and the multi-leg payoff
diagram at expiry. Same payoff chart grammar as OVME so the renderer
is shared.
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
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def osa() -> FunctionManifest:
    return FunctionManifest(
        code="OSA",
        name="Option Strategy Analyzer",
        category=Category.DERIVATIVES,
        intent=(
            "Multi-leg option strategy analyzer. Accepts a list of legs "
            "(call/put × long/short × strike × expiry × qty) and the "
            "pricing model assumptions; returns aggregate Greeks, net "
            "premium, breakevens, and the combined payoff diagram."
        ),
        asset_classes=[
            AssetClass.OPTION,
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.INDEX,
            AssetClass.FX,
            AssetClass.COMMODITY,
        ],
        inputs=[
            InputSpec(
                name="underlying",
                label="Underlying",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Underlying ticker shared by all legs.",
            ),
            InputSpec(
                name="legs",
                label="Legs",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Ordered list of legs. Each leg: "
                    "{option_type: call|put, side: long|short, strike, "
                    "expiry, quantity, volatility}."
                ),
            ),
            InputSpec(
                name="model",
                label="Model",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Pricing model applied to every leg.",
                options=["bsm", "black76", "bachelier"],
            ),
            InputSpec(
                name="risk_free",
                label="Risk-free r",
                control=ControlKind.NUMBER,
                required=True,
                description="Annualized continuous risk-free rate.",
                min=-0.05,
                max=0.20,
                step=0.0001,
                unit="rate",
            ),
            InputSpec(
                name="dividend_yield",
                label="Div Yield q",
                control=ControlKind.NUMBER,
                required=True,
                description="Annualized continuous dividend yield.",
                min=0.0,
                max=0.20,
                step=0.0001,
                unit="rate",
            ),
            InputSpec(
                name="payoff_underlying_range",
                label="Payoff range (×spot)",
                control=ControlKind.SELECT,
                required=False,
                description="Underlying span sampled for the payoff curve.",
                options=["0.6_1.4", "0.5_1.5", "0.3_1.7", "0.1_1.9"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for the spot quote.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                ],
            ),
        ],
        defaults={
            "model": "bsm",
            "risk_free": 0.045,
            "dividend_yield": 0.015,
            "payoff_underlying_range": "0.6_1.4",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "underlying",
                "spot",
                "legs",
                "model",
                "net_premium",
                "aggregate_greeks",
                "payoff",
                "breakevens",
                "as_of",
                "data_mode",
            ],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.PAYOFF,
            x_axis=AxisSpec(type="numeric", unit="underlying_ccy", label="Underlying at expiry"),
            y_axis=AxisSpec(type="numeric", unit="P/L", label="Combined P/L"),
            panes=[
                PaneGrammar(name="payoff", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="leg_idx", label="#", kind="number", format="%d"),
                ColumnSpec(key="option_type", label="Type", kind="tag"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="strike", label="Strike", kind="number", format="%.4f"),
                ColumnSpec(key="expiry", label="Expiry", kind="date"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%d"),
                ColumnSpec(key="volatility", label="σ", kind="percent", format="%.2f"),
                ColumnSpec(key="leg_premium", label="Premium", kind="number", format="%.4f"),
                ColumnSpec(key="delta", label="Δ", kind="number", format="%.4f"),
                ColumnSpec(key="gamma", label="Γ", kind="number", format="%.6f"),
                ColumnSpec(key="theta", label="Θ", kind="number", format="%.4f"),
                ColumnSpec(key="vega", label="Vega", kind="number", format="%.4f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="net_premium", label="Net premium", kind="big_number", unit="underlying_ccy"),
                CardSlot(key="aggregate_delta", label="Σ Δ", kind="kpi"),
                CardSlot(key="aggregate_gamma", label="Σ Γ", kind="kpi"),
                CardSlot(key="aggregate_vega", label="Σ Vega", kind="kpi"),
                CardSlot(key="aggregate_theta", label="Σ Θ", kind="kpi"),
                CardSlot(key="max_profit", label="Max profit", kind="kpi", unit="underlying_ccy"),
                CardSlot(key="max_loss", label="Max loss", kind="kpi", unit="underlying_ccy"),
                CardSlot(key="model", label="Model", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "OSA prices each leg under the chosen model (BSM / Black76 / "
            "Bachelier), then sums the leg-level premiums and Greeks "
            "weighted by side (+1 for long, -1 for short) × quantity. "
            "The payoff at expiry is built by sampling underlying values "
            "across the chosen multiplier band of spot, computing the "
            "intrinsic value of each leg at every sampled point, summing, "
            "and subtracting net_premium. Breakevens are the underlying "
            "values where the aggregate payoff crosses zero (computed by "
            "linear interpolation between adjacent samples). Max profit "
            "and max loss read off the payoff series. Model + r + q are "
            "echoed on the card so the strategy never hides its assumptions."
        ),
        formula_dict={
            "leg_signed_quantity": Formula(
                expression=r"q_i^{signed} = \begin{cases} +q_i & long \\ -q_i & short \end{cases}",
                variables={"q_i": "Leg quantity"},
            ),
            "net_premium": Formula(
                expression=r"\Pi_0 = \sum_i q_i^{signed} \cdot price_i",
                variables={"price_i": "Per-leg model price"},
                notes="Positive = net debit paid, negative = net credit received.",
            ),
            "aggregate_delta": Formula(
                expression=r"\Delta_{port} = \sum_i q_i^{signed} \cdot \Delta_i",
                variables={"Δ_i": "Per-leg BSM delta"},
            ),
            "payoff_at_expiry": Formula(
                expression=(
                    r"\Pi_T(S_T) = \sum_i q_i^{signed} \cdot intrinsic_i(S_T) - \Pi_0"
                ),
                variables={"intrinsic_i": "max(S_T - K_i, 0) for call; max(K_i - S_T, 0) for put"},
            ),
        },
        field_dict={
            "underlying": FieldDef(description="Underlying ticker.", source="input"),
            "spot": FieldDef(unit="underlying_ccy", description="Live spot price.", source="provider"),
            "model": FieldDef(description="bsm | black76 | bachelier.", source="input"),
            "legs": FieldDef(description="Echoed leg list with computed per-leg premiums + Greeks.", source="computed"),
            "net_premium": FieldDef(unit="underlying_ccy", description="Σ signed leg premiums.", source="computed"),
            "aggregate_greeks.delta": FieldDef(description="Σ signed Δ.", source="computed"),
            "aggregate_greeks.gamma": FieldDef(description="Σ signed Γ.", source="computed"),
            "aggregate_greeks.vega": FieldDef(description="Σ signed Vega.", source="computed"),
            "aggregate_greeks.theta": FieldDef(description="Σ signed Θ.", source="computed"),
            "payoff": FieldDef(description="Array of {underlying_at_expiry, pnl} sampled across band.", source="computed"),
            "breakevens": FieldDef(description="Underlying values where aggregate payoff = 0.", source="computed"),
            "max_profit": FieldDef(unit="underlying_ccy", description="Maximum payoff over sampled band.", source="computed"),
            "max_loss": FieldDef(unit="underlying_ccy", description="Minimum payoff over sampled band.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="osa_chart_is_payoff",
                description="OSA must render as a payoff diagram.",
                inputs={},
                assertions=["chart_grammar_kind_is_payoff"],
            ),
            SemanticTest(
                name="osa_long_call_short_call_is_vertical_spread",
                description=(
                    "A long-call/short-call vertical spread on the same "
                    "expiry has bounded max_profit and bounded max_loss."
                ),
                inputs={
                    "underlying": "SPY",
                    "legs": [
                        {"option_type": "call", "side": "long", "strike": 100, "expiry": "+1Y", "quantity": 1, "volatility": 0.20},
                        {"option_type": "call", "side": "short", "strike": 110, "expiry": "+1Y", "quantity": 1, "volatility": 0.20},
                    ],
                    "model": "bsm",
                },
                assertions=[
                    "max_profit_finite",
                    "max_loss_finite",
                    "breakevens_length_in_zero_or_one",
                ],
            ),
            SemanticTest(
                name="osa_long_straddle_has_two_breakevens",
                description="A long straddle (long call + long put same K) has two breakevens.",
                inputs={
                    "underlying": "SPY",
                    "legs": [
                        {"option_type": "call", "side": "long", "strike": 100, "expiry": "+1Y", "quantity": 1, "volatility": 0.20},
                        {"option_type": "put", "side": "long", "strike": 100, "expiry": "+1Y", "quantity": 1, "volatility": 0.20},
                    ],
                    "model": "bsm",
                },
                assertions=[
                    "breakevens_length_at_least_two",
                    "max_loss_equals_negative_net_premium",
                ],
            ),
        ],
    )


__all__ = ["osa"]
