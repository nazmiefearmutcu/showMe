"""OMON — Option Monitor (strikes × expiries with Greeks).

Full option chain table for a chosen underlying. Rows enumerate every
strike × expiry × type with bid/ask/mid, IV, and the BSM Greeks (delta,
gamma, theta, vega). Pricing-model inputs (risk-free rate, dividend
yield, IV source) are exposed as first-class controls so the Greeks
never hide their assumptions.
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
def omon() -> FunctionManifest:
    return FunctionManifest(
        code="OMON",
        name="Option Monitor",
        category=Category.DERIVATIVES,
        intent=(
            "Show the full option chain (every strike × expiry × type) with "
            "live bid/ask/mid, implied vol, and the four primary Greeks for a "
            "chosen underlying, with the pricing model's r, q, and IV source "
            "visible."
        ),
        asset_classes=[
            AssetClass.OPTION,
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="underlying",
                label="Underlying",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Options-eligible equity/ETF/index ticker.",
            ),
            InputSpec(
                name="expiry_filter",
                label="Expirations",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which expiries to include in the monitor.",
                options=["next_1", "next_3", "next_6", "weekly_only", "monthly_only", "all"],
            ),
            InputSpec(
                name="strike_window",
                label="Strike Window",
                control=ControlKind.SELECT,
                required=True,
                description="Moneyness band around spot to include.",
                options=["atm_5", "atm_10", "atm_20", "wide", "all"],
            ),
            InputSpec(
                name="risk_free",
                label="Risk-free r",
                control=ControlKind.NUMBER,
                required=True,
                description="r used in BSM pricing and Greek calcs.",
                min=0.0,
                max=0.10,
                step=0.001,
                unit="rate",
            ),
            InputSpec(
                name="dividend_yield",
                label="Div Yield q",
                control=ControlKind.NUMBER,
                required=True,
                description="q used in BSM pricing and Greek calcs.",
                min=0.0,
                max=0.10,
                step=0.001,
                unit="rate",
            ),
            InputSpec(
                name="iv_source",
                label="IV Source",
                control=ControlKind.SELECT,
                required=True,
                description="Source for implied volatility per row.",
                options=["market_mid", "market_bid_ask", "solved_from_mid"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "underlying": "SPY",
            "expiry_filter": ["next_3"],
            "strike_window": "atm_10",
            "risk_free": 0.045,
            "dividend_yield": 0.015,
            "iv_source": "market_mid",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cboe_options", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=30,
            scope="per_input",
            persist=False,
        ),
        output_contract=OutputContract(
            must_have=[
                "underlying",
                "spot",
                "as_of",
                "rows",
                "iv_source",
                "risk_free",
                "dividend_yield",
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
                ColumnSpec(key="expiry", label="Expiry", kind="text"),
                ColumnSpec(key="strike", label="Strike", kind="number", format="%.2f"),
                ColumnSpec(key="option_type", label="Type", kind="tag"),
                ColumnSpec(key="bid", label="Bid", kind="number", format="%.4f"),
                ColumnSpec(key="ask", label="Ask", kind="number", format="%.4f"),
                ColumnSpec(key="mid", label="Mid", kind="number", format="%.4f"),
                ColumnSpec(key="iv", label="IV", kind="percent", format="%.2f"),
                ColumnSpec(key="delta", label="Δ", kind="number", format="%.4f"),
                ColumnSpec(key="gamma", label="Γ", kind="number", format="%.6f"),
                ColumnSpec(key="theta", label="Θ", kind="number", format="%.4f"),
                ColumnSpec(key="vega", label="Vega", kind="number", format="%.4f"),
                ColumnSpec(key="open_interest", label="OI", kind="number", format="%.0f"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number", unit="$"),
                CardSlot(key="atm_iv_30d", label="ATM IV 30D", kind="kpi", unit="%"),
                CardSlot(key="iv_source", label="IV Source", kind="badge"),
                CardSlot(key="risk_free", label="r", kind="badge", unit="rate"),
                CardSlot(key="dividend_yield", label="q", kind="badge", unit="rate"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Fetch the live option chain for the selected expiries and strike "
            "window, then enrich every row with the four primary BSM Greeks "
            "computed from the per-row implied volatility, the user-supplied "
            "risk-free rate r, and the dividend yield q. mid is (bid+ask)/2 "
            "when both legs exist, else last. IV source is honored: market_mid "
            "uses the chain's quoted IV at the mid; market_bid_ask preserves "
            "separate bid-IV / ask-IV; solved_from_mid inverts the BSM price "
            "to back IV out of the mid premium. Greeks (Δ, Γ, Θ, vega) come "
            "from the BSM closed forms. The card schema exposes r, q, and IV "
            "source so the Greeks never hide their model assumptions."
        ),
        formula_dict={
            "bsm_delta_call": Formula(
                expression=r"\Delta_{call} = e^{-qT} N(d_1)",
                variables={"d1": "(ln(S/K) + (r - q + σ²/2) T) / (σ √T)"},
                notes="BSM call delta with continuous dividends.",
            ),
            "bsm_gamma": Formula(
                expression=r"\Gamma = \frac{e^{-qT} \phi(d_1)}{S \sigma \sqrt{T}}",
                variables={"phi": "Standard-normal PDF"},
            ),
            "bsm_theta_call": Formula(
                expression=(
                    r"\Theta_{call} = -\frac{S e^{-qT} \phi(d_1) \sigma}{2 \sqrt{T}} "
                    r"- r K e^{-rT} N(d_2) + q S e^{-qT} N(d_1)"
                ),
                variables={"d2": "d1 - σ √T"},
                notes="Per-year theta; UI typically divides by 365 to show per-day decay.",
            ),
            "bsm_vega": Formula(
                expression=r"\text{Vega} = S e^{-qT} \phi(d_1) \sqrt{T}",
                variables={},
                notes="Per 1.00 vol change; UI may divide by 100 to show per 1 vol point.",
            ),
        },
        field_dict={
            "spot": FieldDef(unit="$", description="Current underlying price.", source="quote provider"),
            "rows[].expiry": FieldDef(unit="iso8601", description="Option expiry.", source="option chain"),
            "rows[].strike": FieldDef(unit="$", description="Strike.", source="option chain"),
            "rows[].option_type": FieldDef(description="CALL or PUT.", source="option chain"),
            "rows[].bid": FieldDef(unit="$", description="Best bid premium.", source="option chain"),
            "rows[].ask": FieldDef(unit="$", description="Best ask premium.", source="option chain"),
            "rows[].mid": FieldDef(unit="$", description="(bid+ask)/2 fallback to last.", source="derived"),
            "rows[].iv": FieldDef(unit="decimal", description="Implied volatility honoring iv_source.", source="computed"),
            "rows[].delta": FieldDef(description="BSM delta.", source="computed"),
            "rows[].gamma": FieldDef(description="BSM gamma.", source="computed"),
            "rows[].theta": FieldDef(description="BSM theta per year.", source="computed"),
            "rows[].vega": FieldDef(description="BSM vega per 1.00 vol.", source="computed"),
            "rows[].open_interest": FieldDef(unit="contracts", description="Listed OI.", source="option chain"),
            "rows[].volume": FieldDef(unit="contracts", description="Session volume.", source="option chain"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="omon_rows_have_greeks",
                description="Every option-chain row carries finite bid/ask/iv/delta/gamma/theta/vega.",
                inputs={"underlying": "SPY", "expiry_filter": ["next_3"]},
                assertions=[
                    "every_row_has_bid_ask",
                    "every_row_has_finite_iv",
                    "every_row_has_finite_greeks",
                ],
            ),
            SemanticTest(
                name="omon_pricing_assumptions_visible",
                description=(
                    "Card schema exposes iv_source, risk_free, and dividend_yield; the "
                    "payload echoes the same values so Greeks never hide their assumptions."
                ),
                inputs={
                    "underlying": "SPY",
                    "risk_free": 0.045,
                    "dividend_yield": 0.015,
                    "iv_source": "solved_from_mid",
                },
                assertions=[
                    "iv_source_card_present",
                    "risk_free_echoed_in_payload",
                    "dividend_yield_echoed_in_payload",
                ],
            ),
            SemanticTest(
                name="omon_no_provider_returns_unavailable_not_empty_chain",
                description=(
                    "Without a configured options provider, OMON returns provider_unavailable "
                    "with a next_action — not an empty table pretending to be a live chain."
                ),
                inputs={"underlying": "SPY", "provider_mode": "live_official"},
                assertions=[
                    "status_is_provider_unavailable_or_not_configured",
                    "rows_is_empty",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["omon"]
