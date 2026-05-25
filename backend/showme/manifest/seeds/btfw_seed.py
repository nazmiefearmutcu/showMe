"""BTFW — Backtest with Forward Window (rolling walk-forward).

Anchored or rolling walk-forward backtest: at each step fit on the
train window, test on the next walk_step, then advance. Produces a
stitched out-of-sample equity curve plus per-step metrics. Paper-safe.
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
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def btfw() -> FunctionManifest:
    return FunctionManifest(
        code="BTFW",
        name="Backtest Walk-Forward",
        category=Category.PORTFOLIO,
        intent=(
            "Anchored or rolling walk-forward backtest: fit on the train "
            "window, evaluate strictly out-of-sample on the next walk_step, "
            "then advance. Produces a stitched OOS equity curve and per-"
            "step metric series. Paper-safe."
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
                description="Strategy spec to evaluate.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Single instrument; for multi-symbol use BMTX.",
            ),
            InputSpec(
                name="train_pct",
                label="Train % per window",
                control=ControlKind.NUMBER,
                required=True,
                description="Share of each window dedicated to fitting parameters.",
                min=0.1,
                max=0.95,
                step=0.05,
            ),
            InputSpec(
                name="walk_steps",
                label="Walk steps",
                control=ControlKind.NUMBER,
                required=True,
                description="Number of forward walks to perform.",
                min=2,
                max=200,
                step=1,
            ),
            InputSpec(
                name="walk_mode",
                label="Walk mode",
                control=ControlKind.SELECT,
                required=False,
                description="Anchored (expanding train) or rolling (sliding train).",
                options=["anchored", "rolling"],
            ),
            InputSpec(
                name="window_length",
                label="Window length",
                control=ControlKind.SELECT,
                required=False,
                description="Length of each train+test window.",
                options=["30d", "90d", "180d", "1Y", "2Y"],
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
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Always true here.",
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
            "train_pct": 0.7,
            "walk_steps": 12,
            "walk_mode": "anchored",
            "window_length": "1Y",
            "frequency": "1d",
            "commission_bps": 5.0,
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
                "oos_equity_curve",
                "per_step_metrics",
                "summary",
                "data_mode",
            ],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="ms", label="Time"),
            y_axis=AxisSpec(type="numeric", unit="ccy", label="OOS Equity"),
            panes=[
                PaneGrammar(name="equity", series_kind="line", height_pct=70),
                PaneGrammar(name="drawdown", series_kind="area", height_pct=30),
            ],
            overlay_support=True,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="step", label="Step", kind="number", format="%d"),
                ColumnSpec(key="train_start", label="Train start", kind="date"),
                ColumnSpec(key="test_start", label="Test start", kind="date"),
                ColumnSpec(key="test_end", label="Test end", kind="date"),
                ColumnSpec(key="sharpe", label="Sharpe", kind="number", format="%.2f"),
                ColumnSpec(key="cagr", label="CAGR", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="max_drawdown", label="Max DD", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="trades", label="Trades", kind="number", format="%d"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="oos_sharpe", label="OOS Sharpe", kind="big_number"),
                CardSlot(key="oos_cagr", label="OOS CAGR", kind="kpi", unit="%"),
                CardSlot(key="oos_max_drawdown", label="OOS Max DD", kind="kpi", unit="%"),
                CardSlot(key="positive_steps_pct", label="+ Steps", kind="kpi", unit="%"),
                CardSlot(key="walk_mode", label="Mode", kind="badge"),
                CardSlot(key="paper_mode", label="Safe", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BTFW partitions the historical window into walk_steps "
            "successive windows. Each window: take train_pct of the bars "
            "(anchored = expanding from the original start; rolling = "
            "sliding train of fixed length), run the strategy compute "
            "engine to fit any fittable parameters on the train slice, "
            "then evaluate signals on the test slice with commission and "
            "slippage applied at fill time. The OOS equity is the "
            "stitched test-slice equity across all steps; per-step metrics "
            "report Sharpe / CAGR / drawdown / trade count locally. "
            "Summary reports OOS Sharpe (computed on the stitched curve), "
            "fraction of steps with positive return, and the worst-step "
            "drawdown. No information leaks from test back to train — the "
            "test result of step k never influences the fit of step k+1."
        ),
        formula_dict={
            "WalkBoundary": Formula(
                expression=r"train_k = [t_k, t_k + L \cdot train\_pct), \; test_k = [t_k + L \cdot train\_pct, t_{k+1})",
                variables={"L": "Window length"},
            ),
            "OOSEquity": Formula(
                expression=r"V_t^{OOS} = V_{t-1}^{OOS} (1 + r_t^{test})",
                variables={"r_t^test": "Strictly-test-slice return"},
            ),
            "PositiveStepsPct": Formula(
                expression=r"PS = N_{step: r > 0} / N_{steps}",
                variables={},
            ),
        },
        field_dict={
            "oos_equity_curve": FieldDef(unit="ccy", description="Stitched test-slice equity series.", source="computed"),
            "per_step_metrics[]": FieldDef(description="Per-step Sharpe / CAGR / DD / trade count.", source="computed"),
            "summary.oos_sharpe": FieldDef(description="Sharpe of the stitched OOS curve.", source="computed"),
            "summary.positive_steps_pct": FieldDef(unit="decimal", description="Fraction of steps with positive return.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="btfw_paper_mode_always_true",
                description="Walk-forward backtest is research-only.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="btfw_test_slices_are_strictly_after_train",
                description="In every step, test_start > train_end (no peeking).",
                inputs={},
                assertions=["all_steps test_start > train_end"],
            ),
            SemanticTest(
                name="btfw_oos_curve_length_matches_test_bars",
                description="OOS equity curve length equals the sum of test-bar counts.",
                inputs={},
                assertions=["len(oos_equity_curve) == sum(len(test_slice))"],
            ),
            SemanticTest(
                name="btfw_rolling_train_window_does_not_grow",
                description="In rolling mode, train length is constant across steps.",
                inputs={"walk_mode": "rolling"},
                assertions=["len(train_k) == len(train_0) for all k"],
            ),
        ],
    )


__all__ = ["btfw"]
