"""FXFC — FX Forecasts (covered-interest-parity forward carry).

CIP forward-path forecasts for one FX pair across a tenor ladder, with
model volatility bands (spot · vol · √T) and a deterministic confidence
score. Spot comes from the live tier chain (yfinance → ECB →
Frankfurter keyless); when every tier fails the handler labels the
fallback `reference_model` and warns, and the pane mirrors that instead
of pretending the curve is live. The earlier manifest described a
consensus/bull-bear survey that was never implemented.
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
def fxfc() -> FunctionManifest:
    return FunctionManifest(
        code="FXFC",
        name="FX Forecasts",
        category=Category.FX,
        intent=(
            "Covered-interest-parity forward path for an FX pair across the "
            "tenor ladder, with model volatility bands (spot·vol·√T) and a "
            "deterministic confidence score. The spot tier is labelled "
            "(live_yfinance_quote / live_ecb_reference / live_official / "
            "manual_input); the reference_model fallback carries a warning "
            "and never masquerades as a live quote."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="pair",
                label="Pair",
                control=ControlKind.SELECT,
                required=True,
                description="FX pair in BASEQUOTE form (e.g. EURUSD, USDJPY).",
                options=[
                    "EURUSD",
                    "USDJPY",
                    "GBPUSD",
                    "AUDUSD",
                    "USDCAD",
                    "EURGBP",
                ],
            ),
            InputSpec(
                name="tenors",
                label="Tenors",
                control=ControlKind.HORIZON,
                required=False,
                description="Horizon ladder; defaults to 1M,3M,6M,12M.",
                options=["1W", "1M", "3M", "6M", "12M", "1Y"],
            ),
            InputSpec(
                name="vol_annualized",
                label="Vol (annualized)",
                control=ControlKind.NUMBER,
                required=False,
                description="Annualized vol for the model bands; defaults to 0.085.",
                min=0.0,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="r_base",
                label="Base rate",
                control=ControlKind.NUMBER,
                required=False,
                description="Base-currency policy rate override (decimal annual).",
                step=0.001,
                unit="decimal",
            ),
            InputSpec(
                name="r_quote",
                label="Quote rate",
                control=ControlKind.NUMBER,
                required=False,
                description="Quote-currency policy rate override (decimal annual).",
                step=0.001,
                unit="decimal",
            ),
            InputSpec(
                name="spot",
                label="Spot override",
                control=ControlKind.NUMBER,
                required=False,
                description="Manual spot; bypasses the provider chain and is labelled manual_input.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred spot mode; the chain may downgrade and says so.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                ],
            ),
        ],
        defaults={
            "pair": "EURUSD",
            "tenors": "1M,3M,6M,12M",
            "vol_annualized": 0.085,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["ecb", "frankfurter", "reference_fx_spot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "pair",
                "base",
                "quote",
                "spot",
                "base_rate",
                "quote_rate",
                "vol_annualized",
                "forecast",
                "source_mode",
            ],
            rows=True,
            series=True,
            cards=False,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TENOR_CURVE,
            x_axis=AxisSpec(type="category", label="Tenor"),
            y_axis=AxisSpec(type="numeric", unit="quote_ccy", label="Forecast"),
            panes=[
                PaneGrammar(name="cip_forward_ladder", series_kind="line", height_pct=100),
            ],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="horizon", label="Horizon", kind="tag"),
                ColumnSpec(key="forecast", label="Forecast", kind="number", format="%.6f"),
                ColumnSpec(key="forward_points", label="F − S", kind="number", format="%.6f"),
                ColumnSpec(key="lower_band", label="Lower band", kind="number", format="%.6f"),
                ColumnSpec(key="upper_band", label="Upper band", kind="number", format="%.6f"),
                ColumnSpec(key="confidence", label="Confidence", kind="percent"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=None,
        methodology=(
            "FXFC uses covered-interest-parity forward carry as the "
            "deterministic forecast path: forecast = spot · (1 + r_quote·T) / "
            "(1 + r_base·T) with rates on an ACT/360 conversion. The lower / "
            "upper bands are spot · annualized_vol · √T, so they are model "
            "bands, not vendor analyst forecasts. Confidence is a "
            "deterministic score that decays with tenor. Missing spot in "
            "every provider tier yields a labelled reference spot plus a "
            "warning — never a silent zero."
        ),
        formula_dict={
            "forecast": Formula(
                expression=r"F = S \cdot \frac{1 + r_{quote} \cdot T}{1 + r_{base} \cdot T}",
                variables={"S": "Spot", "r_quote": "Quote rate", "r_base": "Base rate", "T": "Tenor in years"},
                notes="ACT/360 day-count conversion applied to T.",
            ),
            "band": Formula(
                expression=r"band = S \cdot \sigma_{ann} \cdot \sqrt{T}",
                variables={"sigma_ann": "Annualized vol"},
                notes="Model band around the CIP forward, not a market quote.",
            ),
        },
        field_dict={
            "pair": FieldDef(description="FX pair (BASEQUOTE).", source="input"),
            "spot": FieldDef(unit="quote_ccy", description="Spot quote used for the path.", source="provider"),
            "forecast": FieldDef(unit="quote_ccy", description="CIP forward-implied level per tenor.", source="computed"),
            "forward_points": FieldDef(unit="quote_ccy", description="Forecast − spot per tenor.", source="computed"),
            "lower_band": FieldDef(unit="quote_ccy", description="Forecast − spot·vol·√T.", source="computed"),
            "upper_band": FieldDef(unit="quote_ccy", description="Forecast + spot·vol·√T.", source="computed"),
            "confidence": FieldDef(unit="percent", description="Deterministic model confidence; lower for longer tenors.", source="computed"),
            "source_mode": FieldDef(description="Spot tier label (live_* / manual_input / reference_model).", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fxfc_reference_model_is_labelled",
                description="With no live spot available the rows carry source_mode=reference_model and the envelope warns.",
                inputs={"pair": "EURUSD", "_mock": "spot_unavailable"},
                assertions=["reference_model_labelled", "warning_present"],
            ),
            SemanticTest(
                name="fxfc_forward_matches_cip",
                description="forecast = spot·(1+r_quote·T)/(1+r_base·T) for every tenor.",
                inputs={"pair": "EURUSD", "spot": 1.1, "r_base": 0.03, "r_quote": 0.05},
                assertions=["forecast_equals_cip"],
            ),
            SemanticTest(
                name="fxfc_bands_straddle_forecast",
                description="lower_band ≤ forecast ≤ upper_band on every horizon.",
                inputs={"pair": "EURUSD"},
                assertions=["lower_le_forecast", "upper_ge_forecast"],
            ),
        ],
    )


__all__ = ["fxfc"]
