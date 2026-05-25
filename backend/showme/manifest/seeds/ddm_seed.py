"""DDM — Gordon Growth Dividend Discount Model.

Classic single-stage Gordon model: P_0 = D_1 / (r − g). Inputs are
editable MODEL_ASSUMPTIONs for discount rate r and dividend growth g;
the next-period dividend D_1 is seeded from yfinance's trailing dividend
× (1 + g). The handler echoes the assumptions so the consumer can audit
which P_0 they are reading.
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
def ddm() -> FunctionManifest:
    return FunctionManifest(
        code="DDM",
        name="Dividend Discount Model",
        category=Category.EQUITIES,
        intent=(
            "Compute Gordon-growth intrinsic value per share from next-period dividend D_1, "
            "discount rate r, and growth rate g."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Dividend-paying equity ticker.",
            ),
            InputSpec(
                name="discount_rate",
                label="Discount rate (r)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Cost of equity used to discount the dividend stream.",
                min=0.01,
                max=0.30,
                step=0.0025,
                unit="decimal",
            ),
            InputSpec(
                name="growth_rate",
                label="Dividend growth (g)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Annual dividend growth rate; must be < discount_rate.",
                min=0.00,
                max=0.15,
                step=0.0025,
                unit="decimal",
            ),
            InputSpec(
                name="dividend_seed",
                label="D_1 override",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Override D_1; default uses last trailing dividend × (1+g).",
                min=0.0,
                step=0.01,
                unit="quote_ccy",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode for the trailing-dividend seed.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "discount_rate": 0.09,
            "growth_rate": 0.04,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "symbol",
                "status",
                "intrinsic_value_per_share",
                "next_dividend",
                "assumptions",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="component", label="Component", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="formula", label="Formula", kind="text"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="intrinsic_value_per_share", label="P_0", kind="big_number", unit="quote_ccy"),
                CardSlot(key="next_dividend", label="D_1", kind="kpi", unit="quote_ccy"),
                CardSlot(key="trailing_dividend", label="D_0", kind="kpi", unit="quote_ccy"),
                CardSlot(key="upside_pct", label="Upside vs price", kind="trend_pill", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DDM applies the Gordon growth formula P_0 = D_1 / (r − g). D_1 is computed as D_0 × "
            "(1 + g) using the trailing 12-month dividend from yfinance, unless dividend_seed is "
            "set directly. The handler warns when (r − g) is non-positive (model diverges) and "
            "returns assumptions in the payload so the consumer can audit which value they read. "
            "Upside vs the live price is reported when a price snapshot is available; otherwise "
            "the field is null and a warning is added."
        ),
        formula_dict={
            "GordonDDM": Formula(
                expression=r"P_0 = \frac{D_1}{r - g}",
                variables={
                    "D_1": "Next-period dividend (D_0 × (1+g) unless overridden)",
                    "r": "Discount rate / cost of equity",
                    "g": "Dividend growth rate; must be < r",
                },
                notes="Gordon growth single-stage DDM.",
            ),
            "NextDividend": Formula(
                expression=r"D_1 = D_0 \cdot (1 + g)",
                variables={"D_0": "Trailing 12-month dividend per share"},
            ),
        },
        field_dict={
            "intrinsic_value_per_share": FieldDef(unit="quote_ccy", description="Gordon DDM P_0.", source="computed"),
            "next_dividend": FieldDef(unit="quote_ccy", description="D_1 used in the formula.", source="computed"),
            "trailing_dividend": FieldDef(unit="quote_ccy", description="D_0 from yfinance trailing 12m.", source="provider"),
            "upside_pct": FieldDef(unit="%", description="(P_0 − price) / price; null when price unavailable.", source="computed"),
            "assumptions": FieldDef(description="Echoed inputs (discount_rate, growth_rate, dividend_seed).", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ddm_msft_default_returns_finite_p0",
                description="DDM for MSFT with default assumptions returns a finite intrinsic value > 0.",
                inputs={"symbol": "MSFT"},
                assertions=[
                    "status_in_ok_set",
                    "intrinsic_value_per_share_is_positive_number",
                    "next_dividend_is_positive_number",
                ],
            ),
            SemanticTest(
                name="ddm_assumptions_visible_in_output",
                description="The output echoes r, g, and dividend_seed so the consumer can audit.",
                inputs={"symbol": "MSFT", "discount_rate": 0.10, "growth_rate": 0.04},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_discount_rate_equals_input",
                    "assumptions_growth_rate_equals_input",
                ],
            ),
            SemanticTest(
                name="ddm_growth_ge_discount_warns_no_divide_by_zero",
                description="When growth_rate >= discount_rate the function warns rather than divide by zero.",
                inputs={"symbol": "MSFT", "discount_rate": 0.04, "growth_rate": 0.05},
                assertions=[
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["ddm"]
