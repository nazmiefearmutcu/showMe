"""PFA — Portfolio Factor Analysis.

Decompose portfolio returns through a chosen factor model (CAPM, Fama-
French 3F, or Fama-French + momentum 5F) and report per-factor loadings,
contributions, and the residual alpha.
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
def pfa() -> FunctionManifest:
    return FunctionManifest(
        code="PFA",
        name="Portfolio Factor Analysis",
        category=Category.PORTFOLIO,
        intent=(
            "Decompose realized portfolio returns through a chosen factor "
            "model (CAPM / FF3 / FF5+Mom), reporting per-factor loadings, "
            "contribution to return, residual alpha, and R²."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
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
                description="When portfolio_source=custom.",
                depends_on=["portfolio_source"],
            ),
            InputSpec(
                name="factor_model",
                label="Factor model",
                control=ControlKind.SELECT,
                required=True,
                description="Which factor set to regress against.",
                options=["capm", "ff3", "ff5", "ff5_mom", "carhart_4"],
            ),
            InputSpec(
                name="window",
                label="Lookback",
                control=ControlKind.SELECT,
                required=True,
                description="Regression window.",
                options=["1Y", "2Y", "3Y", "5Y", "10Y"],
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
                name="risk_free_rate",
                label="Risk-free rate",
                control=ControlKind.NUMBER,
                required=False,
                description="Used for excess returns when factor data does not include it.",
                min=-0.05,
                max=0.25,
                step=0.0001,
                unit="decimal",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for prices + factor series.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "portfolio_source": "port",
            "factor_model": "ff3",
            "window": "3Y",
            "frequency": "1d",
            "risk_free_rate": 0.045,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["fred", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "factor_model",
                "loadings",
                "contributions",
                "alpha",
                "r_squared",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.ATTRIBUTION_BAR,
            x_axis=AxisSpec(type="category", unit="", label="Factor"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Return contribution"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="factor", label="Factor", kind="tag"),
                ColumnSpec(key="loading", label="β", kind="number", format="%.3f"),
                ColumnSpec(key="t_stat", label="t-stat", kind="number", format="%.2f"),
                ColumnSpec(key="contribution_ann", label="Contr. (ann.)", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="factor_return_ann", label="Factor r (ann.)", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="alpha", label="α (ann.)", kind="big_number", unit="%"),
                CardSlot(key="r_squared", label="R²", kind="kpi"),
                CardSlot(key="market_beta", label="β_mkt", kind="kpi"),
                CardSlot(key="factor_model", label="Model", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PFA computes the portfolio's daily return series r_p,t over "
            "the lookback as Σ w_i,t · r_i,t for current positions (or "
            "rebalanced under the configured weights). The factor data "
            "comes from Ken French's public library (MKT-RF, SMB, HML, "
            "RMW, CMA, MOM as required by the chosen model); the risk-free "
            "rate is the 1-month T-bill from the same source. Excess "
            "returns r_p,t − r_f,t are regressed on the chosen factor "
            "vector by OLS; the intercept is the annualized alpha. "
            "Contribution per factor is β_k · μ_k (annualized factor "
            "return × loading). R² and t-stats are reported with HAC "
            "(Newey-West) standard errors at 5 lags to handle "
            "autocorrelation."
        ),
        formula_dict={
            "CAPM": Formula(
                expression=r"r_p - r_f = \alpha + \beta_{mkt} (r_{mkt} - r_f) + \epsilon",
                variables={"β_mkt": "Market loading", "α": "Excess return"},
            ),
            "FamaFrench3": Formula(
                expression=r"r_p - r_f = \alpha + \beta_{mkt} MKT + \beta_{smb} SMB + \beta_{hml} HML + \epsilon",
                variables={"SMB": "Size factor", "HML": "Value factor"},
            ),
            "Contribution": Formula(
                expression=r"C_k = \beta_k \mu_k",
                variables={"μ_k": "Annualized factor return"},
            ),
            "AnnualizedAlpha": Formula(
                expression=r"\alpha_{ann} = (1 + \alpha)^F - 1",
                variables={"F": "Periods per year"},
            ),
        },
        field_dict={
            "loadings": FieldDef(unit="", description="OLS β by factor.", source="computed"),
            "contributions": FieldDef(unit="decimal annualized", description="β_k μ_k by factor.", source="computed"),
            "alpha": FieldDef(unit="decimal annualized", description="Regression intercept, annualized.", source="computed"),
            "r_squared": FieldDef(unit="", description="OLS coefficient of determination.", source="computed"),
            "t_stats[]": FieldDef(unit="", description="HAC (Newey-West) t-statistics per factor.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="pfa_alpha_plus_contributions_equals_ann_return",
                description="Sum of α + Σ contributions ≈ portfolio's annualized excess return.",
                inputs={},
                assertions=["abs(alpha + sum(contributions) - port_excess_ann) < 1e-3"],
            ),
            SemanticTest(
                name="pfa_r_squared_in_zero_one",
                description="R² is bounded in [0, 1].",
                inputs={},
                assertions=["0.0 <= r_squared <= 1.0"],
            ),
            SemanticTest(
                name="pfa_capm_returns_only_mkt_loading",
                description="CAPM model returns exactly one loading: market beta.",
                inputs={"factor_model": "capm"},
                assertions=["len(loadings) == 1", "loadings contains 'mkt'"],
            ),
            SemanticTest(
                name="pfa_window_shorter_than_min_observations_warns",
                description="Window with < 30 observations after alignment surfaces a warning.",
                inputs={},
                assertions=["warnings_non_empty_when_insufficient_obs"],
            ),
        ],
    )


__all__ = ["pfa"]
