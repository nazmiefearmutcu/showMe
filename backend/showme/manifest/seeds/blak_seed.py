"""BLAK — Black-Litterman model with explicit priors, views, and tau.

The Black-Litterman model lives or dies by transparency of its prior. The
manifest forces the prior_returns, prior_covariance, views, view_confidence,
and tau inputs to be ``model_assumption`` controls so the UI must surface
them — they are NOT silent defaults.
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
def blak() -> FunctionManifest:
    return FunctionManifest(
        code="BLAK",
        name="Black-Litterman",
        category=Category.PORTFOLIO,
        intent=(
            "Combine an implied-equilibrium prior with the user's subjective "
            "views (absolute or relative) under the Black-Litterman framework, "
            "producing posterior expected returns and posterior covariance "
            "that can be fed into PORT_OPT. Priors, views, and tau are all "
            "exposed as model_assumption controls — no silent defaults."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.INDEX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Instruments to include in the prior + posterior.",
            ),
            InputSpec(
                name="market_caps",
                label="Market caps",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Cap-weighted market portfolio used to back out the "
                    "implied-equilibrium prior. Required — the model is "
                    "ill-defined without it."
                ),
            ),
            InputSpec(
                name="risk_aversion",
                label="Risk aversion (δ)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Aggregate risk-aversion coefficient for the implied prior.",
                min=0.5,
                max=10.0,
                step=0.1,
            ),
            InputSpec(
                name="prior_covariance",
                label="Prior covariance (Σ)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Covariance estimator for the prior.",
                options=["sample_cov", "ledoit_wolf", "exp_cov"],
            ),
            InputSpec(
                name="views",
                label="Views (P, Q)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Picking matrix P + view returns vector Q. Each view is "
                    "absolute (single asset) or relative (long-short basket)."
                ),
            ),
            InputSpec(
                name="view_confidence",
                label="View confidence (Ω)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Per-view confidence — either explicit Ω diagonal or via "
                    "the Idzorek-style confidence-in-views fraction (0-1)."
                ),
            ),
            InputSpec(
                name="tau",
                label="Tau (τ)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Uncertainty scaling on the prior. Typical values 0.025–0.05; "
                    "the manifest exposes it explicitly so the user owns the choice."
                ),
                min=0.001,
                max=1.0,
                step=0.001,
            ),
            InputSpec(
                name="window",
                label="Lookback window",
                control=ControlKind.SELECT,
                required=False,
                description="History used to estimate Σ when the prior is data-driven.",
                options=["180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="frequency",
                label="Frequency",
                control=ControlKind.SELECT,
                required=False,
                description="Return sampling cadence for Σ.",
                options=["1d", "1wk", "1mo"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for price + market cap inputs.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "risk_aversion": 2.5,
            "prior_covariance": "ledoit_wolf",
            "tau": 0.05,
            "window": "1Y",
            "frequency": "1d",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "symbols",
                "prior_returns",
                "posterior_returns",
                "posterior_covariance",
                "views_applied",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", unit="", label="Symbol"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Expected return (ann.)"),
            panes=[],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="prior_return", label="Prior E[r]", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="posterior_return", label="Posterior E[r]", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="delta", label="Δ", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="market_cap_weight", label="Mkt wt", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="tau", label="τ", kind="kpi"),
                CardSlot(key="num_views", label="Views", kind="kpi"),
                CardSlot(key="risk_aversion", label="δ", kind="kpi"),
                CardSlot(key="avg_delta", label="Avg Δ", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BLAK starts from the implied-equilibrium prior π = δ Σ w_mkt, "
            "where δ is the user's risk aversion and w_mkt is the cap-weighted "
            "market portfolio. The user's views are encoded as (P, Q, Ω) where "
            "P is the K×N picking matrix, Q is the K-vector of view returns, "
            "and Ω is the K×K diagonal of view variances (either explicit or "
            "Idzorek-implied from a confidence fraction). The posterior "
            "expected returns and covariance follow Black-Litterman's closed "
            "form: E[r|view] = [(τΣ)^{-1} + P'Ω^{-1}P]^{-1} [(τΣ)^{-1}π + "
            "P'Ω^{-1}Q]. Tau scales the uncertainty of the prior; the manifest "
            "exposes it as a model_assumption control so the user owns the "
            "choice rather than inheriting a hidden default. The posterior is "
            "intended to feed PORT_OPT — BLAK does not solve for weights "
            "itself."
        ),
        formula_dict={
            "ImpliedPrior": Formula(
                expression=r"\pi = \delta \Sigma w_{mkt}",
                variables={"δ": "Risk aversion", "Σ": "Covariance", "w_mkt": "Cap-weighted market portfolio"},
            ),
            "Posterior": Formula(
                expression=r"E[r|view] = \left[(\tau\Sigma)^{-1} + P^\top \Omega^{-1} P\right]^{-1} \left[(\tau\Sigma)^{-1}\pi + P^\top \Omega^{-1} Q\right]",
                variables={"τ": "Prior uncertainty scaler", "P": "Picking matrix", "Q": "View returns", "Ω": "View covariance"},
            ),
            "PosteriorCov": Formula(
                expression=r"\Sigma^* = \Sigma + \left[(\tau\Sigma)^{-1} + P^\top \Omega^{-1} P\right]^{-1}",
                variables={},
            ),
        },
        field_dict={
            "prior_returns": FieldDef(unit="decimal annualized", description="Implied-equilibrium π by symbol.", source="computed"),
            "posterior_returns": FieldDef(unit="decimal annualized", description="BL posterior E[r|view] by symbol.", source="computed"),
            "posterior_covariance": FieldDef(unit="", description="BL posterior covariance matrix Σ*.", source="computed"),
            "views_applied": FieldDef(unit="", description="Echo of (P, Q, Ω) actually used, including any Idzorek expansion.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="blak_priors_views_tau_are_model_assumptions",
                description="The five core BL knobs must be model_assumption controls — never silent.",
                inputs={},
                assertions=[
                    "input 'market_caps' has control == model_assumption",
                    "input 'views' has control == model_assumption",
                    "input 'view_confidence' has control == model_assumption",
                    "input 'tau' has control == model_assumption",
                    "input 'prior_covariance' has control == model_assumption",
                ],
            ),
            SemanticTest(
                name="blak_no_views_returns_prior",
                description="With an empty view set, posterior == prior up to numerical tolerance.",
                inputs={"views": {"P": [], "Q": []}},
                assertions=["max_abs(posterior_returns - prior_returns) < 1e-9"],
            ),
            SemanticTest(
                name="blak_high_confidence_pulls_posterior_toward_view",
                description="Idzorek confidence → 1 on a single absolute view pulls the posterior on that asset close to the view return.",
                inputs={"view_confidence": 0.99},
                assertions=["abs(posterior_view_asset - view_return) < abs(prior_view_asset - view_return)"],
            ),
            SemanticTest(
                name="blak_low_tau_pulls_posterior_toward_prior",
                description="Small τ shrinks the posterior toward π regardless of views.",
                inputs={"tau": 0.001},
                assertions=["max_abs(posterior_returns - prior_returns) < epsilon_for_low_tau"],
            ),
        ],
    )


__all__ = ["blak"]
