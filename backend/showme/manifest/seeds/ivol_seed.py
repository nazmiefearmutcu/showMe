"""IVOL — Implied Vol Surface heatmap.

Visualises the option chain's implied-vol surface across expiries × strikes
for a chosen underlying. Vol surface is a 2D grid → ``ChartKind.SURFACE``
(falls back to ``HEATMAP`` if the renderer can't paint 3D). Model
assumptions (risk-free, dividend yield, IV source) are first-class inputs
so the surface never hides what produced it.
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
def ivol() -> FunctionManifest:
    return FunctionManifest(
        code="IVOL",
        name="Implied Vol Surface",
        category=Category.DERIVATIVES,
        intent=(
            "Render the implied-volatility surface (expiry × strike) for an "
            "underlying so traders can read the term-structure, skew, and "
            "smile with explicit model assumptions visible."
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
                description="Which expiries to include in the surface.",
                options=["next_1", "next_3", "next_6", "weekly_only", "monthly_only", "all"],
            ),
            InputSpec(
                name="smile_skew_mode",
                label="Smile/Skew",
                control=ControlKind.SELECT,
                required=True,
                description="Render the per-expiry smile cross-section or the full skew surface.",
                options=["smile", "skew", "both"],
            ),
            InputSpec(
                name="iv_source",
                label="IV Source",
                control=ControlKind.SELECT,
                required=True,
                description="Where implied volatility values come from.",
                options=["market_mid", "market_bid_ask", "modeled_vol_surface"],
            ),
            InputSpec(
                name="risk_free",
                label="Risk-free",
                control=ControlKind.NUMBER,
                required=True,
                description="r used when solving / re-pricing IV.",
                min=0.0,
                max=0.10,
                step=0.001,
                unit="rate",
            ),
            InputSpec(
                name="dividend_yield",
                label="Div Yield",
                control=ControlKind.NUMBER,
                required=True,
                description="q used when solving / re-pricing IV.",
                min=0.0,
                max=0.10,
                step=0.001,
                unit="rate",
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
            "smile_skew_mode": "both",
            "iv_source": "market_mid",
            "risk_free": 0.045,
            "dividend_yield": 0.015,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="cboe_options",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=60,
            scope="per_input",
            persist=False,
        ),
        output_contract=OutputContract(
            must_have=["underlying", "spot", "as_of", "surface", "iv_source", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.SURFACE,
            x_axis=AxisSpec(type="numeric", unit="$", label="Strike"),
            y_axis=AxisSpec(type="category", unit="expiry", label="Expiry"),
            panes=[
                PaneGrammar(name="surface", series_kind="area", height_pct=70),
                PaneGrammar(name="atm_term", series_kind="line", height_pct=30),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="expiry", label="Expiry", kind="text"),
                ColumnSpec(key="strike", label="Strike", kind="number", format="%.2f"),
                ColumnSpec(key="option_type", label="Type", kind="tag"),
                ColumnSpec(key="iv", label="IV", kind="percent", format="%.2f"),
                ColumnSpec(key="moneyness", label="K/S", kind="number", format="%.4f"),
                ColumnSpec(key="bid", label="Bid", kind="number", format="%.4f"),
                ColumnSpec(key="ask", label="Ask", kind="number", format="%.4f"),
                ColumnSpec(key="open_interest", label="OI", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number", unit="$"),
                CardSlot(key="atm_iv_30d", label="ATM IV 30D", kind="kpi", unit="%"),
                CardSlot(key="skew_25d", label="Skew 25Δ", kind="kpi", unit="vol pts"),
                CardSlot(key="term_slope", label="Term slope", kind="trend_pill"),
                CardSlot(key="iv_source", label="IV Source", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Fetch the option chain for the selected expiries, collect per-row "
            "implied volatility from the chosen source (market_mid uses the "
            "(bid+ask)/2 IV; market_bid_ask keeps both legs separate; "
            "modeled_vol_surface re-solves IV from mid premium via BSM with "
            "the supplied r and q). Compute moneyness K/S using the live spot. "
            "Render as a (strike, expiry) surface with a small ATM-IV term-"
            "structure pane underneath. Model assumptions stay visible — the "
            "card row exposes IV source, r, and q so the user can never "
            "mistake a re-priced surface for a quoted one. If the provider "
            "yields no usable IV rows, return status=provider_unavailable "
            "with an actionable next_action instead of an empty heatmap."
        ),
        formula_dict={
            "bsm_call": Formula(
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
                    "sigma": "Implied volatility",
                    "N": "Standard-normal CDF",
                },
                notes="Black-Scholes-Merton call price with continuous dividends; IV is solved to match the market mid.",
            ),
            "moneyness": Formula(
                expression=r"m = K / S",
                variables={"K": "Strike", "S": "Spot"},
                notes="Plain strike/spot moneyness used for the surface x-axis.",
            ),
            "skew_25d": Formula(
                expression=r"\text{skew}_{25\Delta} = \sigma_{25P} - \sigma_{25C}",
                variables={
                    "sigma_25P": "IV at the 25-delta put",
                    "sigma_25C": "IV at the 25-delta call",
                },
                notes="Standard 25-delta risk-reversal skew in vol points.",
            ),
        },
        field_dict={
            "spot": FieldDef(unit="$", description="Current underlying price.", source="quote provider"),
            "surface[].expiry": FieldDef(unit="iso8601", description="Option expiry.", source="option chain"),
            "surface[].strike": FieldDef(unit="$", description="Option strike.", source="option chain"),
            "surface[].iv": FieldDef(unit="decimal", description="Implied volatility as a decimal.", source="computed"),
            "surface[].moneyness": FieldDef(unit="ratio", description="Strike / spot.", source="computed"),
            "surface[].option_type": FieldDef(description="CALL or PUT.", source="option chain"),
            "atm_iv_30d": FieldDef(unit="decimal", description="ATM IV at the ~30-day expiry.", source="derived"),
            "skew_25d": FieldDef(unit="vol pts", description="25-delta put IV minus 25-delta call IV.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ivol_surface_axes_are_strike_and_expiry",
                description=(
                    "IVOL renders a strike×expiry surface, not a row-index plot; every cell "
                    "carries a finite IV."
                ),
                inputs={"underlying": "SPY", "expiry_filter": ["next_3"]},
                assertions=[
                    "x_axis_is_strike",
                    "y_axis_is_expiry",
                    "every_cell_has_finite_iv",
                ],
            ),
            SemanticTest(
                name="ivol_source_visible_on_card",
                description=(
                    "Model assumptions are visible — iv_source, risk_free, and dividend_yield "
                    "are exposed on the card schema and echoed in the payload."
                ),
                inputs={"underlying": "SPY", "iv_source": "modeled_vol_surface"},
                assertions=[
                    "iv_source_card_present",
                    "risk_free_echoed_in_payload",
                    "dividend_yield_echoed_in_payload",
                ],
            ),
            SemanticTest(
                name="ivol_no_provider_returns_unavailable_not_empty_surface",
                description=(
                    "Without a configured options provider, IVOL returns provider_unavailable "
                    "with a next_action — not a zero-IV surface pretending to be live."
                ),
                inputs={"underlying": "SPY", "provider_mode": "live_official"},
                assertions=[
                    "status_is_provider_unavailable_or_not_configured",
                    "surface_is_empty",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["ivol"]
