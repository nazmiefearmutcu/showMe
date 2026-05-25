"""REGM — Macro Regime Classifier.

Internal model classifies the prevailing macro regime (e.g. early-cycle,
mid-cycle, late-cycle, recession; or risk-on / risk-off; or
disinflation / stagflation) from a configurable set of regime features
sourced from FRED. Regime label is the headline; per-feature scores
expose the model's reasoning so the analyst can disagree.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
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
def regm() -> FunctionManifest:
    return FunctionManifest(
        code="REGM",
        name="Macro Regime Classifier",
        category=Category.MACRO,
        intent=(
            "Classify the prevailing macro regime (early/mid/late cycle, recession, "
            "stagflation, disinflation, risk-on/off) from a transparent set of "
            "configurable features — yield curve slope, ISM, real rates, credit "
            "spreads, unemployment trend — with per-feature contribution scores so "
            "the analyst can see the model's reasoning and disagree."
        ),
        asset_classes=[
            AssetClass.RATE,
            AssetClass.BOND,
            AssetClass.EQUITY,
            AssetClass.FX,
            AssetClass.COMMODITY,
        ],
        inputs=[
            InputSpec(
                name="regime_taxonomy",
                label="Taxonomy",
                control=ControlKind.SELECT,
                required=True,
                description="Which regime taxonomy to classify against.",
                options=["business_cycle", "risk_on_off", "inflation_growth"],
            ),
            InputSpec(
                name="features",
                label="Features",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Regime feature set: yield curve slope, ISM, real rates, credit spreads, unemployment trend, etc. Empty = curated defaults per taxonomy.",
                options=[
                    "yield_curve_slope_2s10s",
                    "ism_manufacturing",
                    "real_fed_funds",
                    "ig_credit_spread",
                    "hy_credit_spread",
                    "unemployment_trend",
                    "core_pce_yoy",
                    "vix_level",
                ],
            ),
            InputSpec(
                name="window",
                label="Smoothing window",
                control=ControlKind.SELECT,
                required=False,
                description="How many months of feature history to smooth before classification.",
                options=["1m", "3m", "6m", "12m"],
            ),
            InputSpec(
                name="model_threshold",
                label="Confidence floor",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Minimum classifier confidence for a definitive regime label; below this returns 'transitional'.",
                min=0.0,
                max=1.0,
                step=0.05,
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "regime_taxonomy": "business_cycle",
            "features": [],
            "window": "3m",
            "model_threshold": 0.55,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["fred", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["regime_label", "confidence", "features", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="feature", label="Feature", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.2f"),
                ColumnSpec(key="zscore", label="Z", kind="number", format="%.2f", unit="σ"),
                ColumnSpec(key="contribution", label="Contribution", kind="number", format="%.2f"),
                ColumnSpec(key="direction", label="Dir", kind="tag"),
                ColumnSpec(key="source_series_id", label="FRED ID", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="regime_label", label="Regime", kind="big_number"),
                CardSlot(key="confidence", label="Confidence", kind="kpi"),
                CardSlot(key="taxonomy", label="Taxonomy", kind="badge"),
                CardSlot(key="dominant_feature", label="Top Feature", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "REGM is an internal regime classifier. Features come from FRED — yield curve "
            "slope (T10Y2Y), ISM PMI (NAPM), real Fed Funds (FEDFUNDS - core PCE YoY), credit "
            "spreads (BAMLC0A0CM, BAMLH0A0HYM2), unemployment 3m trend, etc — each smoothed "
            "over the configured window. A taxonomy-specific logistic model maps the feature "
            "vector to a regime label probability vector; the label with the highest probability "
            "is the headline regime IF the probability exceeds model_threshold, otherwise the "
            "label is 'transitional' and the warning explains the threshold miss. Per-feature "
            "contribution scores (Shapley-style decomposition over the logistic linear predictor) "
            "are returned in the features array so the analyst can see exactly which inputs "
            "drove the classification. Live FRED is the data source; the regime call itself is "
            "always modeled — data_mode reports 'modeled' for the regime label and "
            "'live_official' for each feature value to keep provenance honest."
        ),
        formula_dict={
            "feature_zscore": Formula(
                expression=r"z_{i} = \frac{x_{i} - \mu_{i, 5y}}{\sigma_{i, 5y}}",
                variables={
                    "x_i": "Smoothed feature value at as_of",
                    "mu_{i, 5y}": "Trailing 5y feature mean",
                    "sigma_{i, 5y}": "Trailing 5y feature stdev",
                },
                notes="Each feature is z-scored vs its own 5y history.",
            ),
            "regime_prob": Formula(
                expression=r"P(regime_k) = \frac{\exp(\beta_k^T z)}{\sum_j \exp(\beta_j^T z)}",
                variables={
                    "z": "Z-scored feature vector",
                    "beta_k": "Taxonomy-specific weight vector for regime k",
                },
                notes="Multinomial logistic over the feature vector.",
            ),
        },
        field_dict={
            "regime_label": FieldDef(description="Headline regime label (or 'transitional' when below threshold).", source="model"),
            "confidence": FieldDef(unit="[0,1]", description="Probability of the selected regime label.", source="model"),
            "features[].feature": FieldDef(description="Feature name.", source="reference"),
            "features[].value": FieldDef(unit="varies", description="Smoothed feature value at as_of.", source="fred"),
            "features[].zscore": FieldDef(unit="σ", description="Feature z-score vs 5y history.", source="computed"),
            "features[].contribution": FieldDef(description="Shapley-style contribution to the chosen regime's logit.", source="model"),
            "features[].direction": FieldDef(description="Sign of the contribution (supports / opposes).", source="computed"),
            "features[].source_series_id": FieldDef(description="FRED series id used to pull the raw value.", source="reference"),
            "data_mode": FieldDef(description="modeled for the regime label; features carry their own provider modes.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="regm_label_below_threshold_is_transitional",
                description="When max regime probability < model_threshold, asserts regime_label == 'transitional' and a warning mentions the threshold.",
                inputs={"model_threshold": 0.95, "_mock": "ambiguous_features"},
                assertions=[
                    "regime_label_equals_transitional",
                    "warning_mentions_confidence_below_threshold",
                ],
            ),
            SemanticTest(
                name="regm_feature_zscores_are_signed",
                description="Asserts every feature row has a signed zscore (negative below mean, positive above) — never an unsigned |z|.",
                inputs={},
                assertions=["feature_zscore_is_signed_not_absolute"],
            ),
            SemanticTest(
                name="regm_data_mode_modeled_for_label",
                description="Asserts data_mode is reported as 'modeled' for the regime label even when feature values are live.",
                inputs={},
                assertions=["data_mode_equals_modeled_for_label"],
            ),
            SemanticTest(
                name="regm_contributions_sum_to_logit",
                description="Asserts sum(features[].contribution) ≈ logit(chosen_regime) within 1e-4 — the decomposition is faithful.",
                inputs={},
                assertions=["contribution_sum_matches_logit_within_1e-4"],
            ),
        ],
    )


__all__ = ["regm"]
