"""STRS — Stress Test Scenarios.

Run portfolio P&L under a curated set of historical or custom scenarios
(2008 Lehman, 2020 COVID, 1987 crash, Russia 1998, custom). The scenario
multiselect and the per-scenario factor magnitudes are exposed as
MODEL_ASSUMPTION controls — stress tests live or die by their assumptions.
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
            "Replay the portfolio through a curated set of historical "
            "stress scenarios (1987, 1998, 2008, 2020-COVID) or a custom "
            "factor-shock vector, reporting worst-case P&L per scenario. "
            "The scenario set and shock magnitudes are model_assumption "
            "controls — there is no defensible default."
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
                    "Curated historical stress windows plus custom shocks. "
                    "The user must explicitly pick at least one."
                ),
                options=[
                    "black_monday_1987",
                    "asia_1997",
                    "russia_ltcm_1998",
                    "dotcom_2000",
                    "lehman_2008",
                    "eurozone_2011",
                    "covid_2020",
                    "rates_2022",
                    "custom",
                ],
            ),
            InputSpec(
                name="scenario_magnitudes",
                label="Shock magnitudes",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "Per-scenario scale factor (1.0 = historical replay; "
                    "2.0 = doubled severity). User owns the choice."
                ),
            ),
            InputSpec(
                name="propagation",
                label="Propagation",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description=(
                    "How shocks propagate across the portfolio: factor "
                    "model (Fama-French-style), historical replay, or "
                    "asset-class mapping."
                ),
                options=["factor_model", "historical_replay", "asset_class_map"],
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
            "propagation": "historical_replay",
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
            "STRS replays each selected scenario against the current "
            "portfolio. Historical replay extracts the actual realized "
            "asset-class returns from the named window (e.g. 2008-09-15 to "
            "2008-12-15 for Lehman) and applies them to today's positions, "
            "scaled by the per-scenario magnitude. Factor model decomposes "
            "current positions into factor exposures (equity-beta, "
            "credit-spread, rates-duration, USD-DXY) and shocks those "
            "factors by the scenario's realized factor moves. "
            "asset_class_map applies one shock per asset class (e.g. SPX "
            "-30%, credit -15%, gold +10%). All three propagation methods "
            "are exposed so the user can compare. Worst_case is the "
            "scenario with the largest realized loss; the manifest forces "
            "the user to pick scenarios + magnitudes — no silent defaults."
        ),
        formula_dict={
            "HistoricalReplay": Formula(
                expression=r"\Delta = w^\top r_{scenario\_window} \cdot MV \cdot magnitude",
                variables={"r": "Realized returns during scenario", "MV": "Market value"},
            ),
            "FactorShock": Formula(
                expression=r"\Delta = B w^\top f_{scenario} \cdot MV \cdot magnitude",
                variables={"B": "Factor exposure matrix", "f": "Scenario factor shocks"},
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
