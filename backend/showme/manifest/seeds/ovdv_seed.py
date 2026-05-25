"""OVDV — OTC FX Volatility Surface.

FX analogue of IVOL: tenor (1W/1M/3M/6M/1Y...) × delta bucket
(10P/25P/ATM/25C/10C) implied-vol surface for a chosen currency pair.
Inputs are quoted via the standard OTC FX vol triplet (ATM, 25Δ
risk-reversal, 25Δ butterfly) so the surface model assumptions are
explicit.
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
def ovdv() -> FunctionManifest:
    return FunctionManifest(
        code="OVDV",
        name="FX Option Volatility Surface",
        category=Category.FX,
        intent=(
            "Render the OTC FX implied-volatility surface across standard "
            "tenors and delta buckets for a currency pair, with the ATM, "
            "25-delta risk-reversal, and 25-delta butterfly inputs visible."
        ),
        asset_classes=[AssetClass.FX, AssetClass.OPTION],
        inputs=[
            InputSpec(
                name="pair",
                label="Pair",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="FX pair, e.g. EURUSD, USDJPY, GBPUSD.",
            ),
            InputSpec(
                name="tenors",
                label="Tenors",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Standard OTC FX expiry buckets.",
                options=["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y"],
            ),
            InputSpec(
                name="delta_buckets",
                label="Delta Buckets",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Delta-quoted strike points across the smile.",
                options=["10P", "25P", "ATM", "25C", "10C"],
            ),
            InputSpec(
                name="atm_vol",
                label="ATM Vol",
                control=ControlKind.NUMBER,
                required=True,
                description="ATM implied vol (decimal, e.g. 0.085 = 8.5%).",
                min=0.0,
                max=2.0,
                step=0.0005,
                unit="vol",
            ),
            InputSpec(
                name="risk_reversal_25d",
                label="25Δ RR",
                control=ControlKind.NUMBER,
                required=True,
                description="25-delta risk reversal (decimal vol pts).",
                min=-0.10,
                max=0.10,
                step=0.0001,
                unit="vol",
            ),
            InputSpec(
                name="butterfly_25d",
                label="25Δ BF",
                control=ControlKind.NUMBER,
                required=True,
                description="25-delta butterfly (decimal vol pts).",
                min=0.0,
                max=0.10,
                step=0.0001,
                unit="vol",
            ),
            InputSpec(
                name="vol_source",
                label="Vol Source",
                control=ControlKind.SELECT,
                required=True,
                description="Where the vol triplet comes from.",
                options=["user_inputs", "reference_model", "vendor_otc"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for the vol triplet.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "pair": "EURUSD",
            "tenors": ["1W", "1M", "3M", "6M", "1Y"],
            "delta_buckets": ["10P", "25P", "ATM", "25C", "10C"],
            "atm_vol": 0.085,
            "risk_reversal_25d": 0.002,
            "butterfly_25d": 0.0015,
            "vol_source": "user_inputs",
            "provider_mode": DataMode.MODELED.value,
        },
        provider_chain=ProviderChain(
            primary="fx_vol_otc",
            fallbacks=["reference_model", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(
            ttl_seconds=120,
            scope="per_input",
            persist=False,
        ),
        output_contract=OutputContract(
            must_have=["pair", "as_of", "surface", "vol_source", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.SURFACE,
            x_axis=AxisSpec(type="category", unit="delta", label="Delta bucket"),
            y_axis=AxisSpec(type="category", unit="tenor", label="Tenor"),
            panes=[
                PaneGrammar(name="vol_surface", series_kind="area", height_pct=70),
                PaneGrammar(name="atm_term", series_kind="line", height_pct=30),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="tenor", label="Tenor", kind="text"),
                ColumnSpec(key="delta", label="Δ Bucket", kind="tag"),
                ColumnSpec(key="vol", label="Vol", kind="percent", format="%.4f"),
                ColumnSpec(key="vol_decimal", label="Vol (dec.)", kind="number", format="%.6f"),
                ColumnSpec(key="tenor_years", label="Years", kind="number", format="%.4f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="pair", label="Pair", kind="badge"),
                CardSlot(key="atm_vol_pct", label="ATM Vol", kind="big_number", unit="%"),
                CardSlot(key="risk_reversal_25d_pct", label="25Δ RR", kind="kpi", unit="%"),
                CardSlot(key="butterfly_25d_pct", label="25Δ BF", kind="kpi", unit="%"),
                CardSlot(key="vol_source", label="Source", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "OVDV builds an OTC FX volatility surface from the standard "
            "tenor × delta-bucket grid. The ATM vol anchors each tenor, "
            "shifted by a small term-structure step. Per-delta wings come "
            "from the 25-delta risk-reversal (RR) and 25-delta butterfly "
            "(BF): 25P uses BF − RR/2, 25C uses BF + RR/2; 10P/10C add "
            "extra smile curvature. When no live OTC FX vol vendor is "
            "configured the surface is labelled reference_model so the user "
            "can never mistake it for vendor-quoted data. vol_source is "
            "exposed on the card schema to keep the model assumptions "
            "first-class."
        ),
        formula_dict={
            "wing_25_put": Formula(
                expression=r"\sigma_{25P} = \sigma_{ATM} + BF_{25} - \tfrac{1}{2} RR_{25}",
                variables={
                    "sigma_ATM": "ATM vol at the tenor",
                    "BF_25": "25-delta butterfly",
                    "RR_25": "25-delta risk reversal",
                },
            ),
            "wing_25_call": Formula(
                expression=r"\sigma_{25C} = \sigma_{ATM} + BF_{25} + \tfrac{1}{2} RR_{25}",
                variables={},
            ),
            "term_step": Formula(
                expression=r"\sigma_{ATM}(t_i) = \sigma_{ATM}(t_0) + i \cdot \Delta_{term}",
                variables={"Delta_term": "Per-tenor term-structure step (calibration)"},
                notes="Reference-model term slope only; vendor mode replaces with the quoted ATM curve.",
            ),
        },
        field_dict={
            "surface[].tenor": FieldDef(description="Option expiry bucket.", source="user_inputs|vendor"),
            "surface[].delta": FieldDef(description="FX delta bucket (10P/25P/ATM/25C/10C).", source="convention"),
            "surface[].vol": FieldDef(unit="%", description="Implied volatility in percent.", source="derived"),
            "surface[].vol_decimal": FieldDef(unit="decimal", description="Implied volatility as a decimal.", source="derived"),
            "surface[].tenor_years": FieldDef(unit="years", description="Tenor expressed in years.", source="derived"),
            "atm_vol_pct": FieldDef(unit="%", description="Input ATM vol echoed back as percent.", source="input"),
            "risk_reversal_25d_pct": FieldDef(unit="%", description="Input 25Δ RR echoed back as percent.", source="input"),
            "butterfly_25d_pct": FieldDef(unit="%", description="Input 25Δ BF echoed back as percent.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ovdv_surface_axes_are_tenor_and_delta",
                description=(
                    "OVDV renders a tenor×delta vol surface; every cell carries a finite "
                    "implied-vol value."
                ),
                inputs={"pair": "EURUSD", "tenors": ["1W", "1M", "3M", "6M", "1Y"]},
                assertions=[
                    "y_axis_is_tenor",
                    "x_axis_is_delta",
                    "every_cell_has_finite_vol",
                ],
            ),
            SemanticTest(
                name="ovdv_inputs_visible_on_card",
                description=(
                    "Model assumptions are visible — ATM, RR, BF, and vol_source are "
                    "exposed on the card schema and echoed in the payload."
                ),
                inputs={
                    "pair": "EURUSD",
                    "atm_vol": 0.085,
                    "risk_reversal_25d": 0.002,
                    "butterfly_25d": 0.0015,
                    "vol_source": "reference_model",
                },
                assertions=[
                    "atm_vol_pct_card_present",
                    "risk_reversal_25d_pct_card_present",
                    "butterfly_25d_pct_card_present",
                    "vol_source_card_present",
                ],
            ),
            SemanticTest(
                name="ovdv_reference_surface_labels_source_mode",
                description=(
                    "Reference-model surface is labelled source_mode in every row so it "
                    "can never be confused with vendor-quoted vols."
                ),
                inputs={"pair": "EURUSD", "vol_source": "reference_model"},
                assertions=["every_surface_row_has_source_mode"],
            ),
        ],
    )


__all__ = ["ovdv"]
