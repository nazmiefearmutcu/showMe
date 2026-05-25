"""PCAS — Principal Component Shocks.

Decompose portfolio risk into N principal components and apply user-
defined shocks to each. Used to stress idiosyncratic vs systematic risk
without naming named scenarios (which STRS owns). n_factors is the key
model knob, exposed as MODEL_ASSUMPTION.
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
def pcas() -> FunctionManifest:
    return FunctionManifest(
        code="PCAS",
        name="Principal Component Shocks",
        category=Category.PORTFOLIO,
        intent=(
            "Decompose portfolio return covariance into principal components "
            "and apply orthogonal shocks to each, reporting per-PC and "
            "aggregate P&L impact. The number of retained factors is a "
            "model_assumption — the user owns the choice."
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
                name="n_factors",
                label="N factors",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Number of principal components to retain. Choose to "
                    "explain ≥ X% of variance or pick fixed N."
                ),
                min=1,
                max=20,
                step=1,
            ),
            InputSpec(
                name="lookback_window",
                label="Lookback",
                control=ControlKind.SELECT,
                required=True,
                description="History used to estimate Σ.",
                options=["90d", "180d", "1Y", "2Y", "5Y"],
            ),
            InputSpec(
                name="shock_set",
                label="Shocks (σ)",
                control=ControlKind.CONSTRAINT_SET,
                required=False,
                description=(
                    "Per-PC shock magnitudes in units of σ. Default 1σ on "
                    "each retained component."
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
            "n_factors": 3,
            "lookback_window": "1Y",
            "frequency": "1d",
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
                "components",
                "shock_impacts",
                "aggregate_impact",
                "explained_variance",
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
            x_axis=AxisSpec(type="category", unit="", label="Component"),
            y_axis=AxisSpec(type="numeric", unit="ccy", label="Shock impact"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="component", label="PC", kind="tag"),
                ColumnSpec(key="explained_variance_pct", label="Var %", kind="percent", unit="%", format="%.1f"),
                ColumnSpec(key="shock_sigma", label="Shock σ", kind="number", format="%.1f"),
                ColumnSpec(key="impact_value", label="P&L Δ", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="impact_pct", label="P&L Δ%", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="aggregate_impact", label="Total Δ", kind="big_number", unit="ccy"),
                CardSlot(key="n_factors", label="Factors", kind="kpi"),
                CardSlot(key="explained_variance", label="Var explained", kind="kpi", unit="%"),
                CardSlot(key="largest_pc", label="Biggest PC", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PCAS estimates the covariance matrix Σ from the universe of "
            "currently-held positions over the lookback window and computes "
            "the eigen-decomposition Σ = VΛV'. The top `n_factors` "
            "eigenvectors define orthogonal directions in return space. For "
            "each PC k, the assumed shock vector r_k = s_k √λ_k v_k (where "
            "s_k is the user-supplied shock in units of σ) maps to "
            "portfolio P&L via Δ_k = w' r_k × total_market_value. The "
            "aggregate impact is the linear sum across active shocks. "
            "Explained variance ratio = Σ_{k≤K} λ_k / Σ λ_i is reported so "
            "the user can see how much risk the retained components "
            "actually cover."
        ),
        formula_dict={
            "EigenDecomposition": Formula(
                expression=r"\Sigma = V \Lambda V^\top",
                variables={"V": "Eigenvectors (orthonormal)", "Λ": "Eigenvalue diagonal"},
            ),
            "PCShock": Formula(
                expression=r"r_k = s_k \sqrt{\lambda_k} v_k",
                variables={"s_k": "User shock in σ units", "v_k": "k-th eigenvector"},
            ),
            "PnLImpact": Formula(
                expression=r"\Delta_k = w^\top r_k \cdot MV",
                variables={"w": "Position weights", "MV": "Total market value"},
            ),
            "ExplainedVariance": Formula(
                expression=r"EV_K = \sum_{k \leq K} \lambda_k / \sum_i \lambda_i",
                variables={},
            ),
        },
        field_dict={
            "components[]": FieldDef(unit="", description="One entry per retained PC with eigenvalue + loading vector.", source="computed"),
            "shock_impacts[]": FieldDef(unit="ccy", description="Per-PC P&L impact at the requested shock magnitude.", source="computed"),
            "aggregate_impact": FieldDef(unit="ccy", description="Linear sum of per-PC impacts.", source="computed"),
            "explained_variance": FieldDef(unit="decimal", description="Variance share covered by retained PCs.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="pcas_n_factors_is_model_assumption",
                description="N-factor choice is exposed as a model_assumption control.",
                inputs={},
                assertions=["input 'n_factors' has control == model_assumption"],
            ),
            SemanticTest(
                name="pcas_eigenvalues_descending",
                description="Components are ordered by descending eigenvalue.",
                inputs={},
                assertions=["lambda_k_monotonically_decreasing"],
            ),
            SemanticTest(
                name="pcas_explained_variance_in_zero_one",
                description="EV ratio is in [0, 1].",
                inputs={},
                assertions=["0.0 <= explained_variance <= 1.0"],
            ),
            SemanticTest(
                name="pcas_aggregate_sums_components",
                description="Aggregate impact equals the sum of per-PC impacts (linear).",
                inputs={},
                assertions=["abs(aggregate_impact - sum(shock_impacts)) < 1e-6"],
            ),
        ],
    )


__all__ = ["pcas"]
