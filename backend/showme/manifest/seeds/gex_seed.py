"""GEX — Gamma Exposure (strike ladder + walls + flip).

Encodes ``docs/rebuild/manifests/wave1/GEX.md`` verbatim. The user-visible
exemplar is the diverging bar ladder against actual strike prices (NOT a
row-index plot), so ``chart_grammar.kind = BAR_LADDER`` is load-bearing.
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
    AlertingSpec,
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def gex() -> FunctionManifest:
    return FunctionManifest(
        code="GEX",
        name="Gamma Exposure",
        category=Category.DERIVATIVES,
        intent=(
            "Show dealer/MM gamma exposure by strike for a chosen underlying so "
            "a trader can identify gamma walls, the gamma flip point, and "
            "exposure regimes that affect realized volatility behavior — with "
            "explicit model assumptions visible."
        ),
        asset_classes=[
            AssetClass.OPTION,
            AssetClass.EQUITY,
            AssetClass.INDEX,
            AssetClass.ETF,
        ],
        inputs=[
            InputSpec(
                name="underlying",
                label="Underlying",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity/ETF/index ticker (options-eligible).",
            ),
            InputSpec(
                name="expiry_filter",
                label="Expirations",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which expiries to include in the GEX aggregation.",
                options=[
                    "next_1",
                    "next_3",
                    "next_6",
                    "weekly_only",
                    "monthly_only",
                    "all",
                ],
            ),
            InputSpec(
                name="oi_source",
                label="OI Source",
                control=ControlKind.SELECT,
                required=True,
                description="Where Open Interest comes from.",
                options=["exchange", "modeled"],
            ),
            InputSpec(
                name="risk_free",
                label="Risk-free",
                control=ControlKind.NUMBER,
                required=True,
                description="r used in BSM gamma calc.",
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
                description="q used in BSM gamma calc.",
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
                description="Implied vol source for the gamma calc.",
                options=["market", "modeled_vol_surface", "fixed_30d_atm"],
            ),
            InputSpec(
                name="dealer_assumption",
                label="Dealer Side",
                control=ControlKind.SELECT,
                required=True,
                description="Convention for who's net short gamma.",
                options=[
                    "short_calls_long_puts",
                    "sticky_strike",
                    "sticky_delta",
                    "neutral",
                ],
            ),
            InputSpec(
                name="as_of",
                label="As of",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Snapshot time; default is last_close.",
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
            "oi_source": "exchange",
            "risk_free": 0.045,
            "dividend_yield": 0.015,
            "iv_source": "market",
            "dealer_assumption": "short_calls_long_puts",
            "as_of": "last_close",
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
            must_have=[
                "underlying",
                "spot",
                "as_of",
                "strikes",
                "data_mode",
                "iv_source",
                "dealer_assumption",
            ],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="GEX $/1%", label="Gamma exposure"),
            y_axis=AxisSpec(type="numeric", unit="$", label="Strike"),
            panes=[
                PaneGrammar(name="gex_bars", series_kind="bar", height_pct=75),
                PaneGrammar(name="cumulative", series_kind="line", height_pct=25),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="spot", label="Spot", kind="big_number", unit="$"),
                CardSlot(key="net_gex", label="Net GEX", kind="trend_pill", unit="$/1%"),
                CardSlot(key="gamma_flip", label="Gamma Flip", kind="big_number", unit="$"),
                CardSlot(key="largest_call_wall", label="Call Wall", kind="kpi", unit="$"),
                CardSlot(key="largest_put_wall", label="Put Wall", kind="kpi", unit="$"),
                CardSlot(key="iv_source", label="IV Source", kind="badge"),
                CardSlot(key="dealer_assumption", label="Dealer", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GEX is computed strike-by-strike from the option chain. For each "
            "strike K and option O with open interest OI(O), implied vol σ(O), "
            "and days-to-expiry T(O): (1) compute Black-Scholes-Merton gamma "
            "γ(S, K, T, σ, r, q); (2) per-contract dollar gamma = γ * S² * "
            "contract_multiplier * 0.01 ($/1% convention); (3) dealer-signed "
            "gamma — under short_calls_long_puts, dealers are short calls "
            "(positive contribution → suppresses realized vol when net γ > 0) "
            "and long puts (negative contribution); (4) aggregate by strike "
            "across selected expiries; (5) gamma flip = strike where cumulative "
            "signed γ crosses zero; (6) walls = strikes with largest absolute "
            "call γ / put γ. Model assumptions are visible — fixed_30d_atm "
            "loses skew (flagged as warning), modeled_vol_surface requires "
            "IVOL infra, market uses chain bid/ask mid IV per contract."
        ),
        formula_dict={
            "bsm_gamma": Formula(
                expression=(
                    r"\gamma = \frac{\phi(d_1)}{S \sigma \sqrt{T}}, "
                    r"\quad d_1 = \frac{\ln(S/K) + (r - q + \sigma^2/2) T}{\sigma \sqrt{T}}"
                ),
                variables={
                    "S": "Spot price of the underlying",
                    "K": "Option strike",
                    "T": "Years to expiry",
                    "sigma": "Implied volatility (annualized, decimal)",
                    "r": "Risk-free rate",
                    "q": "Continuous dividend yield",
                    "phi": "Standard-normal probability density",
                },
                notes="Closed-form BSM gamma for European options on a dividend-paying underlying.",
            ),
            "dollar_gamma": Formula(
                expression=r"\Gamma_\$ = \gamma \cdot S^2 \cdot 100 \cdot 0.01",
                variables={
                    "Gamma_$": "Per-contract dollar gamma in $/1% spot move",
                    "100": "Standard equity-option contract multiplier",
                },
                notes="Per-contract dollar gamma in the $/1% convention.",
            ),
            "dealer_signed": Formula(
                expression=r"\text{signed}_\gamma = +\Gamma_\$(\text{call}) - \Gamma_\$(\text{put})",
                variables={},
                notes="Under standard short_calls_long_puts dealer convention.",
            ),
            "gamma_flip": Formula(
                expression=(
                    r"K^{*} = \min\{K : \sum_{K' \le K} \text{signed}_\gamma(K') \ge 0 "
                    r"\text{ and prior cumulative} < 0\}"
                ),
                variables={"K*": "First strike where cumulative signed gamma crosses zero"},
            ),
        },
        field_dict={
            "spot": FieldDef(unit="$", description="Current underlying price.", source="quote provider"),
            "strikes[].strike": FieldDef(unit="$", description="Strike price.", source="option chain"),
            "strikes[].call_gex": FieldDef(unit="$/1%", description="Aggregated call dealer γ at strike.", source="computed"),
            "strikes[].put_gex": FieldDef(unit="$/1%", description="Aggregated put dealer γ at strike.", source="computed"),
            "strikes[].signed_gex": FieldDef(unit="$/1%", description="call_gex − put_gex.", source="computed"),
            "strikes[].oi_call": FieldDef(unit="contracts", description="Call OI summed across selected expiries.", source="option chain"),
            "strikes[].oi_put": FieldDef(unit="contracts", description="Put OI summed across selected expiries.", source="option chain"),
            "cumulative_gex_curve[].strike": FieldDef(unit="$", description="Strike.", source="derived"),
            "cumulative_gex_curve[].cum_gex": FieldDef(unit="$/1%", description="Running Σ signed_gex from lowest strike.", source="derived"),
            "net_gex": FieldDef(unit="$/1%", description="Σ signed_gex across all strikes.", source="derived"),
            "gamma_flip": FieldDef(unit="$", description="First strike where cumulative crosses zero.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["spot_crosses_gamma_flip", "net_gex_sign_change", "wall_breached"],
            delivery=["tray", "notification"],
        ),
        semantic_tests=[
            SemanticTest(
                name="gex_spy_strike_ladder_real_axis",
                description=(
                    "Chart x-axis is strike-based (not row-index), every bar has a numeric strike, "
                    "strikes are sorted ascending."
                ),
                inputs={"underlying": "SPY", "expiry_filter": ["next_3"]},
                assertions=[
                    "chart_x_axis_is_strike",
                    "every_bar_has_numeric_strike",
                    "strikes_sorted_ascending",
                ],
            ),
            SemanticTest(
                name="gex_gamma_flip_consistent_with_cumulative",
                description=(
                    "Reported gamma_flip strike equals the first cumulative_gex_curve point "
                    "where cum_gex crosses zero."
                ),
                inputs={"underlying": "SPY"},
                assertions=["gamma_flip_matches_cumulative_zero_cross"],
            ),
            SemanticTest(
                name="gex_bsm_gamma_matches_reference",
                description=(
                    "For S=100, K=100, T=30/365, σ=0.2, r=0.04, q=0, computed γ matches the "
                    "BSM closed-form value to within 1e-6."
                ),
                inputs={
                    "S": 100, "K": 100, "T": 30 / 365,
                    "sigma": 0.2, "r": 0.04, "q": 0,
                },
                assertions=["bsm_gamma_within_1e-6_of_reference"],
            ),
            SemanticTest(
                name="gex_no_provider_returns_unavailable_not_silent_zero",
                description=(
                    "With no provider configured, data_mode is not_configured or "
                    "provider_unavailable, strikes==[], warning explains the missing config — "
                    "NOT a zero-strike chart pretending to be live."
                ),
                inputs={"underlying": "SPY", "provider_mode": "live_official"},
                assertions=[
                    "data_mode_is_not_configured_or_provider_unavailable",
                    "strikes_is_empty",
                    "warning_explains_missing_config",
                ],
            ),
            SemanticTest(
                name="gex_dealer_assumption_changes_sign",
                description=(
                    "Same inputs with dealer_assumption short_calls_long_puts vs neutral "
                    "should yield different signed_gex; net_gex differs."
                ),
                inputs={"underlying": "SPY"},
                assertions=["net_gex_differs_across_dealer_assumptions"],
            ),
            SemanticTest(
                name="gex_fixed_30d_atm_warns_about_skew_loss",
                description=(
                    "When iv_source=fixed_30d_atm, a warning is present mentioning "
                    "'skew not modeled'."
                ),
                inputs={"underlying": "SPY", "iv_source": "fixed_30d_atm"},
                assertions=["warning_mentions_skew_not_modeled"],
            ),
        ],
    )


__all__ = ["gex"]
