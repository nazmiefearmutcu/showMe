"""PFA — Performance Attribution (Brinson-Hood-Beebower).

Sector-level decomposition of portfolio active return into allocation,
selection and interaction effects. The handler (``portfolio/pfa.py``) computes
on the four sector maps the caller supplies; it does not fetch market data and
does not run a factor regression (that is a different analysis and is not
offered under this code).
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
def pfa() -> FunctionManifest:
    return FunctionManifest(
        code="PFA",
        name="Performance Attribution (Brinson)",
        category=Category.PORTFOLIO,
        intent=(
            "Attribute a portfolio's active return against a benchmark, sector by sector, "
            "into allocation, selection and interaction effects, from the portfolio and "
            "benchmark weights and sector returns the user supplies."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="port_weights",
                label="Portfolio weights",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Sector to portfolio weight, as fractions summing to 1.0 (the pane takes percent). "
                    "Required: the attribution does not infer weights."
                ),
            ),
            InputSpec(
                name="port_returns",
                label="Portfolio sector returns",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Sector to total return, as decimals, for every sector in either weight map. "
                    "A missing return is rejected, never read as 0%."
                ),
            ),
            InputSpec(
                name="bench_weights",
                label="Benchmark weights",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description="Sector to benchmark weight, as fractions summing to 1.0.",
            ),
            InputSpec(
                name="bench_returns",
                label="Benchmark sector returns",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Sector to benchmark total return, as decimals, for every sector in either weight map."
                ),
            ),
        ],
        defaults={},
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "status",
                "rows",
                "totals",
                "summary",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.ATTRIBUTION_BAR,
            x_axis=AxisSpec(type="category", unit="", label="Sector"),
            y_axis=AxisSpec(type="numeric", unit="decimal", label="Effect (fraction of benchmark)"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="sector", label="Sector", kind="tag"),
                ColumnSpec(key="port_weight", label="Port w", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="bench_weight", label="Bench w", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="allocation_effect", label="Allocation", kind="percent", unit="%", format="%.4f"),
                ColumnSpec(key="selection_effect", label="Selection", kind="percent", unit="%", format="%.4f"),
                ColumnSpec(key="interaction_effect", label="Interaction", kind="percent", unit="%", format="%.4f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="active_return", label="Active return", kind="big_number", unit="%"),
                CardSlot(key="allocation", label="Allocation", kind="kpi", unit="%"),
                CardSlot(key="selection", label="Selection", kind="kpi", unit="%"),
                CardSlot(key="interaction", label="Interaction", kind="kpi", unit="%"),
                CardSlot(key="sectors", label="Sectors", kind="kpi"),
            ],
        ),
        methodology=(
            "Brinson-Hood-Beebower attribution over the sectors in either weight map. For each sector: "
            "allocation = (w_p - w_b) * (R_b - R_b_total); selection = w_b * (R_p - R_b); "
            "interaction = (w_p - w_b) * (R_p - R_b). The three effects sum to the active return "
            "(portfolio total minus benchmark total). Inputs are user-supplied; no market data is fetched."
        ),
        formula_dict={
            "Allocation": Formula(
                expression=r"AE_i = (w_{p,i} - w_{b,i})(R_{b,i} - R_{b})",
                variables={"R_b": "Benchmark total return"},
            ),
            "Selection": Formula(
                expression=r"SE_i = w_{b,i}(R_{p,i} - R_{b,i})",
                variables={},
            ),
            "Interaction": Formula(
                expression=r"IE_i = (w_{p,i} - w_{b,i})(R_{p,i} - R_{b,i})",
                variables={},
            ),
        },
        field_dict={
            "allocation_effect": FieldDef(unit="decimal", description="Allocation effect per sector.", source="computed"),
            "selection_effect": FieldDef(unit="decimal", description="Selection effect per sector.", source="computed"),
            "interaction_effect": FieldDef(unit="decimal", description="Interaction effect per sector.", source="computed"),
            "totals.active_return": FieldDef(unit="decimal", description="Portfolio total return minus benchmark total return.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="pfa_effects_sum_to_active_return",
                description="Allocation + selection + interaction equals the active return for fully invested weights.",
                inputs={},
                assertions=["abs(totals.allocation + totals.selection + totals.interaction - totals.active_return) < 1e-9"],
            ),
            SemanticTest(
                name="pfa_missing_sector_return_is_rejected",
                description="A sector present in a weight map without a return on both sides returns input_error, not a 0% return.",
                inputs={},
                assertions=["status == 'input_error' when any sector lacks a return"],
            ),
        ],
    )


__all__ = ["pfa"]
