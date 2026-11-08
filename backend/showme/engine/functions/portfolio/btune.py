"""BTUNE — Strategy hyperparameter sweep.

Mevcut Backtest framework'unu (sma_crossover gibi) ızgara üzerinde
çalıştırır, en iyi (Sharpe / total_return / Calmar) parametre setini bulur.
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.backtest_framework import Backtest


# Predefined param grids per strategy
GRIDS = {
    "sma_crossover": {
        "fast": [5, 10, 15, 20, 30],
        "slow": [30, 50, 100, 200],
    },
    "rsi_meanrev": {
        "period": [7, 14, 21],
        "lo": [20, 25, 30],
        "hi": [70, 75, 80],
    },
}


def _build_strategy(name: str, params: dict[str, Any]):
    if name == "sma_crossover":
        from showme.engine.services.backtest_framework import sma_crossover
        def fn(bars, state):
            return sma_crossover(bars, state, fast=params["fast"], slow=params["slow"])
        return fn
    if name == "rsi_meanrev":
        from showme.engine.services.backtest_framework import rsi_meanrev
        def fn(bars, state):
            return rsi_meanrev(bars, state, period=params["period"],
                                lo=params["lo"], hi=params["hi"])
        return fn
    raise ValueError(f"unknown strategy {name}")


@FunctionRegistry.register
class BTUNEFunction(BaseFunction):
    code = "BTUNE"
    name = "Backtest Auto-Tuner"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "portfolio"
    description = "Hyperparameter sweep over a strategy grid; rank by Sharpe / total return / Calmar."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("BTUNE requires an instrument symbol")
        strategy = params.get("strategy") or "sma_crossover"
        grid = params.get("grid") or GRIDS.get(strategy)
        if not grid:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=[f"no grid for {strategy}"])
        days = int(params.get("days", 365 * 3))
        try:
            return await asyncio.wait_for(
                self._execute_inner(instrument, **params),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"BTUNE execution timed out: {exc}; no backtest metrics are reported"
            return _unavailable_result(
                self.code, instrument, strategy, grid,
                status="provider_unavailable", reason=reason, days=days,
                warnings=[reason], sources=[], live=False,
            )

    async def _execute_inner(self, instrument: Instrument, **params: Any) -> FunctionResult:
        strategy = params.get("strategy") or "sma_crossover"
        grid = params.get("grid") or GRIDS.get(strategy)
        if not grid:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=[f"no grid for {strategy}"])
        days = int(params.get("days", 365 * 3))
        warnings: list[str] = []
        if not _truthy(params.get("live_backtest") or params.get("live")):
            reason = (
                "Live backtest not requested: set live_backtest=true to run the sweep on "
                "OHLCV history. No metrics are estimated without it."
            )
            return _unavailable_result(
                self.code, instrument, strategy, grid,
                status="needs_input", reason=reason, days=days,
                warnings=[reason], sources=[], live=False,
            )
        df: pd.DataFrame = pd.DataFrame()
        try:
            if not self.deps.yfinance:
                raise RuntimeError("no yfinance dependency")
            df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.now(timezone.utc) - timedelta(days=days),
                    interval="1d",
                    extra={"timeout": 3.0},
                ))
        except Exception as exc:
            warnings.append(f"yfinance: {exc or type(exc).__name__}")
        if df.empty:
            reason = "live OHLCV unavailable; no backtest was run and no metrics are reported"
            warnings.append(reason)
            return _unavailable_result(
                self.code, instrument, strategy, grid,
                status="provider_unavailable", reason=reason, days=days,
                warnings=warnings, sources=[], live=False,
            )
        sources = ["yfinance"]
        keys = list(grid.keys())
        combos = list(itertools.product(*[grid[k] for k in keys]))
        # Run backtests in process (cheap)
        results = []
        for vals in combos:
            cfg = dict(zip(keys, vals))
            try:
                strat_fn = _build_strategy(strategy, cfg)
                bt = Backtest(df, strat_fn, initial_cash=10_000, fee_bps=5)
                r = bt.run()
                results.append({
                    "label": _label_cfg(cfg),
                    "params": cfg,
                    "sharpe": r.metrics["sharpe"],
                    "total_return": r.metrics["total_return"],
                    "max_drawdown": r.metrics["max_drawdown"],
                    "calmar": r.metrics["calmar"],
                    "trades": r.metrics["trades"],
                })
            except Exception:
                continue
        if not results:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=["no successful runs"])
        results.sort(key=lambda x: -x["sharpe"])
        live_ok = True
        # Audit Q3 #10: backtest_framework returns calmar=None when the
        # equity history is too short (<0.25 years). Filter those out
        # before picking a Calmar "best"; None is not orderable against
        # floats.
        calmar_results = [r for r in results if r.get("calmar") is not None]
        best_by_calmar = (
            max(calmar_results, key=lambda x: x["calmar"]) if calmar_results else None
        )
        best_calmar_value = best_by_calmar["calmar"] if best_by_calmar else None
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "symbol": instrument.symbol,
                "strategy": strategy,
                "best_by_sharpe": results[0],
                "best_by_return": max(results, key=lambda x: x["total_return"]),
                "best_by_calmar": best_by_calmar,
                "rows": results,
                "surface": results,
                "all_results": results,
                "param_grid": grid,
                "combos_tested": len(results),
                "summary": {
                    "strategy": strategy,
                    "combos_tested": len(results),
                    "best_sharpe": results[0]["sharpe"],
                    "best_return": max(results, key=lambda x: x["total_return"])["total_return"],
                    "best_calmar": best_calmar_value,
                    "source_mode": "live_yfinance",
                },
                "methodology": (
                    "Hyperparameter sweep: build each strategy configuration, run the "
                    "same daily-OHLCV backtest, then rank all configurations by Sharpe, "
                    "total return, and Calmar. IN-SAMPLE — every configuration is scored "
                    "on the same history it is selected from, so the winning Sharpe is "
                    "optimistically biased by the search itself and is not an estimate "
                    "of future performance. Use BTFW to evaluate a chosen configuration "
                    "out-of-sample."
                ),
                "field_dictionary": {
                    "sharpe": "Annualized return/risk score from the backtest equity curve.",
                    "calmar": "Total return divided by absolute max drawdown.",
                    "total_return": "Final equity divided by initial equity minus one.",
                    "max_drawdown": "Worst peak-to-trough equity decline.",
                    "label": "Readable parameter combination used by the chart.",
                },
            },
            sources=sources,
            warnings=warnings,
            metadata={"days": days, "live": live_ok},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _label_cfg(cfg: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in cfg.items())


def _unavailable_result(
    code: str,
    instrument: Instrument,
    strategy: str,
    grid: dict[str, Any],
    *,
    status: str,
    reason: str,
    days: int,
    warnings: list[str],
    sources: list[str],
    live: bool,
) -> FunctionResult:
    """Honest non-result: the planned grid is listed, but no metric is computed."""
    keys = list(grid.keys())
    rows: list[dict[str, Any]] = []
    for vals in itertools.product(*[grid[k] for k in keys]):
        cfg = dict(zip(keys, vals))
        rows.append({
            "label": _label_cfg(cfg),
            "params": cfg,
            "sharpe": None,
            "total_return": None,
            "max_drawdown": None,
            "calmar": None,
            "trades": None,
            "status": "not_computed",
        })
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": status,
            "reason": reason,
            "strategy": strategy,
            "best_params": None,
            "best_by_sharpe": None,
            "best_by_return": None,
            "best_by_calmar": None,
            "rows": rows,
            "surface": rows,
            "all_results": rows,
            "param_grid": grid,
            "combos_tested": 0,
            "combos_planned": len(rows),
            "summary": {
                "strategy": strategy,
                "combos_tested": 0,
                "combos_planned": len(rows),
                "best_sharpe": None,
                "source_mode": "not_computed",
            },
            "methodology": (
                "No backtest was run. The planned parameter grid is listed for reference only; "
                "metrics are reported only from a live OHLCV sweep."
            ),
            "next_actions": [
                "Set live_backtest=true to run the sweep on OHLCV history.",
                "Retry when the market-data provider is reachable.",
            ],
        },
        sources=sources,
        warnings=warnings,
        metadata={"days": days, "live": live},
    )
