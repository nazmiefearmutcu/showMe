"""STRS — Stress Test Scenarios.

Run portfolio P&L under hand-set parametric stress scenarios or a custom shock
vector. Bond funds in the GFC 2008 and COVID 2020 windows use their measured
window return. The scenario multiselect and the per-scenario magnitudes are
exposed as MODEL_ASSUMPTION controls — stress tests live or die by their
assumptions.
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
def strs() -> FunctionManifest:
    return FunctionManifest(
        code="STRS",
        name="Stress Test Scenarios",
        category=Category.PORTFOLIO,
        intent=(
            "Apply a set of hand-set parametric stress shocks (by symbol, "
            "sector or asset class) or a custom shock vector to today's "
            "positions, reporting P&L per scenario and the worst case. The "
            "engine does not use return history; the one measured input is "
            "each bond fund's own window return in the GFC 2008 and COVID 2020 "
            "scenarios. The scenario set and shock magnitudes are "
            "model_assumption controls — there is no defensible default."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.OPTION,
            AssetClass.FUTURE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="portfolio_source",
                label="Portfolio source",
                control=ControlKind.SELECT,
                required=True,
                description="PORT (live broker positions) or custom basket.",
                options=["port", "custom"],
            ),
            InputSpec(
                name="positions",
                label="Custom positions",
                control=ControlKind.CONSTRAINT_SET,
                required=False,
                description="When portfolio_source=custom.",
                depends_on=["portfolio_source"],
            ),
            InputSpec(
                name="scenarios",
                label="Scenarios",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Named stress scenarios to run (hand-set shocks; bond funds in "
                    "GFC_2008 and COVID_2020 take their measured window return). "
                    "These keys are the only scenarios the engine runs; custom shocks "
                    "use action=custom. The user must explicitly pick at least one."
                ),
                options=[
                    "GFC_2008",
                    "COVID_2020",
                    "CHINA_2015",
                    "RATE_SHOCK_300BP",
                    "TECH_BUST_2022",
                    "USD_STRENGTH",
                    "OIL_SPIKE",
                    "CRYPTO_WINTER",
                ],
            ),
            InputSpec(
                name="scenario_magnitudes",
                label="Shock magnitudes",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Scale factor applied to every hand-set shock (1.0 = base "
                    "calibration; 2.0 = doubled severity; a position cannot lose "
                    "more than 100%). User owns the choice."
                ),
            ),
            InputSpec(
                name="propagation",
                label="Propagation",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "How shocks are looked up for each position: the first "
                    "match of symbol, then sector, then asset class. This is the "
                    "only method the engine runs."
                ),
                options=["hand_set_lookup"],
            ),
            InputSpec(
                name="horizon_days",
                label="Horizon",
                control=ControlKind.NUMBER,
                required=False,
                description="Days over which the shock unfolds.",
                min=1,
                max=60,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for the price history.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "portfolio_source": "port",
            "propagation": "hand_set_lookup",
            "horizon_days": 5,
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
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "scenarios_run",
                "scenario_impacts",
                "worst_case",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", unit="", label="Scenario"),
            y_axis=AxisSpec(type="numeric", unit="%", label="P&L impact"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="scenario", label="Scenario", kind="tag"),
                ColumnSpec(key="magnitude", label="Severity", kind="number", format="%.1fx"),
                ColumnSpec(key="impact_value", label="P&L Δ", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="impact_pct", label="P&L Δ%", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="largest_loser", label="Worst position", kind="text"),
                ColumnSpec(key="largest_winner", label="Best position", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="worst_case", label="Worst Case", kind="big_number", unit="ccy"),
                CardSlot(key="worst_scenario", label="Worst scenario", kind="badge"),
                CardSlot(key="avg_impact", label="Avg Δ", kind="kpi", unit="%"),
                CardSlot(key="scenarios_count", label="Scenarios", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "STRS applies hand-set parametric shocks to today's positions. Each "
            "scenario holds decimal shocks keyed by symbol, sector or asset class; "
            "a position takes the first match in that order. Treasury and "
            "aggregate bond funds (TLT, IEF, SHY, AGG and similar) take the BOND "
            "row in scenarios without a measured window. In GFC_2008 and "
            "COVID_2020 they take their own measured window return: the price "
            "return of that fund from the window's first to last close, fetched "
            "from price history. If that return cannot be obtained the fund is "
            "left unshocked and reported as unavailable, never estimated. The "
            "shocks are calibrations to each scenario's narrative, not replays of "
            "the named windows. Each shock is multiplied by `scale` and floored at "
            "-100% per position; floored positions are listed in warnings. "
            "Worst_case is the scenario with the largest loss. `scenarios` selects "
            "which engine scenarios run (a key the engine does not run is reported "
            "in warnings, never dropped silently); `scenario_magnitudes` is the scale. "
            "The engine applies a single shock method."
        ),
        formula_dict={
            "ParametricShock": Formula(
                expression=r"\Delta_i = \max(s_{k(i)} \cdot scale,\ -1) \cdot MV_i",
                variables={
                    "s_k": "Hand-set scenario shock for the matched symbol, sector or asset class",
                    "k(i)": "First match of symbol, sector, then asset-class bucket",
                    "MV": "Market value",
                },
            ),
            "WorstCase": Formula(
                expression=r"WC = \min_s \Delta_s",
                variables={"Δ_s": "P&L impact under scenario s"},
            ),
        },
        field_dict={
            "scenarios_run[]": FieldDef(unit="", description="Echo of scenario names actually executed.", source="input"),
            "scenario_impacts[]": FieldDef(unit="ccy", description="P&L change per scenario.", source="computed"),
            "worst_case": FieldDef(unit="ccy", description="Largest loss across selected scenarios.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="strs_scenarios_magnitudes_propagation_are_model_assumptions",
                description="Stress assumptions are first-class model_assumption inputs.",
                inputs={},
                assertions=[
                    "input 'scenarios' has control == model_assumption",
                    "input 'scenario_magnitudes' has control == model_assumption",
                    "input 'propagation' has control == model_assumption",
                ],
            ),
            SemanticTest(
                name="strs_worst_case_is_min_of_impacts",
                description="worst_case equals min across scenario_impacts.",
                inputs={},
                assertions=["worst_case == min(scenario_impacts)"],
            ),
            SemanticTest(
                name="strs_no_scenarios_returns_actionable_warning",
                description="Empty scenarios set returns a warning and no rows.",
                inputs={"scenarios": []},
                assertions=["warnings_non_empty", "scenarios_run == []"],
            ),
            SemanticTest(
                name="strs_magnitude_scales_linearly",
                description="Doubling magnitude doubles the impact for the same scenario.",
                inputs={},
                assertions=["impact_at_2x == 2 * impact_at_1x within tolerance"],
            ),
        ],
    )


__all__ = ["strs"]
