"""BTUNE — Backtest parameter tuning.

Grid / random search over a user-defined parameter grid. Outputs the
top-N parameter sets by chosen metric, plus the full parameter-vs-metric
table. Paper-safe.
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
def btune() -> FunctionManifest:
    return FunctionManifest(
        code="BTUNE",
        name="Backtest Parameter Tuning",
        category=Category.PORTFOLIO,
        intent=(
            "Search a user-defined parameter grid for a strategy on a "
            "single symbol; rank the top-N parameter sets by chosen "
            "metric, surfacing overfit warnings when the spread between "
            "in-sample best and OOS validation is too wide. Paper-safe."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="strategy_id",
                label="Strategy",
                control=ControlKind.SELECT,
                required=True,
                description="Strategy spec being tuned.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Single instrument; for matrix runs use BMTX.",
            ),
            InputSpec(
                name="param_grid",
                label="Parameter grid",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Dict of param_name → list_of_values. Cartesian "
                    "product is searched (grid) or sampled (random)."
                ),
            ),
            InputSpec(
                name="search_mode",
                label="Search mode",
                control=ControlKind.SELECT,
                required=True,
                description="Grid (exhaustive) vs random (n_samples).",
                options=["grid", "random"],
            ),
            InputSpec(
                name="n_samples",
                label="Random samples",
                control=ControlKind.NUMBER,
                required=False,
                description="Random-search sample count when search_mode=random.",
                min=10,
                max=5000,
                step=10,
                depends_on=["search_mode"],
            ),
            InputSpec(
                name="metric",
                label="Optimization metric",
                control=ControlKind.SELECT,
                required=True,
                description="Metric to rank parameter sets by.",
                options=["sharpe", "cagr", "calmar", "sortino", "profit_factor"],
            ),
            InputSpec(
                name="train_pct",
                label="Train split",
                control=ControlKind.NUMBER,
                required=False,
                description="In-sample vs OOS split for overfit detection.",
                min=0.3,
                max=0.9,
                step=0.05,
            ),
            InputSpec(
                name="frequency",
                label="Bar frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Bar size.",
                options=["5m", "15m", "1h", "4h", "1d", "1wk"],
            ),
            InputSpec(
                name="top_n",
                label="Top-N",
                control=ControlKind.NUMBER,
                required=False,
                description="Number of best parameter sets to surface.",
                min=1,
                max=100,
                step=1,
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Always true.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for OHLCV.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "search_mode": "grid",
            "n_samples": 200,
            "metric": "sharpe",
            "train_pct": 0.7,
            "frequency": "1d",
            "top_n": 10,
            "paper_mode": True,
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
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "strategy_id",
                "symbol",
                "best_params",
                "top_n_results",
                "full_results",
                "overfit_warning",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.SCATTER,
            x_axis=AxisSpec(type="numeric", unit="", label="In-sample metric"),
            y_axis=AxisSpec(type="numeric", unit="", label="OOS metric"),
            panes=[],
            overlay_support=True,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="rank", label="Rank", kind="number", format="%d"),
                ColumnSpec(key="params", label="Parameters", kind="text"),
                ColumnSpec(key="metric_in_sample", label="IS metric", kind="number", format="%.3f"),
                ColumnSpec(key="metric_oos", label="OOS metric", kind="number", format="%.3f"),
                ColumnSpec(key="overfit_gap", label="Gap", kind="number", format="%.3f"),
                ColumnSpec(key="sharpe", label="Sharpe", kind="number", format="%.2f"),
                ColumnSpec(key="cagr", label="CAGR", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="max_drawdown", label="Max DD", kind="percent", unit="%", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="best_metric_oos", label="Best OOS", kind="big_number"),
                CardSlot(key="evaluations_count", label="Eval count", kind="kpi"),
                CardSlot(key="overfit_score", label="Overfit score", kind="kpi"),
                CardSlot(key="metric", label="Metric", kind="badge"),
                CardSlot(key="search_mode", label="Search", kind="badge"),
                CardSlot(key="paper_mode", label="Safe", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BTUNE enumerates the parameter grid (Cartesian product for "
            "search_mode=grid, n_samples random draws otherwise). For each "
            "parameter set: split the OHLCV history by train_pct, fit on "
            "the train slice (the strategy may be entirely deterministic, "
            "in which case 'fit' is a no-op), evaluate signals on both "
            "slices, and record metric_in_sample + metric_oos. Best_params "
            "is ranked by metric_oos to discourage overfit selection. "
            "overfit_gap = metric_in_sample − metric_oos; "
            "overfit_warning is raised when the median gap across the "
            "top-N exceeds a domain-specific threshold (e.g. ΔSharpe > 1.0). "
            "Search is fully parallelizable; the handler caps concurrency "
            "to keep the sidecar responsive."
        ),
        formula_dict={
            "GridSize": Formula(
                expression=r"|G| = \prod_k |V_k|",
                variables={"V_k": "Value list for parameter k"},
            ),
            "OverfitGap": Formula(
                expression=r"gap = m_{IS} - m_{OOS}",
                variables={"m_IS": "In-sample metric", "m_OOS": "OOS metric"},
            ),
            "OverfitScore": Formula(
                expression=r"OS = median_{topN}(gap) / std_{topN}(m_{OOS})",
                variables={},
                notes="Higher = more overfit risk.",
            ),
        },
        field_dict={
            "best_params": FieldDef(description="Parameter set with the best OOS metric.", source="computed"),
            "top_n_results[]": FieldDef(description="Top-N ranked by OOS metric.", source="computed"),
            "full_results[]": FieldDef(description="Complete grid eval — large; usually paginated.", source="computed"),
            "overfit_warning": FieldDef(description="True when median IS-OOS gap exceeds threshold.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="btune_paper_mode_always_true",
                description="Tuning is research-only.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="btune_best_params_picked_on_oos_not_in_sample",
                description="best_params is the row with highest metric_oos, not metric_in_sample.",
                inputs={},
                assertions=["best_params row.metric_oos == max(top_n_results.metric_oos)"],
            ),
            SemanticTest(
                name="btune_full_grid_size_equals_product_of_values",
                description="In grid mode, full_results length equals Cartesian product size.",
                inputs={"search_mode": "grid"},
                assertions=["len(full_results) == prod(len(v) for v in param_grid.values())"],
            ),
            SemanticTest(
                name="btune_overfit_warning_when_gap_high",
                description="Large IS-vs-OOS gap raises overfit_warning.",
                inputs={},
                assertions=["overfit_warning == True when median_gap > threshold"],
            ),
        ],
    )


__all__ = ["btune"]
