"""RPAR — Risk Parity Allocation.

Risk-parity weights equalize each asset's marginal contribution to total
portfolio variance: σ_i × w_i = constant. The risk_target, lookback_window,
and covariance estimator ride MODEL_ASSUMPTION controls so the rebuild
contract never lets the model assumption hide behind a default. Research
surface only — paper_mode defaults true so no live trade can be triggered.
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
def rpar() -> FunctionManifest:
    return FunctionManifest(
        code="RPAR",
        name="Risk Parity Allocation",
        category=Category.PORTFOLIO,
        intent=(
            "Solve for risk-parity weights where each asset contributes "
            "equally (or to a user-defined risk-budget split) to total "
            "portfolio variance. Risk target, lookback, and covariance "
            "estimator are exposed as model_assumption controls — no silent "
            "defaults."
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
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Instruments to receive a risk-parity weight.",
            ),
            InputSpec(
                name="risk_target",
                label="Annualized risk target",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Total portfolio σ target (decimal annualized). Solver "
                    "scales weights to hit this number after equalizing risk "
                    "contributions."
                ),
                min=0.01,
                max=0.50,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="lookback_window",
                label="Lookback window",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="History used to estimate Σ.",
                options=["90d", "180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="covariance_model",
                label="Covariance estimator",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="How Σ is estimated from the lookback returns.",
                options=["sample_cov", "ledoit_wolf", "exp_cov", "oracle_approximating"],
            ),
            InputSpec(
                name="risk_budget",
                label="Risk budget",
                control=ControlKind.CONSTRAINT_SET,
                required=False,
                description=(
                    "Per-asset risk share. Omit for equal-risk parity; "
                    "supply a dict for budgeted parity."
                ),
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
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Research-only by default. True means weights are a "
                    "preview only and cannot fire orders."
                ),
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
            "risk_target": 0.10,
            "lookback_window": "1Y",
            "covariance_model": "ledoit_wolf",
            "frequency": "1d",
            "paper_mode": True,
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
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "weights",
                "risk_contributions",
                "expected_volatility",
                "diversification_ratio",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.RISK_CONTRIBUTION_BAR,
            x_axis=AxisSpec(type="category", unit="", label="Symbol"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Risk contribution"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="weight", label="Weight", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="risk_contribution", label="Risk contr.", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="marginal_risk", label="Marg. σ", kind="percent", unit="%", format="%.4f"),
                ColumnSpec(key="vol", label="σ_i", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="expected_volatility", label="Port σ", kind="big_number", unit="%"),
                CardSlot(key="diversification_ratio", label="Div. ratio", kind="kpi"),
                CardSlot(key="risk_target", label="Target σ", kind="kpi", unit="%"),
                CardSlot(key="universe_size", label="N", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "RPAR estimates the covariance matrix Σ from the universe's "
            "return history at the chosen frequency and lookback. The "
            "risk-parity weights solve σ_i × w_i = c for all i, where σ_i is "
            "the i-th asset's marginal risk contribution (Σw)_i / σ_p and c "
            "is the parity constant. Equal-risk parity sets c = 1/N; "
            "budgeted parity sets per-asset target shares b_i with Σb_i = 1. "
            "The solver uses an iterative log-barrier / Newton step on the "
            "convex relaxation; failures (singular Σ, dropped universe) "
            "surface as warnings. Final weights are scaled so port σ matches "
            "the risk_target. This is a research surface — paper_mode "
            "defaults true so the weight vector cannot be wired into any "
            "live execution path."
        ),
        formula_dict={
            "RiskContribution": Formula(
                expression=r"RC_i = w_i (\Sigma w)_i / (w^\top \Sigma w)",
                variables={"w": "Weights", "Σ": "Covariance"},
                notes="Σ RC_i = 1 by construction.",
            ),
            "ParityCondition": Formula(
                expression=r"\sigma_i \cdot w_i = c \quad \forall i",
                variables={"σ_i": "Marginal risk", "c": "Parity constant"},
            ),
            "PortVol": Formula(
                expression=r"\sigma_p = \sqrt{w^\top \Sigma w}",
                variables={},
            ),
            "DiversificationRatio": Formula(
                expression=r"DR = (w^\top \sigma) / \sigma_p",
                variables={"σ": "Per-asset volatility vector"},
            ),
        },
        field_dict={
            "weights": FieldDef(unit="decimal", description="Risk-parity weights keyed by symbol.", source="optimizer"),
            "risk_contributions": FieldDef(unit="decimal", description="Per-asset risk contribution share (sums to 1).", source="optimizer"),
            "expected_volatility": FieldDef(unit="decimal annualized", description="Total portfolio σ at the returned weights.", source="optimizer"),
            "diversification_ratio": FieldDef(unit="", description="Σ w_i σ_i / σ_p; >1 indicates diversification benefit.", source="optimizer"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="rpar_risk_target_lookback_covariance_are_model_assumptions",
                description="The three core RPAR knobs must be model_assumption controls.",
                inputs={},
                assertions=[
                    "input 'risk_target' has control == model_assumption",
                    "input 'lookback_window' has control == model_assumption",
                    "input 'covariance_model' has control == model_assumption",
                ],
            ),
            SemanticTest(
                name="rpar_paper_mode_defaults_true",
                description="Research surfaces ship paper-safe by default.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="rpar_equal_risk_contributions_under_default",
                description="With no risk_budget, RC_i ≈ 1/N for every i.",
                inputs={"universe": ["A", "B", "C"]},
                assertions=["max_abs(rc_i - 1/N) < 1e-4"],
            ),
            SemanticTest(
                name="rpar_port_vol_matches_target",
                description="Output expected_volatility equals risk_target within tolerance.",
                inputs={"risk_target": 0.10},
                assertions=["abs(expected_volatility - 0.10) < 1e-3"],
            ),
            SemanticTest(
                name="rpar_singular_covariance_warns_no_silent_fallback",
                description="Rank-deficient Σ surfaces a warning rather than equal-weight fallback.",
                inputs={},
                assertions=["warnings_non_empty", "weights_empty_or_absent"],
            ),
        ],
    )


__all__ = ["rpar"]
