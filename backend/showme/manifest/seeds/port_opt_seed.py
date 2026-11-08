"""PORT_OPT — Mean-variance portfolio optimization with efficient frontier.

Solved by in-house mean-variance code (services/optimizer.py); no external
optimizer library is used. The manifest locks the contract: frontier-grammar
chart, weight + constraint inputs, exportable optimal-weights vector + frontier
array. Inputs the handler does not apply are reported in ``unapplied_inputs``.
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
def port_opt() -> FunctionManifest:
    return FunctionManifest(
        code="PORT_OPT",
        name="Portfolio Optimization",
        category=Category.PORTFOLIO,
        intent=(
            "Compute the efficient frontier and the max-Sharpe, min-volatility "
            "and risk-parity long-only weights for a chosen universe from "
            "historical daily returns. Solvers are hand-written in-house "
            "mean-variance code; no external optimizer library is used."
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
                description="Instruments to consider for the optimization.",
            ),
            InputSpec(
                name="objective",
                label="Objective",
                control=ControlKind.SELECT,
                required=True,
                description="Optimization objective.",
                options=[
                    "max_sharpe",
                    "min_volatility",
                    "max_return",
                    "target_return",
                    "target_volatility",
                    "max_quadratic_utility",
                ],
            ),
            InputSpec(
                name="risk_model",
                label="Risk model",
                control=ControlKind.SELECT,
                required=True,
                description="Covariance estimator. Only sample_cov is applied; other choices are reported in unapplied_inputs.",
                options=[
                    "sample_cov",
                    "ledoit_wolf",
                    "oracle_approximating",
                    "exp_cov",
                    "semicovariance",
                ],
            ),
            InputSpec(
                name="return_model",
                label="Expected returns",
                control=ControlKind.SELECT,
                required=True,
                description="Expected-returns estimator.",
                options=["mean_historical", "ema_historical", "capm_return"],
            ),
            InputSpec(
                name="window",
                label="Lookback window",
                control=ControlKind.SELECT,
                required=True,
                description="History used to estimate µ and Σ.",
                options=["90d", "180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="frequency",
                label="Frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Return sampling cadence.",
                options=["1d", "1wk", "1mo"],
            ),
            InputSpec(
                name="constraints",
                label="Constraints",
                control=ControlKind.CONSTRAINT_SET,
                required=False,
                description=(
                    "Mapping such as {\"max_weight\": 0.2}. max_weight is a long-only per-asset cap "
                    "enforced in min-volatility, max-Sharpe and the frontier (not in risk parity or "
                    "short solutions). Sector/group caps are not applied; any unapplied key is "
                    "reported in unapplied_inputs."
                ),
            ),
            InputSpec(
                name="risk_free_rate",
                label="Risk-free rate",
                control=ControlKind.NUMBER,
                required=False,
                description="Annualized risk-free rate used in Sharpe-style objectives.",
                min=-0.05,
                max=0.25,
                step=0.0001,
                unit="decimal",
            ),
            InputSpec(
                name="frontier_points",
                label="Frontier points",
                control=ControlKind.NUMBER,
                required=False,
                description="Number of points to sample along the efficient frontier.",
                min=10,
                max=200,
                step=1,
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
            "objective": "max_sharpe",
            "risk_model": "ledoit_wolf",
            "return_model": "mean_historical",
            "window": "1Y",
            "frequency": "1d",
            "risk_free_rate": 0.045,
            "frontier_points": 60,
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
                "weights",
                "expected_return",
                "expected_volatility",
                "sharpe",
                "frontier",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.FRONTIER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Volatility (ann.)"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Expected return (ann.)"),
            panes=[],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="weight", label="Weight", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="expected_return", label="E[r]", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="contribution_vol", label="Risk contr.", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="weight_cap", label="Cap", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="expected_return", label="E[r]", kind="big_number", unit="%"),
                CardSlot(key="expected_volatility", label="σ", kind="kpi", unit="%"),
                CardSlot(key="sharpe", label="Sharpe", kind="kpi"),
                CardSlot(key="diversification_ratio", label="Div. ratio", kind="kpi"),
                CardSlot(key="universe_size", label="N", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PORT_OPT fetches daily close-to-close returns per symbol over the "
            "lookback (a calendar-day window; the sample count is the number of "
            "trading-day returns inside it). It estimates annualized mean returns "
            "(252-day annualization) and the sample covariance, then solves "
            "long-only mean-variance problems with in-house solvers. Max-Sharpe "
            "starts from the analytical tangency portfolio and runs projected "
            "gradient ascent. Min-volatility uses projected gradient descent on the "
            "simplex with no return target and no multiplier. The frontier uses "
            "projected gradient descent with an adaptive Lagrange multiplier for the "
            "return target. The frontier "
            "samples targets between the lowest and highest single-asset annualized "
            "mean; targets the solver cannot reach repeat one portfolio, so duplicate "
            "points are removed. Risk parity uses cyclical coordinate descent and "
            "reports converged and max_risk_contribution_error; min-volatility and max-Sharpe report "
            "converged and solver_residual. Symbols "
            "whose live returns cannot be fetched are listed in dropped_symbols with "
            "status partial; with fewer than two survivors no weights are produced "
            "(status provider_unavailable). Declared inputs this optimizer does not "
            "apply, such as sector/group caps or non-sample covariance estimators, are "
            "listed in unapplied_inputs and reported as warnings."
        ),
        formula_dict={
            "PortfolioReturn": Formula(
                expression=r"\mu_p = w^\top \mu",
                variables={"w": "Weight vector", "µ": "Expected returns"},
            ),
            "PortfolioVol": Formula(
                expression=r"\sigma_p = \sqrt{w^\top \Sigma w}",
                variables={"Σ": "Covariance matrix"},
            ),
            "Sharpe": Formula(
                expression=r"SR = (\mu_p - r_f) / \sigma_p",
                variables={"r_f": "Annualized risk-free rate"},
            ),
            "RiskContribution": Formula(
                expression=r"RC_i = w_i (\Sigma w)_i / (w^\top \Sigma w)",
                variables={},
                notes="Sum of RC_i across i equals 1.",
            ),
        },
        field_dict={
            "weights": FieldDef(unit="decimal", description="Weight vector keyed by symbol; sums to 1 under standard constraints.", source="optimizer"),
            "expected_return": FieldDef(unit="decimal annualized", description="µ_p of the optimal portfolio.", source="optimizer"),
            "expected_volatility": FieldDef(unit="decimal annualized", description="σ_p of the optimal portfolio.", source="optimizer"),
            "sharpe": FieldDef(unit="", description="Sharpe ratio of the optimal portfolio at risk_free_rate.", source="optimizer"),
            "frontier": FieldDef(unit="", description="Array of {target_return, volatility, weights} samples.", source="optimizer"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="port_opt_chart_grammar_is_frontier",
                description="The efficient-frontier chart grammar is locked at the manifest layer.",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'frontier'"],
            ),
            SemanticTest(
                name="port_opt_weights_sum_to_one_under_standard_constraints",
                description="Default long-only fully-invested run.",
                inputs={"universe": ["A", "B", "C"], "objective": "max_sharpe"},
                assertions=["sum(weights.values()) == 1.0 within 1e-6"],
            ),
            SemanticTest(
                name="port_opt_min_vol_lt_max_sharpe_vol",
                description="Min-volatility frontier point has σ ≤ max-Sharpe σ for the same universe.",
                inputs={"universe": ["A", "B", "C"]},
                assertions=["sigma_min_vol <= sigma_max_sharpe + tolerance"],
            ),
            SemanticTest(
                name="port_opt_infeasible_constraints_warns_no_silent_fallback",
                description="Constraint set with impossible bounds returns a warning and no weights.",
                inputs={"constraints": {"impossible": True}},
                assertions=[
                    "warnings_non_empty",
                    "weights_empty_or_absent",
                ],
            ),
        ],
    )


__all__ = ["port_opt"]
