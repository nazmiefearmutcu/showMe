"""MARS — Multi-Asset Risk (ETF-proxy factor regression).

Regresses a multi-asset daily return series on six ETF total-return proxies
and reports factor betas, R-squared, volatility and 95% VaR / ETL. Live
ETF proxies by default; ``reference=true`` serves the labelled template
series. Analysis only: no orders are generated, so there is no paper-mode
control.
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
def mars() -> FunctionManifest:
    return FunctionManifest(
        code="MARS",
        name="Multi-Asset Risk",
        category=Category.PORTFOLIO,
        intent=(
            "Regress a multi-asset return series on six ETF total-return proxies "
            "to estimate factor betas, R-squared, volatility and 95% VaR / ETL; "
            "live by default, labelled template only on request."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
        ],
        inputs=[
            InputSpec(
                name="symbols",
                label="Universe",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Comma-separated tickers whose equal-weight return series is "
                    "regressed. Defaults to the handler universe when empty."
                ),
            ),
            InputSpec(
                name="years",
                label="History (years)",
                control=ControlKind.NUMBER,
                required=False,
                description="Calendar years of daily history to regress on.",
                min=1,
                max=10,
                step=1,
                unit="years",
            ),
            InputSpec(
                name="reference",
                label="Labelled template (MODEL)",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "true serves the labelled template return series instead of "
                    "live ETF proxies; regression statistics are then not estimated."
                ),
            ),
        ],
        defaults={
            "years": 3,
            "reference": False,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "alpha_annualized",
                "factor_loadings",
                "r_squared",
                "annualized_volatility",
                "var_95_daily_loss",
                "samples",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", unit="", label="Factor"),
            y_axis=AxisSpec(type="numeric", unit="", label="Regression beta"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="factor", label="Factor", kind="text"),
                ColumnSpec(key="loading", label="Loading", kind="number", format="%.4f"),
                ColumnSpec(key="abs_loading", label="|Loading|", kind="number", format="%.4f"),
                ColumnSpec(key="meaning", label="Meaning", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="r_squared", label="R²", kind="kpi"),
                CardSlot(key="annualized_volatility", label="Vol (ann.)", kind="kpi"),
                CardSlot(key="var_95_daily_loss", label="VaR 95 (1d loss)", kind="kpi"),
                CardSlot(key="samples", label="Samples", kind="kpi"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MARS regresses the daily return series of the universe on six ETF "
            "total-return proxies by ordinary least squares with an intercept: "
            "MKT=SPY, SMB=IWM, HML=VLUE, MOM=MTUM, QMJ=QUAL, BAB=USMV. These are "
            "long-only ETFs, not Fama-French long-short premia, and they are highly "
            "correlated, so individual betas are not separable exposures. Alpha is "
            "annualized as 252 x daily alpha. VaR and ETL are reported as positive "
            "daily losses. reference=true serves the labelled template series."
        ),
        formula_dict={
            "OLS": Formula(
                expression=r"r_{p,t} = \alpha + \sum_k \beta_k f_{k,t} + \varepsilon_t",
                variables={
                    "r_{p,t}": "Portfolio daily return",
                    "f_{k,t}": "ETF proxy daily return for factor k",
                    "\\beta_k": "Factor loading",
                },
            ),
            "AnnualizedAlpha": Formula(
                expression=r"\alpha_{ann} = 252 \cdot \alpha_{daily}",
                variables={"\\alpha_{daily}": "Intercept of the daily regression"},
            ),
        },
        field_dict={
            "alpha_annualized": FieldDef(unit="decimal", description="Annualized regression intercept (252 x daily).", source="computed"),
            "factor_loadings": FieldDef(unit="beta", description="OLS betas to the named ETF proxies.", source="computed"),
            "r_squared": FieldDef(unit="decimal", description="Share of portfolio return variance explained by the proxies.", source="computed"),
            "var_95_daily_loss": FieldDef(unit="decimal", description="5th-percentile daily loss, positive number.", source="computed"),
            "samples": FieldDef(unit="count", description="Overlapping daily observations used in the regression.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="mars_factor_proxies_are_etf_total_return",
                description="The factor set is six ETF total-return proxies, not Fama-French premia.",
                inputs={},
                assertions=["factor_proxies == ['SPY', 'IWM', 'VLUE', 'MTUM', 'QUAL', 'USMV']"],
            ),
            SemanticTest(
                name="mars_reference_is_labelled_not_live",
                description="reference=true never claims a live data mode.",
                inputs={"reference": True},
                assertions=["metadata.live == False", "metadata.data_mode == 'modeled'"],
            ),
            SemanticTest(
                name="mars_partial_factor_coverage_is_labelled",
                description="Any missing ETF proxy downgrades the labels and names the proxy.",
                inputs={},
                assertions=["missing proxy -> metadata.live == False", "warnings name the missing proxy"],
            ),
        ],
    )


__all__ = ["mars"]
