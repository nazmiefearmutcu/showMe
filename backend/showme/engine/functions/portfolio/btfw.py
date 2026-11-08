"""BTFW — Walk-forward backtest function.

Runs a real walk-forward evaluation via
``showme.engine.services.backtest_framework.WalkForwardBacktest``: sequential
train/test folds, parameters fitted on the train slice only, results reported
from the out-of-sample slices with a leakage tripwire and worst-fold reporting.

Inputs are read under the names the manifest declares (strategy_id,
window_length, commission_bps, walk_steps, train_pct, walk_mode). The legacy
names (strategy, days, fee_bps, n_splits) are still accepted. A value that is
typed but not a valid number, or is out of range, returns an explicit
input_error instead of a silently substituted default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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

# Manifest window_length -> calendar days of history. 3Y matches the handler's
# historical default (365 * 3 days).
WINDOW_DAYS: dict[str, int] = {
    "30d": 30, "90d": 90, "180d": 180, "1Y": 365, "2Y": 730, "3Y": 1095,
}
DEFAULT_WINDOW = "3Y"
DEFAULT_WALK_STEPS = 5


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


class _InputError(ValueError):
    """A typed BTFW input that is not a valid value; the message names it."""


@dataclass(frozen=True)
class _RunConfig:
    strategy: str
    days: int
    fee_bps: float
    allow_short: bool
    cash: float
    walk_steps: int
    train_pct: float
    walk_mode: str
    warmup: int
    live: bool
    interval: str
    notes: tuple[str, ...]


def _first_present(params: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, Any]:
    for key in keys:
        value = params.get(key)
        if value not in (None, ""):
            return key, value
    return None, None


def _float_param(params: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
    key, value = _first_present(params, keys)
    if key is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _InputError(f"BTFW: {key} must be a number, got {value!r}.") from None
    if not math.isfinite(number):
        raise _InputError(f"BTFW: {key} must be a finite number, got {value!r}.")
    return number


def _int_param(params: dict[str, Any], keys: tuple[str, ...], default: int) -> int:
    number = _float_param(params, keys, float(default))
    if not number.is_integer():
        key, value = _first_present(params, keys)
        raise _InputError(f"BTFW: {key} must be a whole number, got {value!r}.")
    return int(number)


def _run_config(params: dict[str, Any]) -> _RunConfig:
    """Resolve the declared BTFW inputs. Raises _InputError for a bad value."""
    strategy = str(params.get("strategy_id") or params.get("strategy") or "sma_crossover").strip()
    notes: list[str] = []

    key, window = _first_present(params, ("window_length",))
    if key is not None and str(window) not in WINDOW_DAYS:
        raise _InputError(
            f"BTFW: window_length must be one of {', '.join(WINDOW_DAYS)}, got {window!r}."
        )
    days_key, _ = _first_present(params, ("days",))
    if key is None or days_key is not None:
        days = _int_param(params, ("days",), WINDOW_DAYS[DEFAULT_WINDOW])
    else:
        days = WINDOW_DAYS[str(window)]

    fee_bps = _float_param(params, ("commission_bps", "fee_bps"), 5.0)
    train_pct = _float_param(params, ("train_pct",), 0.7)
    if not 0.1 <= train_pct <= 0.95:
        raise _InputError(f"BTFW: train_pct must be between 0.1 and 0.95, got {train_pct}.")
    walk_steps = _int_param(params, ("walk_steps", "n_splits"), DEFAULT_WALK_STEPS)
    if walk_steps < 2:
        raise _InputError(f"BTFW: walk_steps must be at least 2, got {walk_steps}.")
    walk_mode = str(params.get("walk_mode") or "anchored").strip()
    if walk_mode not in ("anchored", "rolling"):
        raise _InputError(f"BTFW: walk_mode must be 'anchored' or 'rolling', got {walk_mode!r}.")
    warmup = _int_param(params, ("warmup",), 30)
    allow_short = bool(params.get("allow_short", True))
    cash = _float_param(params, ("initial_cash",), 10_000.0)
    live = _truthy(params.get("live_backtest") or params.get("live"))
    interval = str(params.get("interval") or "1d")

    if key is not None and _first_present(params, ("days",))[0] is not None:
        notes.append(
            "BTFW: window_length is not applied because days was also given; days sets the history length."
        )
    return _RunConfig(
        strategy=strategy, days=days, fee_bps=fee_bps, allow_short=allow_short,
        cash=cash, walk_steps=walk_steps, train_pct=train_pct, walk_mode=walk_mode,
        warmup=warmup, live=live, interval=interval, notes=tuple(notes),
    )


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
        try:
            cfg = _run_config(params)
        except _InputError as exc:
            return _input_error(instrument, str(exc))
        try:
            import asyncio
            result = await asyncio.wait_for(
                self._execute_inner(instrument, cfg),
                timeout=9.0,
            )
            if cfg.notes:
                result.warnings = [*cfg.notes, *result.warnings]
            return result
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = f"BTFW execution timed out: {exc}"
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_walk_forward_template(instrument.symbol, cfg.strategy, cfg.cash),
                sources=["placeholder_no_backtest_run"],
                warnings=[reason, "Showing an illustrative placeholder — no "
                                  "backtest completed, so no metrics are reported."],
                metadata={"days": cfg.days, "fee_bps": cfg.fee_bps, "allow_short": cfg.allow_short,
                          "live": False, "is_placeholder": True,
                          "provider_errors": [reason]},
            )

    async def _execute_inner(
        self,
        instrument: Instrument,
        cfg: _RunConfig,
    ) -> FunctionResult:
        strategy_name = cfg.strategy
        days = cfg.days
        fee_bps = cfg.fee_bps
        allow_short = cfg.allow_short
        cash = cfg.cash
        sources = ["yfinance"]
        fetch_error = ""
        if strategy_name not in STRATEGY_REGISTRY:
            return FunctionResult(code=self.code, instrument=instrument, data={},
                                  warnings=[f"unknown strategy {strategy_name}",
                                            f"available: {list(STRATEGY_REGISTRY)}"])
        if not cfg.live:
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
                    interval=cfg.interval,
                ))
            except Exception as exc:
                fetch_error = f"{type(exc).__name__}: {exc}"
                df = pd.DataFrame()
        else:
            fetch_error = "no OHLCV provider configured"
            df = pd.DataFrame()
        if df.empty:
            # DATA POLICY: no synthetic history is ever substituted for market
            # data. The run is reported as unavailable, with no metrics.
            reason = (
                "Live OHLCV was unavailable for this symbol, so no walk-forward "
                "backtest was run. No synthetic history is substituted."
            )
            if fetch_error:
                reason += f" Provider error: {fetch_error}."
            return _provider_unavailable(
                instrument, strategy_name, cash, reason, days, fee_bps, allow_short,
            )
        walk_steps = cfg.walk_steps
        train_pct = cfg.train_pct
        walk_mode = cfg.walk_mode
        try:
            wf = WalkForwardBacktest(
                df, strategy_name, n_splits=walk_steps, train_pct=train_pct,
                mode=walk_mode, initial_cash=cash, fee_bps=fee_bps,
                allow_short=allow_short, warmup=cfg.warmup,
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
                "walk_steps": res.summary["n_splits"],
                "window_days": days,
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
                    "walk_steps": "Number of walk-forward folds actually run.",
                    "window_days": "Calendar days of history requested for this run.",
                },
            },
            sources=sources,
            warnings=[],
            metadata={"days": days, "fee_bps": fee_bps, "allow_short": allow_short,
                      "walk_steps": res.summary["n_splits"], "walk_mode": walk_mode,
                      "in_sample": False, "synthetic_history": False},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _input_error(instrument: Instrument, reason: str) -> FunctionResult:
    """A typed input that cannot be run: named, with no measured values."""
    data = _walk_forward_template(instrument.symbol, "sma_crossover", 10_000.0)
    data["status"] = "input_error"
    data["reason"] = reason
    data["next_actions"] = ["Correct the named BTFW input and run again."]
    return FunctionResult(
        code="BTFW",
        instrument=instrument,
        data=data,
        sources=["input_error"],
        warnings=[reason],
        metadata={"live": False, "is_placeholder": True, "synthetic_history": False},
    )


def _provider_unavailable(
    instrument: Instrument, strategy: str, cash: float, reason: str,
    days: int, fee_bps: float, allow_short: bool,
) -> FunctionResult:
    """Explicit no-data state: placeholder shape, no measured values."""
    data = _walk_forward_template(instrument.symbol, strategy, cash)
    data["status"] = "provider_unavailable"
    data["reason"] = reason
    data["next_actions"] = [
        "Retry BTFW with live=true once OHLCV history for this symbol is reachable.",
    ]
    return FunctionResult(
        code="BTFW",
        instrument=instrument,
        data=data,
        sources=["provider_unavailable"],
        warnings=[reason],
        metadata={"days": days, "fee_bps": fee_bps, "allow_short": allow_short,
                  "live": True, "is_placeholder": True, "synthetic_history": False,
                  "provider_errors": [reason]},
    )


def _walk_forward_template(symbol: str, strategy: str, cash: float) -> dict[str, Any]:
    """Empty payload returned when no backtest was actually run.

    No equity curve and no final equity are shipped: a drawn ramp would be
    an invented series (the old 1.0015^n template). Metrics are None and the
    payload is flagged on every level a consumer might read. The caller is
    told to re-run with live=true for a measured out-of-sample curve.
    """
    curve: list[dict[str, Any]] = []
    final_equity = None
    disclaimer = (
        "PLACEHOLDER — no backtest was run, so there is no equity curve and no "
        "metrics for this strategy or symbol. Re-run with live=true to compute a "
        "real out-of-sample result."
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
            "No backtest was run. No equity curve is shown and no metrics are reported; "
            "a curve is only produced by a live run on market data."
        ),
        "field_dictionary": {
            "is_placeholder": "True when no backtest was run; the payload carries no measured values.",
            "equity_curve": "Empty until a live (live=true) run completes on market data.",
        },
        "next_actions": [
            "Run BTFW with live=true to compute a real out-of-sample equity curve.",
        ],
    }
