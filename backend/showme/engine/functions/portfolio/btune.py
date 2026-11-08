"""BTUNE — Strategy hyperparameter sweep with an out-of-sample ranking.

Each parameter set is backtested twice on the same daily OHLCV history: on
the in-sample (train) slice and on the out-of-sample (test) slice. The test
slice keeps the train history as indicator warm-up, but only test-slice bars
are scored. Configurations are ranked by the out-of-sample value of the chosen
metric (as the BTUNE seed contract states); overfit_gap = in-sample − OOS.
"""

from __future__ import annotations

import asyncio
import itertools
import random
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

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

SUPPORTED_METRICS = ("sharpe", "cagr", "calmar", "sortino")
SUPPORTED_FREQUENCIES = ("1d",)
OVERFIT_GAP_THRESHOLD = 1.0  # in metric units (e.g. Sharpe points)
MIN_TRAIN_BARS = 60  # backtest warm-up is 30 bars; leave room to trade
MIN_TEST_BARS = 60
DEFAULT_FEE_BPS = 5.0
RANDOM_SEED = 0
INITIAL_CASH = 10_000


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
    description = "Hyperparameter sweep over a strategy grid; rank out-of-sample by Sharpe / total return / Calmar."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError("BTUNE requires an instrument symbol")
        spec, error = _resolve_spec(params)
        if error is not None:
            return _error_result(self.code, instrument, reason=error)
        live = _truthy(params.get("live_backtest") or params.get("live"))
        try:
            return await asyncio.wait_for(
                self._execute_inner(instrument, spec, live),
                timeout=9.0,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"BTUNE execution timed out: {exc}; no backtest metrics are reported"
            return _unavailable_result(
                self.code, instrument, spec,
                status="provider_unavailable", reason=reason,
                warnings=[reason], sources=[], live=False,
            )

    async def _execute_inner(self, instrument: Instrument, spec: dict[str, Any], live: bool) -> FunctionResult:
        if not live:
            reason = (
                "Live backtest not requested: set live_backtest=true to run the sweep on "
                "OHLCV history. No metrics are estimated without it."
            )
            return _unavailable_result(
                self.code, instrument, spec,
                status="needs_input", reason=reason,
                warnings=[reason], sources=[], live=False,
            )
        warnings: list[str] = []
        df: pd.DataFrame = pd.DataFrame()
        try:
            if not self.deps.yfinance:
                raise RuntimeError("no yfinance dependency")
            df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.now(timezone.utc) - timedelta(days=spec["days"]),
                    interval="1d",
                    extra={"timeout": 3.0},
                ))
        except Exception as exc:
            warnings.append(f"yfinance: {exc or type(exc).__name__}")
        if df is None or df.empty or "close" not in df.columns:
            reason = "live OHLCV unavailable; no backtest was run and no metrics are reported"
            warnings.append(reason)
            return _unavailable_result(
                self.code, instrument, spec,
                status="provider_unavailable", reason=reason,
                warnings=warnings, sources=[], live=False,
            )

        split_idx = int(len(df) * spec["train_pct"])
        test_bars = len(df) - split_idx
        if split_idx < MIN_TRAIN_BARS or test_bars < MIN_TEST_BARS:
            reason = (
                f"insufficient OHLCV history: {len(df)} bars split {split_idx}/{test_bars}; "
                f"need at least {MIN_TRAIN_BARS} train and {MIN_TEST_BARS} test bars"
            )
            warnings.append(reason)
            return _unavailable_result(
                self.code, instrument, spec,
                status="provider_unavailable", reason=reason,
                warnings=warnings, sources=["yfinance"], live=False,
            )

        keys = list(spec["grid"].keys())
        full_grid = [dict(zip(keys, vals)) for vals in itertools.product(*[spec["grid"][k] for k in keys])]
        planned = full_grid
        if spec["search_mode"] == "random":
            planned = random.Random(RANDOM_SEED).sample(full_grid, min(spec["n_samples"], len(full_grid)))

        train_df = df.iloc[:split_idx]
        rows: list[dict[str, Any]] = []
        skipped: list[str] = []
        for cfg in planned:
            try:
                is_metrics = Backtest(
                    train_df, _build_strategy(spec["strategy"], cfg),
                    initial_cash=INITIAL_CASH, fee_bps=spec["fee_bps"],
                ).run().metrics
                oos_metrics = Backtest(
                    df, _build_strategy(spec["strategy"], cfg),
                    initial_cash=INITIAL_CASH, fee_bps=spec["fee_bps"], eval_start=split_idx,
                ).run().metrics
            except Exception as exc:
                skipped.append(f"{_label_cfg(cfg)}: {type(exc).__name__}: {exc}")
                continue
            rows.append(_row(cfg, is_metrics, oos_metrics, spec["metric"]))

        if skipped:
            warnings.append(
                f"{len(skipped)} of {len(planned)} parameter combinations failed and were skipped; "
                f"first: {skipped[0]}"
            )
        if not rows:
            return _unavailable_result(
                self.code, instrument, spec,
                status="input_error", reason="no parameter combination produced a backtest",
                warnings=warnings, sources=["yfinance"], live=True,
            )

        ranked = sorted(rows, key=_oos_sort_key)
        top = ranked[: spec["top_n"]]
        best = ranked[0] if ranked[0]["metric_oos"] is not None else None
        if best is None:
            warnings.append(f"metric '{spec['metric']}' is not defined for any tested parameter set")
        overfit = _overfit_summary(top)
        if overfit["warning"]:
            warnings.append(
                f"in-sample metric exceeds out-of-sample by a median {overfit['median_gap']:.2f} "
                f"across the top {spec['top_n']}; treat the ranking as overfit-prone"
            )
        train_index = df.index[:split_idx]
        test_index = df.index[split_idx:]
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "status": "ok",
                "symbol": instrument.symbol,
                "strategy": spec["strategy"],
                "strategy_id": spec["strategy"],
                "metric": spec["metric"],
                "search_mode": spec["search_mode"],
                "n_samples": spec["n_samples"] if spec["search_mode"] == "random" else None,
                "fee_bps": spec["fee_bps"],
                "frequency": spec["frequency"],
                "split": {
                    "train_pct": spec["train_pct"],
                    "train_bars": split_idx,
                    "test_bars": test_bars,
                    "train_start": str(train_index[0])[:10],
                    "train_end": str(train_index[-1])[:10],
                    "test_start": str(test_index[0])[:10],
                    "test_end": str(test_index[-1])[:10],
                },
                "best_params": best["params"] if best else None,
                "best_metric_oos": best["metric_oos"] if best else None,
                "rows": top,
                "top_n_results": top,
                "full_results": ranked,
                "surface": ranked,
                "all_results": ranked,
                "param_grid": spec["grid"],
                "combos_planned": len(full_grid),
                "combos_tested": len(rows),
                "combos_skipped": len(skipped),
                "overfit_warning": overfit["warning"],
                "overfit_gap_median": overfit["median_gap"],
                "overfit_score": overfit["score"],
                "overfit_threshold": OVERFIT_GAP_THRESHOLD,
                "summary": {
                    "strategy": spec["strategy"],
                    "metric": spec["metric"],
                    "combos_tested": len(rows),
                    "combos_skipped": len(skipped),
                    "best_params": best["params"] if best else None,
                    "best_metric_oos": best["metric_oos"] if best else None,
                    "overfit_warning": overfit["warning"],
                    "source_mode": "live_yfinance",
                },
                "methodology": (
                    "Hyperparameter sweep with an out-of-sample split. Each parameter set is "
                    f"backtested on the first {spec['train_pct']:.0%} of the daily OHLCV history "
                    "(in-sample) and on the remainder (out-of-sample, with the train history kept "
                    "as indicator warm-up). Configurations are ranked by the out-of-sample value of "
                    f"'{spec['metric']}'. overfit_gap = in-sample minus out-of-sample; overfit_warning "
                    f"is set when the median gap across the top-N exceeds {OVERFIT_GAP_THRESHOLD}. "
                    "The out-of-sample figure is still a search result: the chosen set was selected "
                    "from the grid, so confirm it on new data before relying on it."
                ),
                "field_dictionary": {
                    "metric_in_sample": "Selected metric on the train slice.",
                    "metric_oos": "Selected metric on the test slice; the ranking key.",
                    "overfit_gap": "metric_in_sample minus metric_oos.",
                    "sharpe": "Out-of-sample annualized return/risk score (sqrt(252) scaling).",
                    "cagr": "Out-of-sample compound annual growth rate as a fraction (not percent); null for windows under 0.25 years.",
                    "calmar": "Out-of-sample CAGR divided by absolute max drawdown; null when undefined.",
                    "total_return": "Out-of-sample final equity divided by starting equity minus one (fraction).",
                    "max_drawdown": "Out-of-sample worst peak-to-trough decline (fraction).",
                    "label": "Readable parameter combination.",
                },
            },
            sources=["yfinance"],
            warnings=warnings,
            metadata={"days": spec["days"], "live": True},
        )


def _resolve_spec(params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Read the declared inputs (seed names first, legacy names as aliases)."""
    strategy = str(params.get("strategy_id") or params.get("strategy") or "sma_crossover")
    if strategy not in GRIDS:
        return None, f"unsupported strategy '{strategy}'; choose one of {sorted(GRIDS)}"
    grid = params.get("param_grid") or params.get("grid") or GRIDS[strategy]
    if not isinstance(grid, dict) or not grid:
        return None, "param_grid must map each parameter name to a non-empty list of values"
    for key, values in grid.items():
        if not isinstance(values, (list, tuple)) or not values:
            return None, f"param_grid['{key}'] must be a non-empty list"
    metric = str(params.get("metric") or "sharpe")
    if metric not in SUPPORTED_METRICS:
        return None, f"unsupported metric '{metric}'; choose one of {list(SUPPORTED_METRICS)}"
    search_mode = str(params.get("search_mode") or "grid")
    if search_mode not in ("grid", "random"):
        return None, "search_mode must be 'grid' or 'random'"
    try:
        n_samples = int(params.get("n_samples") or 200)
        top_n = int(params.get("top_n") or 10)
        train_pct = float(params.get("train_pct") if params.get("train_pct") is not None else 0.7)
        fee_bps = float(params.get("fee_bps") if params.get("fee_bps") is not None else DEFAULT_FEE_BPS)
        days = int(params.get("days", 365 * 3))
    except (TypeError, ValueError):
        return None, "n_samples, top_n, train_pct, fee_bps and days must be numbers"
    if n_samples < 1 or top_n < 1:
        return None, "n_samples and top_n must be at least 1"
    if not 0.3 <= train_pct <= 0.9:
        return None, "train_pct must be between 0.3 and 0.9"
    if fee_bps < 0:
        return None, "fee_bps must be zero or positive"
    frequency = str(params.get("frequency") or "1d")
    if frequency not in SUPPORTED_FREQUENCIES:
        return None, f"frequency '{frequency}' is not implemented; only {list(SUPPORTED_FREQUENCIES)} bars are supported"
    return {
        "strategy": strategy,
        "grid": grid,
        "metric": metric,
        "search_mode": search_mode,
        "n_samples": n_samples,
        "top_n": top_n,
        "train_pct": train_pct,
        "fee_bps": fee_bps,
        "days": days,
        "frequency": frequency,
    }, None


def _f(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if number != number else number  # NaN -> None


def _row(cfg: dict[str, Any], is_m: dict[str, Any], oos_m: dict[str, Any], metric: str) -> dict[str, Any]:
    m_is = _f(is_m.get(metric))
    m_oos = _f(oos_m.get(metric))
    gap = (m_is - m_oos) if (m_is is not None and m_oos is not None) else None
    return {
        "label": _label_cfg(cfg),
        "params": cfg,
        "metric_in_sample": m_is,
        "metric_oos": m_oos,
        "overfit_gap": _f(gap),
        "sharpe": _f(oos_m.get("sharpe")),
        "sharpe_in_sample": _f(is_m.get("sharpe")),
        "cagr": _f(oos_m.get("cagr")),
        "calmar": _f(oos_m.get("calmar")),
        "sortino": _f(oos_m.get("sortino")),
        "total_return": _f(oos_m.get("total_return")),
        "total_return_in_sample": _f(is_m.get("total_return")),
        "max_drawdown": _f(oos_m.get("max_drawdown")),
        "trades": int(oos_m.get("trades") or 0),
        "status": "computed",
    }


def _oos_sort_key(row: dict[str, Any]) -> tuple[bool, float]:
    value = row["metric_oos"]
    return (value is None, -value if value is not None else 0.0)


def _overfit_summary(top: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [r["overfit_gap"] for r in top if r["overfit_gap"] is not None]
    oos = [r["metric_oos"] for r in top if r["metric_oos"] is not None]
    median_gap = float(statistics.median(gaps)) if gaps else None
    score = None
    if median_gap is not None and len(oos) >= 2:
        spread = statistics.stdev(oos)
        score = median_gap / spread if spread > 0 else None
    warning = bool(median_gap is not None and median_gap > OVERFIT_GAP_THRESHOLD)
    return {"median_gap": median_gap, "score": score, "warning": warning}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _label_cfg(cfg: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in cfg.items())


def _error_result(code: str, instrument: Instrument, *, reason: str) -> FunctionResult:
    return FunctionResult(
        code=code,
        instrument=instrument,
        data={
            "status": "input_error",
            "reason": reason,
            "best_params": None,
            "rows": [],
            "top_n_results": [],
            "full_results": [],
            "combos_tested": 0,
            "next_actions": ["Correct the highlighted input and run the sweep again."],
        },
        warnings=[reason],
    )


def _unavailable_result(
    code: str,
    instrument: Instrument,
    spec: dict[str, Any] | None,
    *,
    status: str,
    reason: str,
    warnings: list[str],
    sources: list[str],
    live: bool,
) -> FunctionResult:
    """Honest non-result: the planned grid is listed, but no metric is computed."""
    grid = spec["grid"] if spec else {}
    strategy = spec["strategy"] if spec else None
    keys = list(grid.keys())
    rows: list[dict[str, Any]] = []
    for vals in itertools.product(*[grid[k] for k in keys]):
        cfg = dict(zip(keys, vals))
        rows.append({
            "label": _label_cfg(cfg),
            "params": cfg,
            "metric_in_sample": None,
            "metric_oos": None,
            "overfit_gap": None,
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
            "best_metric_oos": None,
            "rows": rows,
            "top_n_results": [],
            "full_results": rows,
            "surface": rows,
            "all_results": rows,
            "param_grid": grid,
            "combos_tested": 0,
            "combos_planned": len(rows),
            "overfit_warning": None,
            "summary": {
                "strategy": strategy,
                "combos_tested": 0,
                "combos_planned": len(rows),
                "best_metric_oos": None,
                "source_mode": "not_computed",
            },
            "methodology": (
                "No backtest was run. The planned parameter grid is listed for reference only; "
                "metrics are reported only from a live OHLCV sweep with an out-of-sample split."
            ),
            "next_actions": [
                "Set live_backtest=true to run the sweep on OHLCV history.",
                "Retry when the market-data provider is reachable.",
            ],
        },
        sources=sources,
        warnings=warnings,
        metadata={"days": spec["days"] if spec else None, "live": live},
    )
