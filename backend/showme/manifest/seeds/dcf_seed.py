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
                name="discount_rate",
                label="Discount rate (WACC)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Cost of capital used to discount each future cash flow.",
                min=0.01,
                max=0.30,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="growth_rate",
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
                name="terminal_growth",
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
                name="projection_years",
                label="Projection years",
                control=ControlKind.NUMBER,
                required=False,
                description="Length of the explicit-projection stage.",
                min=3,
                max=15,
                step=1,
                unit="years",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode for the FCF history pull.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "discount_rate": 0.09,
            "growth_rate": 0.08,
            "terminal_growth": 0.025,
            "projection_years": 10,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
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
                "symbol",
                "status",
                "intrinsic_value_per_share",
                "enterprise_value",
                "projection",
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
                ColumnSpec(key="fcf", label="FCF", kind="number", unit="quote_ccy", format="%.0f"),
                ColumnSpec(key="discount_factor", label="DF", kind="number", format="%.4f"),
                ColumnSpec(key="present_value", label="PV", kind="number", unit="quote_ccy", format="%.0f"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="intrinsic_value_per_share", label="Intrinsic / share", kind="big_number", unit="quote_ccy"),
                CardSlot(key="enterprise_value", label="EV", kind="kpi", unit="quote_ccy"),
                CardSlot(key="terminal_value", label="Terminal", kind="kpi", unit="quote_ccy"),
                CardSlot(key="upside_pct", label="Upside vs price", kind="trend_pill", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DCF takes the most-recent free cash flow (CFO − |Capex|) from the FA service and "
            "projects it forward at `growth_rate` for `projection_years`. Each year's FCF is "
            "discounted at (1+discount_rate)^t. The terminal value uses the Gordon growth model "
            "TV = FCF_{n+1} / (discount_rate − terminal_growth) and is discounted to year 0. "
            "Enterprise value is the sum of PVs + PV(terminal); intrinsic value per share = "
            "(EV − net debt) / shares outstanding. The handler echoes the assumptions dict so the "
            "consumer can audit which model produced the number, and warns when terminal_growth "
            "is not strictly less than discount_rate."
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
                expression=r"P_0 = \frac{EV - Net\_Debt}{Shares\_Out}",
                variables={"EV": "Enterprise value (sum of PVs)", "Net_Debt": "Total debt − cash"},
            ),
        },
        field_dict={
            "intrinsic_value_per_share": FieldDef(unit="quote_ccy", description="DCF intrinsic value divided by shares outstanding.", source="computed"),
            "enterprise_value": FieldDef(unit="quote_ccy", description="Sum of discounted projected FCFs + discounted terminal value.", source="computed"),
            "terminal_value": FieldDef(unit="quote_ccy", description="Undiscounted terminal value at year n.", source="computed"),
            "projection": FieldDef(description="Per-year FCF / discount factor / present value rows.", source="computed"),
            "assumptions": FieldDef(description="Echoed inputs (discount_rate, growth_rate, terminal_growth, projection_years).", source="input"),
            "upside_pct": FieldDef(unit="%", description="(intrinsic − price) / price.", source="computed"),
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
                description="DCF for AAPL with default assumptions returns a finite intrinsic_value_per_share > 0.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "intrinsic_value_per_share_is_positive_number",
                    "projection_length_equals_projection_years",
                ],
            ),
            SemanticTest(
                name="dcf_assumptions_visible_in_output",
                description="The output echoes the discount/growth/terminal assumptions so the consumer can audit.",
                inputs={"symbol": "AAPL", "discount_rate": 0.10, "growth_rate": 0.05, "terminal_growth": 0.02},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_discount_rate_equals_input",
                    "assumptions_growth_rate_equals_input",
                ],
            ),
            SemanticTest(
                name="dcf_terminal_growth_ge_discount_warns_or_errors",
                description="When terminal_growth >= discount_rate the function warns (Gordon model diverges).",
                inputs={"symbol": "AAPL", "discount_rate": 0.04, "terminal_growth": 0.05},
                assertions=[
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["dcf"]
