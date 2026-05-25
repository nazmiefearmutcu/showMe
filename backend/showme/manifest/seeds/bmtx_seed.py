"""BMTX — Backtest Matrix.

Run a single strategy across a universe under multiple walk-forward
windows, producing a (strategy × symbol × window) grid of Sharpe / CAGR /
max drawdown. Paper-safe by definition — backtests never touch live
order routing.
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
def bmtx() -> FunctionManifest:
    return FunctionManifest(
        code="BMTX",
        name="Backtest Matrix",
        category=Category.PORTFOLIO,
        intent=(
            "Run a chosen strategy across a universe under multiple walk-"
            "forward windows, producing a (symbol × window) grid of "
            "Sharpe, CAGR, max drawdown, and hit rate. Result is a "
            "research artifact — paper-safe by construction."
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
                description="Strategy spec to backtest (from STRA store).",
            ),
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Symbols to evaluate.",
            ),
            InputSpec(
                name="walk_forward_windows",
                label="WF windows",
                control=ControlKind.CONSTRAINT_SET,
                required=True,
                description=(
                    "Ordered list of (train_start, train_end, test_start, "
                    "test_end) tuples. Each is one matrix column."
                ),
            ),
            InputSpec(
                name="frequency",
                label="Bar frequency",
                control=ControlKind.SELECT,
                required=True,
                description="Bar size for OHLCV + signal evaluation.",
                options=["1m", "5m", "15m", "1h", "4h", "1d", "1wk"],
            ),
            InputSpec(
                name="initial_equity",
                label="Initial equity",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-cell starting equity for percentage metrics.",
                min=100,
                max=10000000,
                step=100,
                unit="ccy",
            ),
            InputSpec(
                name="commission_bps",
                label="Commission",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-trade commission in basis points.",
                min=0,
                max=100,
                step=0.1,
                unit="bps",
            ),
            InputSpec(
                name="slippage_bps",
                label="Slippage",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-fill slippage in basis points.",
                min=0,
                max=100,
                step=0.1,
                unit="bps",
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Always true here — backtest cannot wire to live.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for OHLCV history.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "frequency": "1d",
            "initial_equity": 100000,
            "commission_bps": 5.0,
            "slippage_bps": 2.0,
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
                "matrix",
                "window_summary",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Window"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="window", label="Window", kind="text"),
                ColumnSpec(key="sharpe", label="Sharpe", kind="number", format="%.2f"),
                ColumnSpec(key="cagr", label="CAGR", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="max_drawdown", label="Max DD", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="hit_rate", label="Hit %", kind="percent", unit="%", format="%.1f"),
                ColumnSpec(key="trades", label="Trades", kind="number", format="%d"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="avg_sharpe", label="Avg Sharpe", kind="big_number"),
                CardSlot(key="best_cell", label="Best", kind="badge"),
                CardSlot(key="worst_cell", label="Worst", kind="badge"),
                CardSlot(key="windows_count", label="Windows", kind="kpi"),
                CardSlot(key="universe_size", label="Symbols", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BMTX iterates every (symbol, window) cell of the matrix. For "
            "each cell: fetch OHLCV at the chosen frequency, run the "
            "strategy_id compute engine on the train slice to fit any "
            "fittable parameters, then evaluate signals on the test "
            "slice. Returns are gross-of-commission-and-slippage; per-"
            "trade costs are deducted at fill time. Equity curve per cell "
            "is reconstructed; sharpe = mean / std × √F (annualized), "
            "cagr = (final/initial)^(1/years) − 1, max_drawdown = max "
            "trough-to-peak loss, hit_rate = #wins/#trades. The window "
            "summary aggregates by window across symbols (mean ± std). "
            "Backtest is strictly research; output cannot wire into live "
            "execution from this surface."
        ),
        formula_dict={
            "Sharpe": Formula(
                expression=r"SR = \bar{r} / \sigma_r \cdot \sqrt{F}",
                variables={"F": "Periods per year"},
            ),
            "CAGR": Formula(
                expression=r"CAGR = (V_T / V_0)^{1/T} - 1",
                variables={"V_T": "Final equity", "T": "Years"},
            ),
            "MaxDrawdown": Formula(
                expression=r"MDD = \min_t (V_t / \max_{s \leq t} V_s - 1)",
                variables={},
            ),
            "HitRate": Formula(
                expression=r"HR = N_{win} / N_{trade}",
                variables={},
            ),
        },
        field_dict={
            "matrix": FieldDef(description="2-D grid keyed by [symbol][window] of metric dicts.", source="computed"),
            "window_summary": FieldDef(description="Per-window aggregate stats across the universe.", source="computed"),
            "strategy_id": FieldDef(description="Echo of the chosen strategy spec id.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="bmtx_paper_mode_always_true",
                description="Backtest surface cannot fire live orders.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="bmtx_matrix_cells_equal_symbols_times_windows",
                description="Matrix has exactly |universe| × |windows| cells.",
                inputs={},
                assertions=["len(matrix) == universe_size * windows_count"],
            ),
            SemanticTest(
                name="bmtx_window_summary_uses_only_test_slices",
                description="Sharpe/CAGR/DD are computed on test slices, never train.",
                inputs={},
                assertions=["metrics computed strictly on test_slice"],
            ),
            SemanticTest(
                name="bmtx_unknown_strategy_returns_actionable_warning",
                description="Missing strategy_id returns a warning without partial data.",
                inputs={"strategy_id": "does_not_exist"},
                assertions=["warnings_non_empty", "matrix_empty_or_absent"],
            ),
        ],
    )


__all__ = ["bmtx"]
