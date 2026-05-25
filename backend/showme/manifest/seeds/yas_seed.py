"""YAS — Yield & Spread Analytics.

Solves for yield-to-maturity, Macaulay/modified duration, and convexity
for a fixed-coupon bond given price + cashflow shape, and exposes a
``spread_vs_benchmark`` overlay against a sovereign curve point. The
Newton solver has a bisection fallback for distressed bonds (|y_period|
> 2.0); convexity normalization is per-period to keep quarterly bonds
honest (D03 fix in the handler).
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
    AlertingSpec,
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
def yas() -> FunctionManifest:
    return FunctionManifest(
        code="YAS",
        name="Yield & Spread Analytics",
        category=Category.BONDS_RATES,
        intent=(
            "Compute yield-to-maturity, duration, and convexity for a fixed-coupon"
            " bond and surface its spread vs a sovereign benchmark so the operator"
            " can read carry, rate sensitivity, and risk premium in one pane."
        ),
        asset_classes=[AssetClass.BOND],
        inputs=[
            InputSpec(
                name="symbol",
                label="Bond",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Bond identifier (CUSIP/ISIN/internal alias).",
            ),
            InputSpec(
                name="face",
                label="Face value",
                control=ControlKind.NUMBER,
                required=True,
                description="Par / face amount used for cashflows.",
                min=1.0,
                max=1_000_000_000.0,
                step=1.0,
                unit="currency",
            ),
            InputSpec(
                name="price",
                label="Clean price",
                control=ControlKind.NUMBER,
                required=True,
                description="Quoted clean price (per 100 face).",
                min=0.01,
                max=1000.0,
                step=0.0001,
            ),
            InputSpec(
                name="coupon",
                label="Annual coupon",
                control=ControlKind.NUMBER,
                required=True,
                description="Annual coupon rate as a decimal (0.045 = 4.5%).",
                min=0.0,
                max=0.5,
                step=0.0001,
            ),
            InputSpec(
                name="frequency",
                label="Coupon frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Coupon payments per year.",
                options=[1, 2, 4, 12],
            ),
            InputSpec(
                name="years_to_maturity",
                label="Years to maturity",
                control=ControlKind.NUMBER,
                required=True,
                description="Remaining years until maturity.",
                min=0.01,
                max=100.0,
                step=0.01,
                unit="years",
            ),
            InputSpec(
                name="benchmark",
                label="Benchmark",
                control=ControlKind.SELECT,
                required=False,
                description="Sovereign curve point to compute spread against.",
                options=["UST2Y", "UST5Y", "UST10Y", "UST30Y", "DBR10Y", "JGB10Y", "GILT10Y"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "face": 100.0,
            "price": 99.75,
            "coupon": 0.045,
            "frequency": 2,
            "years_to_maturity": 10.0,
            "benchmark": "UST10Y",
            "provider_mode": DataMode.MODELED.value,
        },
        provider_chain=ProviderChain(
            primary="fred",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["ytm", "macaulay_duration", "modified_duration", "convexity", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", label="Metric"),
            y_axis=[
                AxisSpec(type="numeric", unit="%", label="Yield"),
                AxisSpec(type="numeric", unit="bp", label="Spread"),
            ],
            panes=[
                PaneGrammar(name="yield_vs_benchmark", series_kind="bar", height_pct=60),
                PaneGrammar(name="spread_bp", series_kind="bar", height_pct=40),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text", width_hint=140),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="unit", label="Unit", kind="tag", width_hint=60),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="ytm", label="YTM", kind="big_number", unit="%"),
                CardSlot(key="modified_duration", label="Mod Dur", kind="kpi", unit="years"),
                CardSlot(key="convexity", label="Convexity", kind="kpi"),
                CardSlot(key="spread_vs_benchmark", label="Spread", kind="kpi", unit="bp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "YAS solves YTM via Newton's method on the bond pricing identity"
            " price = Σ c/(1+y)^k + face/(1+y)^N with c = coupon/frequency and N = years × frequency."
            " A bisection fallback bracketed in [-0.99, 5.0] catches divergence for distressed bonds"
            " (|y_period| > 2.0). Macaulay duration is Σ k·CF_k / price (in per-period units, then"
            " divided by frequency for annualized years); modified duration = Macaulay / (1 + y);"
            " convexity is Σ k(k+1) CF_k / ((1+y)^(k+2) · price · freq²) — the freq² normalization"
            " stops quarterly bonds (freq=4) from drifting (D03 fix in the handler). Spread vs"
            " benchmark = (ytm - benchmark_yield) × 100 bp; benchmark yield is pulled from FRED for"
            " UST tenors and falls back to cached_snapshot otherwise."
        ),
        formula_dict={
            "ytm": Formula(
                expression=r"price = \sum_{k=1}^{N} \frac{c}{(1+y)^k} + \frac{F}{(1+y)^N}",
                variables={"c": "Periodic coupon", "F": "Face value", "y": "Per-period yield"},
                notes="Solved by Newton's method with bisection fallback.",
            ),
            "macaulay_duration": Formula(
                expression=r"D_{mac} = \frac{\sum_{k=1}^{N} k \cdot CF_k / (1+y)^k}{price \cdot freq}",
                variables={"CF_k": "Cashflow at period k", "freq": "Coupons per year"},
            ),
            "modified_duration": Formula(
                expression=r"D_{mod} = \frac{D_{mac}}{1 + y}",
                variables={"y": "Per-period yield"},
            ),
            "convexity": Formula(
                expression=r"C = \frac{\sum_{k=1}^{N} k(k+1) CF_k / (1+y)^{k+2}}{price \cdot freq^2}",
                variables={"freq": "Coupons per year"},
                notes="freq² normalization keeps quarterly (freq=4) bonds honest.",
            ),
            "spread_vs_benchmark": Formula(
                expression=r"spread_{bp} = (y_{bond} - y_{benchmark}) \times 100",
                variables={"y_bond": "Bond YTM (%)", "y_benchmark": "Sovereign benchmark yield (%)"},
            ),
        },
        field_dict={
            "ytm": FieldDef(unit="%", description="Yield to maturity (annualized).", source="computed"),
            "macaulay_duration": FieldDef(unit="years", description="Macaulay duration in years.", source="computed"),
            "modified_duration": FieldDef(unit="years", description="Modified duration (price sensitivity to yield).", source="computed"),
            "convexity": FieldDef(description="Second-order yield sensitivity.", source="computed"),
            "spread_vs_benchmark": FieldDef(unit="bp", description="Bond YTM minus benchmark yield in basis points.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["ytm_above", "ytm_below", "spread_above", "spread_below"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="yas_par_bond_yields_equal_coupon",
                description="A bond priced at par should have YTM equal to its coupon rate.",
                inputs={"price": 100.0, "coupon": 0.04, "frequency": 2, "years_to_maturity": 10},
                assertions=["abs(ytm - coupon_pct) < 1e-4"],
            ),
            SemanticTest(
                name="yas_distressed_bond_bisection_fallback",
                description="A deeply distressed bond (|y_period| > 2.0) routes through the bisection fallback rather than Newton blow-up.",
                inputs={"price": 30.0, "coupon": 0.04, "frequency": 2, "years_to_maturity": 5},
                assertions=[
                    "ytm_is_finite",
                    "ytm_within_reasonable_distressed_range",
                ],
            ),
            SemanticTest(
                name="yas_convexity_freq_squared_normalization",
                description=(
                    "A 30Y 4% bond with quarterly (freq=4) coupons must report convexity ≈ 200, not"
                    " ≈ 700 (the freq² normalization bug fixed in D03)."
                ),
                inputs={"price": 100.0, "coupon": 0.04, "frequency": 4, "years_to_maturity": 30},
                assertions=["convexity_within_150_and_250"],
            ),
            SemanticTest(
                name="yas_spread_vs_benchmark_in_bp",
                description="Spread is computed as (ytm - benchmark_yield) × 100 and surfaced as bp.",
                inputs={"benchmark": "UST10Y"},
                assertions=["spread_unit_is_bp", "spread_sign_matches_ytm_minus_benchmark"],
            ),
        ],
    )


__all__ = ["yas"]
