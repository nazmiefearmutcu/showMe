"""REGM — Market Regime Classifier.

A rule-based composite of trend, volatility, drawdown and the 10Y-2Y curve for
a benchmark. The label is the headline; input_coverage reports how many of the
four components resolved. No macro feature model is run in this build.
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
            "Classify the market regime of a benchmark (default SPY) as a rule-based "
            "composite of trend, volatility, drawdown and the 2s10s curve, and report "
            "how many of those four inputs resolved. No macro feature model is run in "
            "this build."
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
                description="Not wired in this build: no code reads it; the label is always the rule-based composite.",
                options=["business_cycle", "risk_on_off", "inflation_growth"],
            ),
            InputSpec(
                name="features",
                label="Features",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Not wired in this build: no code reads it, and no macro feature series are fetched.",
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
                description="Not applied to the current payload; action=history reads it as an integer bar count, so the 1m-12m options do not apply.",
                options=["1m", "3m", "6m", "12m"],
            ),
            InputSpec(
                name="model_threshold",
                label="Unused threshold (not wired)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Not wired in this build: no code reads this value, so it does not change the regime label.",
                min=0.0,
                max=1.0,
                step=0.05,
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Not wired in this build: the payload reports its own source list and status, not a data mode.",
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
            must_have=["current", "input_coverage", "rows"],
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
                CardSlot(key="input_coverage", label="Input coverage", kind="kpi"),
                CardSlot(key="data_state", label="Data state", kind="badge"),
                CardSlot(key="source_mode", label="Source", kind="badge"),
            ],
        ),
        methodology=(
            "REGM classifies a benchmark (default SPY) from daily closes fetched through "
            "yfinance over the trailing window. Components: the 50-day versus 200-day "
            "moving-average spread (trend); 21-day annualized realized volatility versus "
            "long-run volatility (vol); the close versus its trailing peak (drawdown); and the "
            "10Y minus 2Y Treasury spread in basis points from FRED DGS10 and DGS2 (curve), "
            "keyed when an adapter is configured and keyless otherwise. The regime label is the "
            "rule-based composite of those four components. input_coverage reports how many of "
            "the four resolved (0.25 each); it is not a probability of the label. If the benchmark "
            "cannot be fetched the function returns provider_unavailable with no label and never "
            "substitutes a synthetic series. No statistical model or per-feature attribution is "
            "computed in this build."
        ),
        field_dict={
            "current.regime": FieldDef(description="Headline regime label from the rule-based composite; None when inputs are insufficient.", source="computed"),
            "input_coverage": FieldDef(unit="[0,1]", description="Share of the four classifier components (trend, volatility, drawdown, curve) that resolved. Not a probability of the regime label.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="regm_input_coverage_is_resolved_share",
                description="Asserts input_coverage equals the resolved share of the four components (0.25 each); it is not a probability of the regime label.",
                inputs={},
                assertions=["input_coverage_is_resolved_share_of_four"],
            ),
        ],
    )


__all__ = ["regm"]
