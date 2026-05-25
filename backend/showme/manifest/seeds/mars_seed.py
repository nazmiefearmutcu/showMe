"""MARS — Mean-reverting allocation.

Allocates to a universe whose return signal is assumed to revert to a
slow-moving anchor (e.g. cross-sectional or pairwise z-score reversion).
Lookback, regime detector, and half-life ride MODEL_ASSUMPTION controls.
Paper-safe by default.
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
        name="Mean-Reverting Allocation",
        category=Category.PORTFOLIO,
        intent=(
            "Allocate to a universe under a mean-reversion assumption: long "
            "the most-oversold, short the most-overbought, sized by the "
            "estimated half-life of reversion. Half-life, regime assumption, "
            "and lookback ride model_assumption controls."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
        ],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Instruments to score and allocate.",
            ),
            InputSpec(
                name="lookback_window",
                label="Lookback window",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="History used to estimate the z-score anchor.",
                options=["30d", "60d", "90d", "180d", "1Y"],
            ),
            InputSpec(
                name="reversion_half_life",
                label="Reversion half-life (days)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Assumed half-life over which the signal decays back to "
                    "its anchor. Drives leverage sizing."
                ),
                min=1,
                max=120,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="regime_assumption",
                label="Regime assumption",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Stationarity model used to qualify the signal.",
                options=["stationary", "trending_filter", "ou_process"],
            ),
            InputSpec(
                name="signal",
                label="Signal",
                control=ControlKind.SELECT,
                required=False,
                description="Underlying mean-reversion signal.",
                options=["zscore", "rsi_extreme", "ou_residual"],
            ),
            InputSpec(
                name="gross_leverage_cap",
                label="Gross leverage cap",
                control=ControlKind.NUMBER,
                required=False,
                description="Σ|w_i| ceiling.",
                min=0.5,
                max=4.0,
                step=0.1,
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Research-only by default.",
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
            "lookback_window": "90d",
            "reversion_half_life": 10,
            "regime_assumption": "stationary",
            "signal": "zscore",
            "gross_leverage_cap": 2.0,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "weights",
                "signal_scores",
                "expected_half_life_days",
                "gross_exposure",
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
            y_axis=AxisSpec(type="numeric", unit="z", label="Signal score"),
            panes=[],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="signal", label="Signal", kind="number", format="%.2f"),
                ColumnSpec(key="weight", label="Weight", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="half_life_days", label="Half-life", kind="number", unit="d", format="%.1f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="gross_exposure", label="Gross", kind="big_number", unit="%"),
                CardSlot(key="net_exposure", label="Net", kind="kpi", unit="%"),
                CardSlot(key="expected_half_life_days", label="Half-life", kind="kpi", unit="d"),
                CardSlot(key="signal_range", label="Signal Δ", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MARS computes a per-asset mean-reversion score over the chosen "
            "lookback. For zscore, the score is (price - rolling_mean) / "
            "rolling_std; for ou_residual it is the residual of an "
            "Ornstein-Uhlenbeck fit; rsi_extreme converts RSI distance from "
            "50 into a z-equivalent. The regime_assumption guards entry: "
            "stationary always enters; trending_filter rejects assets in a "
            "strong trend; ou_process requires a significant mean-reversion "
            "fit (p-value < 0.05). Weights are proportional to -score "
            "(buy the oversold), scaled so Σ|w_i| ≤ gross_leverage_cap. The "
            "expected_half_life_days is the assumption echoed back to the "
            "user — actual realized half-life is observed, not predicted. "
            "Research surface: paper_mode defaults true."
        ),
        formula_dict={
            "ZScore": Formula(
                expression=r"z_i = (p_i - \mu_i) / \sigma_i",
                variables={"μ_i": "Rolling mean", "σ_i": "Rolling std"},
            ),
            "OUHalfLife": Formula(
                expression=r"\tau_{1/2} = \ln 2 / \theta",
                variables={"θ": "Mean-reversion speed of OU fit"},
            ),
            "Weight": Formula(
                expression=r"w_i = -z_i / \sum_j |z_j| \cdot L",
                variables={"L": "Gross leverage cap"},
            ),
        },
        field_dict={
            "weights": FieldDef(unit="decimal", description="Long-short weight vector, sums to ~0 by construction.", source="optimizer"),
            "signal_scores": FieldDef(unit="z", description="Per-asset reversion signal score.", source="computed"),
            "expected_half_life_days": FieldDef(unit="days", description="User-supplied half-life, echoed for traceability.", source="input"),
            "gross_exposure": FieldDef(unit="decimal", description="Σ|w_i| at the returned weights.", source="optimizer"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="mars_lookback_half_life_regime_are_model_assumptions",
                description="The three MARS assumptions ride model_assumption controls.",
                inputs={},
                assertions=[
                    "input 'lookback_window' has control == model_assumption",
                    "input 'reversion_half_life' has control == model_assumption",
                    "input 'regime_assumption' has control == model_assumption",
                ],
            ),
            SemanticTest(
                name="mars_paper_mode_defaults_true",
                description="Research surface ships paper-safe.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="mars_oversold_long_overbought_short",
                description="Most-negative score must produce a long weight; most-positive a short.",
                inputs={"universe": ["A", "B"]},
                assertions=["w_min_score > 0", "w_max_score < 0"],
            ),
            SemanticTest(
                name="mars_gross_cap_respected",
                description="Σ|w_i| ≤ gross_leverage_cap within numeric tolerance.",
                inputs={"gross_leverage_cap": 1.0},
                assertions=["sum_abs_weights <= 1.0 + 1e-6"],
            ),
        ],
    )


__all__ = ["mars"]
