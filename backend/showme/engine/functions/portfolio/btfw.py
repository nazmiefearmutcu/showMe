"""BTFW — Walk-forward backtest function.

Runs a real walk-forward evaluation via
``showme.engine.services.backtest_framework.WalkForwardBacktest``: sequential
train/test folds, parameters fitted on the train slice only, results reported
from the out-of-sample slices with a leakage tripwire and worst-fold reporting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.backtest_framework import (
    STRATEGY_REGISTRY, WalkForwardBacktest,
)


def _template_history(days: int) -> pd.DataFrame:
    periods = max(240, min(days, 756))
    index = pd.date_range(end=datetime.now(timezone.utc).date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    close = 100 + (t * 0.08) + np.sin(t / 9) * 2.5
    return pd.DataFrame({
        "open": close * 0.998,
        "high": close * 1.012,
        "low": close * 0.988,
        "close": close,
        "volume": 1_000_000 + (t % 20) * 10_000,
    }, index=index)


@FunctionRegistry.register
class BTFWFunction(BaseFunction):
    code = "BTFW"
    name = "Walk-Forward Backtest"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF, AssetClass.FX)
    category = "portfolio"
    description = ("Walk-forward a registered strategy over historical OHLCV: "
                   "fit per fold on train, report out-of-sample equity, Sharpe, "
                   "drawdown and the worst fold.")

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("BTFW requires instrument")
        strategy_name = params.get("strategy") or "sma_crossover"
        days = int(params.get("days", 365 * 3))
        fee_bps = float(params.get("fee_bps", 5.0))
        allow_short = bool(params.get("allow_short", True))
        cash = float(params.get("initial_cash", 10_000))
        try:
            import asyncio
            return await asyncio.wait_for(
                self._execute_inner(instrument, **params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"BTFW execution timed out: {exc}"
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_walk_forward_template(instrument.symbol, strategy_name, cash),
                sources=["placeholder_no_backtest_run"],
                warnings=[reason, "Showing an illustrative placeholder — no "
                                  "backtest completed, so no metrics are reported."],
                metadata={"days": days, "fee_bps": fee_bps, "allow_short": allow_short,
                          "live": False, "is_placeholder": True,
                          "provider_errors": [reason]},
            )

    async def _execute_inner(
        self,
        instrument: Instrument,
        **params: Any,
    ) -> FunctionResult:
        strategy_name = params.get("strategy") or "sma_crossover"
        days = int(params.get("days", 365 * 3))
        fee_bps = float(params.get("fee_bps", 5.0))
        allow_short = bool(params.get("allow_short", True))
        cash = float(params.get("initial_cash", 10_000))
        sources = ["yfinance"]
        warnings: list[str] = []
        synthetic_history = False
        if strategy_name not in STRATEGY_REGISTRY:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=[f"unknown strategy {strategy_name}",
                                            f"available: {list(STRATEGY_REGISTRY)}"])
        if not _truthy(params.get("live_backtest") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_walk_forward_template(instrument.symbol, strategy_name, cash),
                sources=["placeholder_no_backtest_run"],
                warnings=["No backtest was run — showing an illustrative "
                          "placeholder. Pass live=true to compute a real "
                          "out-of-sample result."],
                metadata={"days": days, "fee_bps": fee_bps, "allow_short": allow_short,
                          "live": False, "is_placeholder": True},
            )
        elif self.deps.yfinance:
            try:
                df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.now(timezone.utc) - timedelta(days=days),
                    interval=params.get("interval", "1d"),
                ))
            except Exception:
                df = pd.DataFrame()
        else:
            df = pd.DataFrame()
        if df.empty:
            df = _template_history(days)
            sources = ["local_backtest_model"]
            synthetic_history = True
            # Be explicit about the substitution: the walk-forward below is a
            # real fit, but it runs on a synthetic sine ramp, not market data.
            warnings.append(
                "Live OHLCV was unavailable — walk-forward metrics below were "
                "computed on a synthetic placeholder history (sine ramp), not "
                "market data."
            )
        walk_steps = int(params.get("walk_steps", params.get("n_splits", 5)))
        train_pct = float(params.get("train_pct", 0.7))
        walk_mode = str(params.get("walk_mode", "anchored"))
        warmup = int(params.get("warmup", 30))
        try:
            wf = WalkForwardBacktest(
                df, strategy_name, n_splits=walk_steps, train_pct=train_pct,
                mode=walk_mode, initial_cash=cash, fee_bps=fee_bps,
                allow_short=allow_short, warmup=warmup,
            )
            res = wf.run()
        except ValueError as exc:
            return FunctionResult(
                code=self.code, instrument=instrument,
                data=_walk_forward_template(instrument.symbol, strategy_name, cash),
                sources=["local_backtest_model"],
                warnings=[f"walk-forward could not run on this history: {exc}"],
                metadata={"days": days, "fee_bps": fee_bps,
                          "allow_short": allow_short, "live": False,
                          "is_placeholder": True},
            )

        eq = res.oos_equity_curve
        idx_strs = [str(i) for i in eq.index]
        step = max(1, len(eq) // 500)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "symbol": instrument.symbol,
                "strategy": strategy_name,
                "walk_mode": walk_mode,
                "train_pct": train_pct,
                "oos_equity_curve": [
                    {"ts": idx_strs[i], "equity": float(eq.iloc[i])}
                    for i in range(0, len(eq), step)
                ],
                # Back-compat alias for older consumers; same OOS series.
                "equity_curve": [
                    {"ts": idx_strs[i], "equity": float(eq.iloc[i])}
                    for i in range(0, len(eq), step)
                ],
                "per_step_metrics": [
                    {
                        "step": f.fold,
                        "train_start": f.train_start, "train_end": f.train_end,
                        "test_start": f.test_start, "test_end": f.test_end,
                        "train_bars": f.train_bars, "test_bars": f.test_bars,
                        "params": f.params,
                        "oos_return": f.oos_return,
                        "sharpe": f.metrics.get("sharpe"),
                        "cagr": f.metrics.get("cagr"),
                        "max_drawdown": f.metrics.get("max_drawdown"),
                        "trades": f.metrics.get("trades"),
                    }
                    for f in res.folds
                ],
                "final_equity": float(eq.iloc[-1]),
                "trades": res.trades[:200],
                "summary": res.summary,
                "methodology": (
                    "Single-symbol walk-forward backtest. The history is cut into "
                    f"{res.summary['n_splits']} successive folds; in each fold the first "
                    f"{train_pct:.0%} of bars fits the strategy's parameters by grid search "
                    "and the remainder is evaluated out-of-sample with those parameters "
                    "frozen. A per-fold tripwire asserts the test slice starts strictly "
                    "after the last bar the fit could see. Reported metrics come from the "
                    "stitched out-of-sample equity curve only; the worst fold is reported "
                    "alongside so a single favourable fold cannot be quoted on its own. "
                    "Position size is a fraction of current equity and fees are charged on "
                    "the notional actually traded, so returns are scale-free."
                ),
                "field_dictionary": {
                    "oos_equity_curve": "Stitched out-of-sample equity: only test-slice bars contribute.",
                    "per_step_metrics": "Per-fold train/test boundaries, fitted parameters and local metrics.",
                    "summary.oos_sharpe": "Annualized Sharpe of the stitched out-of-sample curve.",
                    "summary.positive_steps_pct": "Fraction of folds with a positive out-of-sample return.",
                    "summary.worst_fold": "The weakest fold, always reported to prevent cherry-picking.",
                    "equity": "Account equity after marking the position on each bar, net of fees.",
                    "total_return": "Final equity divided by initial equity minus one.",
                    "max_drawdown": "Worst peak-to-trough equity decline.",
                    "trades": "Number of entry/exit trade events.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata={"days": days, "fee_bps": fee_bps, "allow_short": allow_short,
                      "walk_steps": res.summary["n_splits"], "walk_mode": walk_mode,
                      "in_sample": False, "synthetic_history": synthetic_history},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _walk_forward_template(symbol: str, strategy: str, cash: float) -> dict[str, Any]:
    """Illustrative placeholder shown when no backtest was actually run.

    Every number here is INVENTED — a smooth synthetic ramp with hardcoded
    Sharpe/drawdown/trade counts. It exists so the pane has a shape to render
    before the user opts into a live backtest. It is flagged on every level
    that a consumer might read (status, is_placeholder, each metric block, the
    methodology string and a warning) so it can never be mistaken for a
    measured result.
    """
    curve = [
        {"ts": f"template-{idx + 1:03d}", "equity": round(cash * (1 + idx * 0.0015), 2)}
        for idx in range(30)
    ]
    final_equity = curve[-1]["equity"]
    disclaimer = (
        "PLACEHOLDER — not a backtest. These numbers are invented for layout "
        "purposes and say nothing about this strategy or this symbol. Re-run "
        "with live=true to compute a real out-of-sample result."
    )
    return {
        "status": "placeholder",
        "is_placeholder": True,
        "measured": False,
        "symbol": symbol,
        "strategy": strategy,
        "disclaimer": disclaimer,
        "metrics": {
            "is_placeholder": True,
            "sharpe": None,
            "total_return": None,
            "max_drawdown": None,
            "trades": None,
            "note": disclaimer,
        },
        "final_equity": final_equity,
        "trades": [],
        "equity_curve": curve,
        "oos_equity_curve": curve,
        "per_step_metrics": [],
        "summary": {
            "strategy": strategy,
            "is_placeholder": True,
            "measured": False,
            "oos_sharpe": None,
            "oos_total_return": None,
            "oos_max_drawdown": None,
            "positive_steps_pct": None,
            "trades": None,
            "source_mode": "placeholder_shape_only",
            "note": disclaimer,
        },
        "methodology": (
            "No backtest was run. The curve below is an invented placeholder "
            "used only to give the pane a shape; it is not derived from market "
            "data and no metrics are reported from it."
        ),
        "field_dictionary": {
            "is_placeholder": "True when the payload is illustrative rather than measured.",
            "equity_curve": "Synthetic ramp for layout only — carries no information.",
        },
    }
