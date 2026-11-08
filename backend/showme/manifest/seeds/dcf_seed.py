"""DCF — Two-stage Discounted Cash Flow valuation.

Discount future free cash flows + a terminal value at the user's WACC.
Inputs are editable MODEL_ASSUMPTION controls (discount rate, growth rate,
terminal growth, projection years). Cash-flow history seeds the projection
from yfinance / SEC EDGAR FA data.
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
def dcf() -> FunctionManifest:
    return FunctionManifest(
        code="DCF",
        name="Discounted Cash Flow",
        category=Category.EQUITIES,
        intent=(
            "Compute a two-stage DCF intrinsic value per share: project free cash flow forward "
            "at the input growth rate, discount each year at the discount rate, add a terminal "
            "value at stable growth."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="wacc",
                label="Discount rate (WACC)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Discount rate applied to each future FCFE. Empty uses the cost of equity (CAPM) from the WACC model, since FCFE is levered; a constant is never substituted and WACC is not used to discount FCFE.",
                min=0.01,
                max=0.30,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="growth_high",
                label="Stage-1 growth",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Annual FCF growth during the projection window.",
                min=-0.20,
                max=0.40,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="growth_terminal",
                label="Terminal growth",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Stable growth used in the perpetual terminal value (must be < discount_rate).",
                min=0.00,
                max=0.05,
                step=0.0025,
                unit="decimal",
            ),
            InputSpec(
                name="years",
                label="Projection years",
                control=ControlKind.NUMBER,
                required=False,
                description="Length of the explicit-projection stage.",
                min=3,
                max=15,
                step=1,
                unit="years",
            ),
        ],
        defaults={
            "growth_high": 0.08,
            "growth_terminal": 0.025,
            "years": 10,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "status",
                "wacc",
                "starting_fcfe",
                "fair_value_per_share",
                "equity_value",
                "rows",
                "bridge",
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
                ColumnSpec(key="year", label="Year", kind="number"),
                ColumnSpec(key="fcfe", label="FCFE", kind="number", unit="quote_ccy", format="%.0f"),
                ColumnSpec(key="discount_factor", label="DF", kind="number", format="%.4f"),
                ColumnSpec(key="pv", label="PV", kind="number", unit="quote_ccy", format="%.0f"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="fair_value_per_share", label="Fair value / share", kind="big_number", unit="quote_ccy"),
                CardSlot(key="equity_value", label="Equity value", kind="kpi", unit="quote_ccy"),
                CardSlot(key="terminal_value", label="Terminal", kind="kpi", unit="quote_ccy"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Two-stage FCFE DCF. Starting FCFE is the caller's fcfe (a labelled manual override) or "
            "the yfinance freeCashflow provider value. FCFE is projected at growth_high for years, each "
            "year is discounted at (1+wacc)^t, and the terminal value TV = FCFE_n * (1+growth_terminal) / "
            "(wacc - growth_terminal) is discounted to year 0. Equity value = PV(explicit) + PV(terminal); "
            "fair value per share = equity value / shares outstanding (caller override or provider). "
            "wacc is the caller value or the WACC model and is never a constant. A wacc at or below "
            "growth_terminal returns a model error."
        ),
            formula_dict={
            "DCF": Formula(
                expression=r"PV = \sum_{t=1}^{n} \frac{CF_t}{(1+r)^t} + \frac{TV}{(1+r)^n}",
                variables={
                    "CF_t": "Projected free cash flow in year t",
                    "r": "Discount rate (WACC)",
                    "n": "Projection horizon (projection_years)",
                    "TV": "Terminal value at year n",
                },
                notes="Two-stage DCF with explicit projection + perpetual terminal value.",
            ),
            "TerminalValue": Formula(
                expression=r"TV = \frac{CF_{n+1}}{r - g}",
                variables={
                    "g": "Terminal growth rate (terminal_growth, must be < r)",
                    "r": "Discount rate (WACC)",
                },
                notes="Gordon growth model; requires r > g for convergence.",
            ),
            "IntrinsicValue": Formula(
                expression=r"P_0 = \frac{Equity\_Value}{Shares\_Out}",
                variables={
                    "Equity_Value": "PV of explicit FCFE + PV of terminal value (FCFE is already after debt)",
                    "Shares_Out": "Shares outstanding (caller override or provider)",
                },
            ),
        },
        field_dict={
            "fair_value_per_share": FieldDef(unit="quote_ccy", description="Equity value divided by shares outstanding.", source="computed"),
            "equity_value": FieldDef(unit="quote_ccy", description="Sum of discounted projected FCFE + discounted terminal value.", source="computed"),
            "terminal_value": FieldDef(unit="quote_ccy", description="Undiscounted terminal value at year n.", source="computed"),
            "rows": FieldDef(description="Per-year FCFE / discount factor / present value rows.", source="computed"),
            "bridge": FieldDef(description="PV explicit + PV terminal = equity value, then fair value per share.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dcf_aapl_default_assumptions_returns_finite_intrinsic",
                description="DCF for AAPL with default assumptions returns a finite fair_value_per_share > 0.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "fair_value_per_share_is_positive_number",
                    "rows_length_equals_years",
                ],
            ),
            SemanticTest(
                name="dcf_assumptions_visible_in_output",
                description="The output echoes wacc, growth_high and growth_terminal in assumptions so the consumer can audit.",
                inputs={"symbol": "AAPL", "wacc": 0.10, "growth_high": 0.05, "growth_terminal": 0.02},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_wacc_equals_input",
                    "assumptions_growth_high_equals_input",
                ],
            ),
            SemanticTest(
                name="dcf_terminal_growth_ge_discount_warns_or_errors",
                description="When growth_terminal >= wacc the function warns (Gordon model diverges).",
                inputs={"symbol": "AAPL", "wacc": 0.04, "growth_terminal": 0.05},
                assertions=[
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["dcf"]
