"""MLSIG — ML signal generator.

Generic feature-set + label-horizon ML signal pipeline. Trains a chosen
model family (tree ensemble or linear) on engineered features, outputs
per-bar predictions and feature importances. Paper-safe — signal is
research output, not an order router.
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
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def mlsig() -> FunctionManifest:
    return FunctionManifest(
        code="MLSIG",
        name="ML Signal Generator",
        category=Category.PORTFOLIO,
        intent=(
            "Train a chosen ML model family (tree ensemble or linear) on "
            "an engineered feature set to predict labels at a chosen "
            "horizon; output per-bar predictions, feature importances, and "
            "validation metrics. Strictly research — predictions never wire "
            "directly to a live broker."
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
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Single instrument; multi-symbol training uses BMTX hand-off.",
            ),
            InputSpec(
                name="feature_set",
                label="Feature set",
                control=ControlKind.MULTISELECT,
                required=True,
                description=(
                    "Engineered features to include. Each maps to a "
                    "deterministic function over the OHLCV history."
                ),
                options=[
                    "returns_1d",
                    "returns_5d",
                    "rsi_14",
                    "macd",
                    "atr_14",
                    "bb_pct",
                    "volume_zscore",
                    "ema_cross",
                    "ichimoku",
                    "vwap_distance",
                ],
            ),
            InputSpec(
                name="label_horizon",
                label="Label horizon",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Bars ahead the model predicts. Defines the target. "
                    "Choice is consequential — exposed for the user."
                ),
                min=1,
                max=60,
                step=1,
                unit="bars",
            ),
            InputSpec(
                name="label_type",
                label="Label type",
                control=ControlKind.SELECT,
                required=True,
                description="Regression on return, or up/down classification.",
                options=["regression_return", "binary_updown", "ternary_signal"],
            ),
            InputSpec(
                name="model_family",
                label="Model family",
                control=ControlKind.SELECT,
                required=True,
                description="ML model class.",
                options=["xgboost", "lightgbm", "random_forest", "logistic_l2", "ridge"],
            ),
            InputSpec(
                name="train_pct",
                label="Train split",
                control=ControlKind.NUMBER,
                required=False,
                description="In-sample vs OOS split.",
                min=0.3,
                max=0.9,
                step=0.05,
            ),
            InputSpec(
                name="frequency",
                label="Bar frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Bar size.",
                options=["5m", "15m", "1h", "4h", "1d"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Always true — signal cannot directly route orders.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for OHLCV.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "label_horizon": 5,
            "label_type": "binary_updown",
            "model_family": "lightgbm",
            "train_pct": 0.7,
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
        caching=CachingPolicy(ttl_seconds=1800, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "symbol",
                "predictions",
                "feature_importances",
                "validation_metrics",
                "model_family",
                "data_mode",
            ],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="ms", label="Time"),
            y_axis=AxisSpec(type="numeric", unit="", label="Prediction"),
            panes=[
                PaneGrammar(name="price", series_kind="line", height_pct=50),
                PaneGrammar(name="prediction", series_kind="line", height_pct=30),
                PaneGrammar(name="confidence", series_kind="area", height_pct=20),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="feature", label="Feature", kind="text"),
                ColumnSpec(key="importance", label="Importance", kind="number", format="%.4f"),
                ColumnSpec(key="rank", label="Rank", kind="number", format="%d"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="latest_prediction", label="Latest", kind="big_number"),
                CardSlot(key="latest_confidence", label="Confidence", kind="kpi", unit="%"),
                CardSlot(key="oos_score", label="OOS score", kind="kpi"),
                CardSlot(key="label_horizon", label="Horizon", kind="kpi", unit="bars"),
                CardSlot(key="model_family", label="Model", kind="badge"),
                CardSlot(key="paper_mode", label="Safe", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MLSIG builds the feature matrix from OHLCV at the chosen "
            "frequency by applying each feature_set entry as a "
            "deterministic transform. Labels are constructed at "
            "label_horizon: regression_return = return over the next H "
            "bars; binary_updown = sign of that return; ternary_signal "
            "= {down, flat, up} bucketed by volatility-adjusted "
            "thresholds. The data is split chronologically by train_pct "
            "(no leakage). The chosen model family fits on the train "
            "slice; OOS predictions and validation metrics (AUC for "
            "classification, R² for regression) come from the held-out "
            "slice. Feature importances use tree gain (XGBoost / LightGBM "
            "/ RF) or normalized abs(coef) (linear). The latest_prediction "
            "is the model's view at the most recent bar — surfaced as "
            "research output, never auto-routed to execution."
        ),
        formula_dict={
            "Label": Formula(
                expression=r"y_t = sign(p_{t+H} / p_t - 1)",
                variables={"H": "label_horizon"},
                notes="Variant for regression: y_t = p_{t+H}/p_t - 1 (continuous).",
            ),
            "TrainTestSplit": Formula(
                expression=r"|train| = \lfloor train\_pct \cdot T \rfloor, \; |test| = T - |train|",
                variables={"T": "Total bars after feature alignment"},
                notes="Chronological — first train_pct of bars to train, rest to test.",
            ),
            "OOSScore": Formula(
                expression=r"AUC (classification) \text{ or } R^2 (regression)",
                variables={},
            ),
        },
        field_dict={
            "predictions[]": FieldDef(description="Per-bar OOS prediction time series.", source="computed"),
            "feature_importances[]": FieldDef(description="Per-feature importance with rank.", source="computed"),
            "validation_metrics": FieldDef(description="AUC / R² / accuracy on the OOS slice.", source="computed"),
            "model_family": FieldDef(description="Echo of the chosen model class.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="mlsig_paper_mode_always_true",
                description="ML signals cannot wire directly to live execution.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="mlsig_label_horizon_is_model_assumption",
                description="label_horizon ships as a model_assumption control.",
                inputs={},
                assertions=["input 'label_horizon' has control == model_assumption"],
            ),
            SemanticTest(
                name="mlsig_train_test_split_is_chronological_not_random",
                description="Split is by time, not random shuffle (no peek).",
                inputs={},
                assertions=["test_min_timestamp > train_max_timestamp"],
            ),
            SemanticTest(
                name="mlsig_feature_importance_count_matches_feature_set",
                description="Returned importance list length equals len(feature_set).",
                inputs={},
                assertions=["len(feature_importances) == len(feature_set)"],
            ),
            SemanticTest(
                name="mlsig_predictions_length_matches_test_bars",
                description="Predictions cover the OOS slice exactly.",
                inputs={},
                assertions=["len(predictions) == len(test_slice)"],
            ),
        ],
    )


__all__ = ["mlsig"]
