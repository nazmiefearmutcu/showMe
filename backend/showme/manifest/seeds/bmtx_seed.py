"""BMTX — Backtest Matrix.

Run each selected registered strategy across a symbol universe on live daily
OHLCV history, producing a (strategy × symbol) grid of in-sample Sharpe, total
return and max drawdown, plus a final-slice holdout score. Paper-safe by
definition — backtests never touch live order routing.
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
            "Run each selected strategy across a universe on live daily "
            "OHLCV history, producing a (strategy × symbol) grid of Sharpe, "
            "total return, max drawdown and trades, with a final-slice "
            "holdout score. The ranking is in-sample. Result is a research "
            "artifact — paper-safe by construction."
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
                name="universe",
                label="Universe",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Symbols to evaluate.",
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
        ],
        # paper_mode is not a control: the handler never reads it, and
        # backtests cannot reach live routing. It stays as a default invariant.
        # provider_mode is not a control either: OHLCV always comes from the
        # yfinance source, which the result's sources state.
        defaults={
            "initial_equity": 100000,
            "commission_bps": 5.0,
            "slippage_bps": 2.0,
            "paper_mode": True,
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
                "status",
                "strategies",
                "cells",
                "surface",
                "best_per_symbol",
                "rank_basis",
                "oos_windows",
                "methodology",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Strategy"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="strategy", label="Strategy", kind="text"),
                ColumnSpec(key="sharpe", label="Sharpe (in-sample)", kind="number", format="%.2f"),
                ColumnSpec(key="total_return", label="Total return", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="max_drawdown", label="Max DD", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="oos_sharpe", label="Sharpe (holdout)", kind="number", format="%.2f"),
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
                CardSlot(key="universe_size", label="Symbols", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BMTX runs every selected registered strategy on every symbol's "
            "daily OHLCV history from live yfinance data. Each run starts at "
            "initial equity and charges commission plus slippage (bps) per "
            "unit of turnover. Cells are ranked by in-sample Sharpe. The oos_* "
            "fields score only the final 30% of bars (oos_windows), using fixed "
            "default strategy parameters so nothing is fitted on that slice. "
            "Returns are after costs. Symbols or strategies that cannot run are "
            "listed with their reason, never filled with substitute values. "
            "Backtest is strictly research; output cannot wire into live "
            "execution from this surface."
        ),
        formula_dict={
            "Sharpe": Formula(
                expression=r"SR = \bar{r} / \sigma_r \cdot \sqrt{F}",
                variables={"F": "Periods per year"},
            ),
            "MaxDrawdown": Formula(
                expression=r"MDD = \min_t (V_t / \max_{s \leq t} V_s - 1)",
                variables={},
            ),
        },
        field_dict={
            "cells": FieldDef(description="List of (symbol, strategy) run metrics; in-sample and holdout.", source="computed"),
            "oos_windows": FieldDef(description="Per-symbol train and holdout bar counts and dates.", source="computed"),
            "strategies": FieldDef(description="Echo of the requested strategy names.", source="input"),
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
                name="bmtx_cells_bounded_by_symbols_times_strategies",
                description="The grid has at most |symbols| × |strategies| cells, one per completed run.",
                inputs={},
                assertions=["len(cells) <= len(symbols) * len(strategies)"],
            ),
            SemanticTest(
                name="bmtx_holdout_uses_only_final_slice",
                description="oos_* metrics are computed on the final holdout slice only, never on the ranked history.",
                inputs={},
                assertions=["oos metrics computed strictly on oos_windows test slice"],
            ),
            SemanticTest(
                name="bmtx_unknown_strategy_returns_actionable_warning",
                description="An unregistered strategy name returns a warning naming it, with no cells for it.",
                inputs={"strategies": ["does_not_exist"]},
                assertions=["warnings_non_empty", "cells_empty_for_unknown_strategy"],
            ),
        ],
    )


__all__ = ["bmtx"]
