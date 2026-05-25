"""OVME — Option Valuation / Model Engine.

Single-strike option pricer. User supplies underlying, strike, expiry,
risk-free r, dividend yield q, and volatility (plus the pricing
model: BSM / Black76 / Bachelier). OVME returns the theoretical price,
all four primary Greeks, and a payoff diagram at expiry rendered as a
``payoff`` chart grammar.
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
def ovme() -> FunctionManifest:
    return FunctionManifest(
        code="OVME",
        name="Option Valuation / Model Engine",
        category=Category.DERIVATIVES,
        intent=(
            "Single-strike option pricer with full Greeks and a payoff "
            "diagram at expiry. Model assumptions (BSM / Black76 / "
            "Bachelier, r, q, vol) are first-class inputs so the price "
            "never hides its provenance."
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
                description="Underlying ticker; spot price is fetched live.",
            ),
            InputSpec(
                name="option_type",
                label="Type",
                control=ControlKind.SELECT,
                required=True,
                description="Option contract type.",
                options=["call", "put"],
            ),
            InputSpec(
                name="strike",
                label="Strike (K)",
                control=ControlKind.NUMBER,
                required=True,
                description="Strike price in underlying currency.",
                min=0.0,
                step=0.01,
            ),
            InputSpec(
                name="expiry",
                label="Expiry",
                control=ControlKind.DATE_RANGE,
                required=True,
                description="Option expiry date (ISO 8601).",
            ),
            InputSpec(
                name="model",
                label="Model",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Pricing model.",
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
                name="volatility",
                label="Vol (σ)",
                control=ControlKind.NUMBER,
                required=True,
                description="Annualized implied volatility (decimal).",
                min=0.001,
                max=5.0,
                step=0.0001,
                unit="decimal",
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
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "option_type": "call",
            "model": "bsm",
            "risk_free": 0.045,
            "dividend_yield": 0.015,
            "volatility": 0.20,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "underlying",
                "spot",
                "strike",
                "expiry",
                "option_type",
                "model",
                "theoretical_price",
                "greeks",
                "payoff",
                "as_of",
                "data_mode",
            ],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.PAYOFF,
            x_axis=AxisSpec(type="numeric", unit="underlying_ccy", label="Underlying at expiry"),
            y_axis=AxisSpec(type="numeric", unit="P/L", label="P/L"),
            panes=[
                PaneGrammar(name="payoff", series_kind="line", height_pct=100),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.6f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="theoretical_price", label="Theoretical", kind="big_number", unit="underlying_ccy"),
                CardSlot(key="moneyness", label="K/S", kind="kpi"),
                CardSlot(key="time_to_expiry_years", label="T (yr)", kind="kpi"),
                CardSlot(key="delta", label="Δ", kind="kpi"),
                CardSlot(key="gamma", label="Γ", kind="kpi"),
                CardSlot(key="vega", label="Vega", kind="kpi"),
                CardSlot(key="theta", label="Θ", kind="kpi"),
                CardSlot(key="model", label="Model", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "OVME prices a single option contract under the chosen model. "
            "BSM (Black-Scholes-Merton with continuous dividend yield q) "
            "is the default; Black-76 is used for futures (no q term, "
            "drift = r); Bachelier (arithmetic Brownian) is offered for "
            "rates options where prices can be near zero. Spot S is "
            "fetched from yfinance; time to expiry T is computed in years "
            "from the ISO expiry date and now. The handler returns the "
            "theoretical price, all four primary Greeks (Δ, Γ, Θ, vega), "
            "and a sampled payoff curve at expiry over [0.6 S, 1.4 S] for "
            "the chart. Card row exposes model + r + q so the price never "
            "hides its assumptions."
        ),
        formula_dict={
            "bsm_call_price": Formula(
                expression=(
                    r"C = S e^{-qT} N(d_1) - K e^{-rT} N(d_2), "
                    r"\quad d_1 = \frac{\ln(S/K) + (r - q + \sigma^2/2) T}{\sigma \sqrt{T}}, "
                    r"\quad d_2 = d_1 - \sigma \sqrt{T}"
                ),
                variables={
                    "S": "Spot",
                    "K": "Strike",
                    "T": "Years to expiry",
                    "r": "Risk-free rate",
                    "q": "Continuous dividend yield",
                    "sigma": "Volatility",
                },
                notes="Black-Scholes-Merton call with continuous dividends.",
            ),
            "bsm_put_price": Formula(
                expression=r"P = K e^{-rT} N(-d_2) - S e^{-qT} N(-d_1)",
                variables={"d1": "see BSM call", "d2": "d1 - σ √T"},
            ),
            "payoff_at_expiry_call": Formula(
                expression=r"\Pi_T = \max(S_T - K, 0) - premium",
                variables={"S_T": "Underlying at expiry", "premium": "Theoretical price paid today"},
            ),
            "payoff_at_expiry_put": Formula(
                expression=r"\Pi_T = \max(K - S_T, 0) - premium",
                variables={"S_T": "Underlying at expiry"},
            ),
        },
        field_dict={
            "underlying": FieldDef(description="Underlying ticker.", source="input"),
            "spot": FieldDef(unit="underlying_ccy", description="Live spot price.", source="provider"),
            "strike": FieldDef(unit="underlying_ccy", description="Option strike.", source="input"),
            "expiry": FieldDef(unit="iso8601", description="Expiry date.", source="input"),
            "model": FieldDef(description="bsm | black76 | bachelier.", source="input"),
            "theoretical_price": FieldDef(unit="underlying_ccy", description="Model-derived option price.", source="computed"),
            "greeks.delta": FieldDef(description="Δ — dV/dS.", source="computed"),
            "greeks.gamma": FieldDef(description="Γ — d²V/dS².", source="computed"),
            "greeks.vega": FieldDef(description="dV/dσ.", source="computed"),
            "greeks.theta": FieldDef(description="dV/dt (per year).", source="computed"),
            "payoff": FieldDef(description="Array of {underlying_at_expiry, pnl} sampled across [0.6S, 1.4S].", source="computed"),
            "moneyness": FieldDef(description="K / S.", source="computed"),
            "time_to_expiry_years": FieldDef(unit="years", description="T in years.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ovme_chart_is_payoff",
                description="OVME must render as a payoff diagram, not a row-index line.",
                inputs={},
                assertions=["chart_grammar_kind_is_payoff"],
            ),
            SemanticTest(
                name="ovme_bsm_call_atm_returns_positive_price_and_greeks",
                description=(
                    "An ATM BSM call with T=1, σ=0.2, r=0.045, q=0 returns a "
                    "positive theoretical price and a positive vega/gamma."
                ),
                inputs={
                    "underlying": "SPY",
                    "strike": 100.0,
                    "expiry": "+1Y",
                    "option_type": "call",
                    "model": "bsm",
                    "risk_free": 0.045,
                    "dividend_yield": 0.0,
                    "volatility": 0.20,
                },
                assertions=[
                    "theoretical_price_positive",
                    "delta_in_open_interval_0_1",
                    "gamma_non_negative",
                    "vega_non_negative",
                ],
            ),
            SemanticTest(
                name="ovme_assumptions_visible_on_card",
                description="Card row exposes model, r, and q so price provenance is auditable.",
                inputs={"model": "bsm", "risk_free": 0.045, "dividend_yield": 0.015},
                assertions=[
                    "model_card_present",
                    "risk_free_echoed_in_payload",
                    "dividend_yield_echoed_in_payload",
                ],
            ),
        ],
    )


__all__ = ["ovme"]
