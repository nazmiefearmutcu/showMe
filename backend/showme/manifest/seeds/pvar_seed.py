"""PVAR — Portfolio Value-at-Risk and Expected Shortfall.

Three computation methods (parametric / historical / monte_carlo), each
with its own model assumptions. confidence_level, horizon, and method
ride MODEL_ASSUMPTION controls so the user owns the choice — VaR is
notorious for hiding behind defaults.
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
def pvar() -> FunctionManifest:
    return FunctionManifest(
        code="PVAR",
        name="Portfolio VaR & ES",
        category=Category.PORTFOLIO,
        intent=(
            "Compute portfolio Value-at-Risk and Expected Shortfall at user-"
            "selected confidence and horizon, by parametric (Gaussian), "
            "historical-simulation, or Monte Carlo methods. Confidence, "
            "horizon, and method are model_assumption controls — VaR has "
            "no defensible silent default."
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
                name="portfolio_source",
                label="Portfolio source",
                control=ControlKind.SELECT,
                required=True,
                description="PORT (live broker positions) or custom basket.",
                options=["port", "custom"],
            ),
            InputSpec(
                name="positions",
                label="Custom positions",
                control=ControlKind.CONSTRAINT_SET,
                required=False,
                description="When portfolio_source=custom, list of (symbol, qty, price).",
                depends_on=["portfolio_source"],
            ),
            InputSpec(
                name="confidence_level",
                label="Confidence",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Loss-tail confidence level. 95/99/99.5 are standard "
                    "regulatory choices; the manifest forces the user to "
                    "pick one rather than inherit a default."
                ),
                options=[0.95, 0.99, 0.995],
            ),
            InputSpec(
                name="horizon",
                label="Horizon",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Risk horizon in trading days (1d Basel, 10d Basel-stress).",
                options=["1d", "5d", "10d", "20d"],
            ),
            InputSpec(
                name="method",
                label="Method",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Computation method — each has different distributional assumptions.",
                options=["parametric", "historical", "monte_carlo"],
            ),
            InputSpec(
                name="lookback_window",
                label="Lookback",
                control=ControlKind.SELECT,
                required=True,
                description="History used to estimate Σ (parametric) or to resample (historical).",
                options=["180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="mc_paths",
                label="MC paths",
                control=ControlKind.NUMBER,
                required=False,
                description="Monte Carlo sample count.",
                min=1000,
                max=200000,
                step=1000,
                depends_on=["method"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for the price history.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "portfolio_source": "port",
            "confidence_level": 0.99,
            "horizon": "1d",
            "method": "historical",
            "lookback_window": "1Y",
            "mc_paths": 20000,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "var",
                "expected_shortfall",
                "confidence_level",
                "horizon",
                "method",
                "data_mode",
            ],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.DISTRIBUTION,
            x_axis=AxisSpec(type="numeric", unit="ccy", label="P&L"),
            y_axis=AxisSpec(type="numeric", unit="", label="Density"),
            panes=[],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="component_var", label="Comp. VaR", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="incremental_var", label="Incr. VaR", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="marginal_var", label="Marg. VaR", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="weight", label="Weight", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="var", label="VaR", kind="big_number", unit="ccy"),
                CardSlot(key="expected_shortfall", label="ES", kind="big_number", unit="ccy"),
                CardSlot(key="confidence_level", label="Conf.", kind="kpi", unit="%"),
                CardSlot(key="horizon", label="Horizon", kind="kpi"),
                CardSlot(key="method", label="Method", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PVAR computes portfolio loss at the chosen confidence and "
            "horizon by one of three methods. Parametric assumes returns are "
            "multivariate Gaussian: VaR = -μ_p Δt + z_α σ_p √Δt where z_α is "
            "the one-sided normal quantile. Historical simulation resamples "
            "P&L vectors from the actual lookback; VaR is the empirical "
            "quantile and ES the conditional tail mean. Monte Carlo "
            "simulates `mc_paths` correlated draws under a fitted "
            "multivariate t (degrees of freedom estimated). Component VaR "
            "decomposes total VaR back to per-asset contributions using "
            "marginal VaR × position weight. The method and confidence are "
            "echoed verbatim so backtests can reproduce the run."
        ),
        formula_dict={
            "ParametricVaR": Formula(
                expression=r"VaR_\alpha = -\mu_p \Delta t + z_\alpha \sigma_p \sqrt{\Delta t}",
                variables={"z_α": "Normal quantile at α", "Δt": "Horizon (years)"},
            ),
            "HistoricalVaR": Formula(
                expression=r"VaR_\alpha = -\text{quantile}_{1-\alpha}(P_t)",
                variables={"P_t": "Historical P&L vector"},
            ),
            "ExpectedShortfall": Formula(
                expression=r"ES_\alpha = -\mathbb{E}[P \mid P \leq -VaR_\alpha]",
                variables={},
                notes="Mean of the losses beyond VaR.",
            ),
            "ComponentVaR": Formula(
                expression=r"CVaR_i = w_i \cdot \partial VaR / \partial w_i",
                variables={},
                notes="Sums to total VaR by Euler's theorem.",
            ),
        },
        field_dict={
            "var": FieldDef(unit="ccy", description="Loss at the requested confidence; positive number = loss.", source="computed"),
            "expected_shortfall": FieldDef(unit="ccy", description="Conditional expected loss beyond VaR.", source="computed"),
            "component_var[]": FieldDef(unit="ccy", description="Per-position contribution; sums to total VaR.", source="computed"),
            "method": FieldDef(unit="", description="Echoes the chosen method for traceability.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="pvar_confidence_horizon_method_are_model_assumptions",
                description="The three governing VaR knobs ride model_assumption controls.",
                inputs={},
                assertions=[
                    "input 'confidence_level' has control == model_assumption",
                    "input 'horizon' has control == model_assumption",
                    "input 'method' has control == model_assumption",
                ],
            ),
            SemanticTest(
                name="pvar_es_geq_var",
                description="ES is always ≥ VaR for the same confidence.",
                inputs={},
                assertions=["expected_shortfall >= var"],
            ),
            SemanticTest(
                name="pvar_higher_confidence_higher_var",
                description="VaR(99) ≥ VaR(95) on the same portfolio + window.",
                inputs={},
                assertions=["var_at_99 >= var_at_95"],
            ),
            SemanticTest(
                name="pvar_component_var_sums_to_total_var",
                description="Component VaR decomposition is Euler-consistent.",
                inputs={},
                assertions=["abs(sum(component_var) - var) < 1e-3 * var"],
            ),
            SemanticTest(
                name="pvar_horizon_scales_root_t_under_parametric",
                description="Parametric VaR scales as √Δt; 10d ≈ √10 × 1d.",
                inputs={"method": "parametric"},
                assertions=["abs(var_10d / var_1d - sqrt(10)) < 0.05"],
            ),
        ],
    )


__all__ = ["pvar"]
