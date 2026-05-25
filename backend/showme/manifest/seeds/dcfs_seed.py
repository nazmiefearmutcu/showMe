"""DCFS — DCF Sensitivity grid + tornado.

Reuses the DCF intrinsic-value pipeline and runs it across a grid of
discount rate × terminal growth combinations, plus a ±20% input tornado on
each MODEL_ASSUMPTION. The output is a 2D sensitivity grid + a ranked
tornado list so the operator can see which input swings move the result
the most.
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
def dcfs() -> FunctionManifest:
    return FunctionManifest(
        code="DCFS",
        name="DCF Sensitivity",
        category=Category.EQUITIES,
        intent=(
            "Stress the DCF intrinsic value across a discount-rate × terminal-growth grid plus "
            "a ±20% per-input tornado, so the operator can see which assumption matters most."
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
                label="Center discount rate",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Centre of the WACC grid.",
                min=0.04,
                max=0.20,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="terminal_growth",
                label="Center terminal growth",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Centre of the terminal-growth grid.",
                min=0.00,
                max=0.05,
                step=0.0025,
                unit="decimal",
            ),
            InputSpec(
                name="growth_rate",
                label="Stage-1 growth",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Stage-1 FCF growth shared across all grid cells.",
                min=-0.20,
                max=0.40,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="grid_width",
                label="Grid width",
                control=ControlKind.NUMBER,
                required=False,
                description="Cells per axis (3,5,7).",
                options=[3, 5, 7],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode for the FCF history pull.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "discount_rate": 0.09,
            "terminal_growth": 0.025,
            "growth_rate": 0.08,
            "grid_width": 5,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "grid", "tornado", "assumptions"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="numeric", unit="decimal", label="Terminal growth"),
            y_axis=AxisSpec(type="numeric", unit="decimal", label="Discount rate"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="input", label="Input", kind="text"),
                ColumnSpec(key="low_value", label="−20% value", kind="number", format="%.2f"),
                ColumnSpec(key="high_value", label="+20% value", kind="number", format="%.2f"),
                ColumnSpec(key="delta_pct", label="Delta %", kind="percent", format="%.2f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="base_intrinsic_value", label="Base IV / share", kind="big_number", unit="quote_ccy"),
                CardSlot(key="grid_min", label="Grid min", kind="kpi", unit="quote_ccy"),
                CardSlot(key="grid_max", label="Grid max", kind="kpi", unit="quote_ccy"),
                CardSlot(key="most_sensitive_input", label="Top driver", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DCFS reuses the DCF intrinsic-value pipeline. It builds a `grid_width`×`grid_width` "
            "grid of (discount_rate, terminal_growth) pairs centered on the inputs (±width/2 steps "
            "of step). For each cell it runs the full DCF and records intrinsic value per share. "
            "It then runs a tornado: for each MODEL_ASSUMPTION input the function recomputes "
            "intrinsic value at −20% and +20% (other inputs held at base) and ranks inputs by the "
            "spread (most-to-least sensitive). Assumptions are echoed back; the chart grammar is "
            "a HEATMAP keyed on terminal_growth × discount_rate."
        ),
        formula_dict={
            "DCF": Formula(
                expression=r"PV = \sum_{t=1}^{n} \frac{CF_t}{(1+r)^t} + \frac{TV}{(1+r)^n}",
                variables={"CF_t": "Projected FCF year t", "r": "Discount rate", "TV": "Terminal value"},
                notes="Grid cell evaluates this expression at (r, g) corners.",
            ),
            "TornadoDelta": Formula(
                expression=r"\Delta\% = \frac{IV(input \cdot 1.2) - IV(input \cdot 0.8)}{IV_{base}}",
                variables={"IV": "DCF intrinsic value as a function of one input"},
            ),
        },
        field_dict={
            "grid": FieldDef(description="2D grid of {discount_rate, terminal_growth, intrinsic_value} cells.", source="computed"),
            "tornado": FieldDef(description="Per-input tornado ranking by intrinsic-value sensitivity.", source="computed"),
            "base_intrinsic_value": FieldDef(unit="quote_ccy", description="IV at the centre cell.", source="computed"),
            "grid_min": FieldDef(unit="quote_ccy", description="Minimum IV in the grid.", source="computed"),
            "grid_max": FieldDef(unit="quote_ccy", description="Maximum IV in the grid.", source="computed"),
            "most_sensitive_input": FieldDef(description="Top of the tornado ranking.", source="computed"),
            "assumptions": FieldDef(description="Echoed inputs (center rates + grid width).", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dcfs_aapl_5x5_grid_populated",
                description="DCFS for AAPL with grid_width=5 returns a 5x5 grid + tornado rows.",
                inputs={"symbol": "AAPL", "grid_width": 5},
                assertions=[
                    "status_in_ok_set",
                    "grid_length_equals_25",
                    "tornado_non_empty",
                ],
            ),
            SemanticTest(
                name="dcfs_assumptions_visible_in_output",
                description="The output echoes the centre + grid-width inputs so the consumer can audit.",
                inputs={"symbol": "AAPL", "discount_rate": 0.10, "terminal_growth": 0.02, "grid_width": 3},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_discount_rate_equals_input",
                    "assumptions_grid_width_equals_input",
                ],
            ),
            SemanticTest(
                name="dcfs_chart_grammar_is_heatmap",
                description="Grid renders as a heatmap, not a line plot.",
                inputs={},
                assertions=["chart_grammar_kind_is_heatmap"],
            ),
        ],
    )


__all__ = ["dcfs"]
