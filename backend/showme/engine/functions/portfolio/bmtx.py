"""BMTX — Backtest matrix (strategy × universe).

Verilen sembol listesini ve birden fazla strategy ismini paralel olarak
backtest eder; her hücrede Sharpe ve total return raporlar.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.backtest_framework import Backtest, STRATEGY_REGISTRY

# Wall-clock budget for one matrix run (fetch + backtests).
LIVE_TIMEOUT_S = 9.0

# BMTX#6: fraction of the most recent bars scored as the out-of-sample holdout.
OOS_TEST_FRACTION = 0.3


@FunctionRegistry.register
class BMTXFunction(BaseFunction):
    code = "BMTX"
    name = "Backtest Matrix"
    category = "portfolio"
    description = "Run multiple strategies across a symbol universe in parallel."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Fix A7-C3: GET ?symbols=AAPL,MSFT,NVDA arrives as a string and used
        # to iterate character-by-character into ["A","P","S"]. Mirror the
        # guard BLAK/RPAR already implement.
        symbols = _requested_symbols(params)
        strategies = params.get("strategies") or list(STRATEGY_REGISTRY.keys())
        if isinstance(strategies, str):
            strategies = [s.strip() for s in strategies.split(",") if s.strip()]
        days = int(params.get("days", 365 * 3))
        fee_bps = _cost_inputs(params)[3]
        try:
            return await asyncio.wait_for(
                self._execute_inner(instrument, **params),
                timeout=LIVE_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            # BMTX#3: a timed-out run is an honest outage, not a reference
            # matrix with invented Sharpe values under the requested tickers.
            reason = f"BMTX execution timed out after {LIVE_TIMEOUT_S:g}s: {exc}"
            return _unavailable(
                instrument=instrument,
                symbols=symbols,
                strategies=strategies,
                days=days,
                fee_bps=fee_bps,
                reason=reason,
                failures={},
            )

    async def _execute_inner(
        self,
        instrument: Instrument | None = None,
        **params: Any,
    ) -> FunctionResult:
        symbols = _requested_symbols(params)
        strategies = params.get("strategies") or list(STRATEGY_REGISTRY.keys())
        if isinstance(strategies, str):
            strategies = [s.strip() for s in strategies.split(",") if s.strip()]
        days = int(params.get("days", 365 * 3))
        initial_equity, commission_bps, slippage_bps, fee_bps = _cost_inputs(params)
        sources = ["yfinance"]
        if not _live_requested(params):
            # BMTX residual: without live OHLCV no backtest runs, so the grid
            # carries requested labels with null metrics and needs_input status.
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_matrix_template(symbols, strategies),
                sources=[],
                warnings=[_OFFLINE_REASON],
                metadata={"days": days, "fee_bps": fee_bps, "live": False},
            )
        else:
            bars_dict = {}

        async def _bars(sym: str):
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("no live OHLCV provider is configured")
                inst = await self.deps.symbol_registry.resolve(sym) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                df = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=inst,
                    start=datetime.now(timezone.utc) - timedelta(days=days),
                    interval="1d",
                ))
            except Exception as exc:
                return sym, None, f"OHLCV fetch failed ({type(exc).__name__})"
            if df is None or df.empty:
                return sym, None, "provider returned no OHLCV rows"
            return sym, df, None
        bars_results = await asyncio.gather(*(_bars(s) for s in symbols))
        bars_dict = {s: df for s, df, _ in bars_results if df is not None}
        failures = {s: reason for s, df, reason in bars_results if df is None}
        if not bars_dict:
            # BMTX#3: never substitute a template history. Report the outage
            # and name every symbol that produced no bars.
            return _unavailable(
                instrument=instrument,
                symbols=symbols,
                strategies=strategies,
                days=days,
                fee_bps=fee_bps,
                reason="Live OHLCV providers returned no usable bars for any requested symbol.",
                failures=failures,
            )
        # BMTX: a requested name that is not registered is not run; name it, do not drop it silently.
        unknown_strategies = [s for s in strategies if s not in STRATEGY_REGISTRY]
        # BMTX#5: the backtest loop is CPU-bound and synchronous. It runs in a
        # worker thread so LIVE_TIMEOUT_S can fire and the event loop stays free.
        cells, strategy_errors, oos_windows = await asyncio.to_thread(
            _run_backtests, bars_dict, strategies, initial_equity, fee_bps,
        )
        # BMTX-R1: a symbol with no successful cell is excluded and named with its reason.
        ok_symbols = {cell["symbol"] for cell in cells}
        failed_cells = [
            {"symbol": sym, "strategy": strat, "error": msg}
            for sym, errs in strategy_errors.items()
            for strat, msg in errs
        ]
        for sym in list(bars_dict):
            if sym not in ok_symbols:
                reasons = [f"{strat}: {msg}" for strat, msg in strategy_errors.get(sym, [])]
                if reasons:
                    failures[sym] = "all strategy backtests failed (" + "; ".join(reasons) + ")"
                elif unknown_strategies:
                    failures[sym] = (
                        "no registered strategy produced a run (not registered: "
                        + ", ".join(unknown_strategies) + ")"
                    )
                else:
                    failures[sym] = "no registered strategy produced a run"
                del bars_dict[sym]
                oos_windows.pop(sym, None)
        if not bars_dict:
            return _no_run_result(
                instrument=instrument,
                symbols=symbols,
                strategies=strategies,
                days=days,
                fee_bps=fee_bps,
                failures=failures,
                unknown_strategies=unknown_strategies,
                strategy_errors=strategy_errors,
            )
        # Best per symbol
        best_per_symbol = {}
        for cell in cells:
            sym = cell["symbol"]
            if sym not in best_per_symbol or cell["sharpe"] > best_per_symbol[sym]["sharpe"]:
                best_per_symbol[sym] = cell
        cells.sort(key=lambda x: -x["sharpe"])
        surface = [
            {
                "label": cell["label"],
                "symbol": cell["symbol"],
                "strategy": cell["strategy"],
                "sharpe": cell["sharpe"],
                "total_return": cell["total_return"],
                "max_drawdown": cell["max_drawdown"],
                "oos_sharpe": cell["oos_sharpe"],
            }
            for cell in cells
        ]
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": "partial" if (failures or failed_cells or unknown_strategies) else "ok",
                "symbols": list(bars_dict.keys()),
                "unavailable_symbols": list(failures),
                "failed_cells": failed_cells,
                "unknown_strategies": unknown_strategies,
                "strategies": strategies,
                "cells": cells,
                "surface": surface,
                "best_per_symbol": best_per_symbol,
                "rank_basis": "in_sample_sharpe",
                "oos_windows": oos_windows,
                "top_10_by_sharpe": cells[:10],
                "summary": {
                    "symbols": len(bars_dict),
                    "strategies": len(strategies),
                    "runs": len(cells),
                    "best_sharpe": cells[0]["sharpe"] if cells else None,
                },
                "methodology": (
                    "Runs each selected strategy on each symbol's daily OHLCV history "
                    f"from initial equity {initial_equity:,.0f} with commission "
                    f"{commission_bps:g} bps plus slippage {slippage_bps:g} bps per unit of turnover, "
                    "then ranks cells by in-sample Sharpe and total return. "
                    "IN-SAMPLE ranking — each cell is ranked on the history it is scored on, "
                    "so the top cell is favoured by the comparison itself. The oos_* fields "
                    "score only the final holdout slice (oos_windows); the strategies use fixed "
                    "default parameters, so nothing is fitted on that slice. Use BTFW for a "
                    "walk-forward estimate of a chosen strategy/symbol pair."
                ),
                "field_dictionary": {
                    "sharpe": "Annualized return/risk score from the backtest equity curve.",
                    "total_return": "Final equity divided by initial equity minus one.",
                    "max_drawdown": "Worst peak-to-trough equity decline during the test.",
                    "trades": "Number of trade events created by the strategy.",
                    "oos_sharpe": "Sharpe on the final holdout slice only (oos_windows); not used for ranking.",
                    "oos_total_return": "Holdout total return on the final slice only, after costs.",
                    "oos_max_drawdown": "Worst peak-to-trough equity decline on the holdout slice only.",
                    "rank_basis": "Column the cells are sorted by. In-sample Sharpe, not out-of-sample.",
                    "surface": "Strategy-by-symbol grid used by the heatmap.",
                },
            },
            sources=sources,
            warnings=[_failure_warning(sym, reason) for sym, reason in failures.items()]
            + [
                f"BMTX: {cell['strategy']} failed on {cell['symbol']} ({cell['error']}); that cell is excluded."
                for cell in failed_cells if cell["symbol"] in ok_symbols
            ]
            + [
                f"BMTX: strategy '{name}' is not registered and was not run."
                for name in unknown_strategies
            ],
            metadata={"days": days, "fee_bps": fee_bps, "live": True,
                      "unavailable_symbols": list(failures)},
        )


def _run_backtests(
    bars_dict: dict[str, pd.DataFrame],
    strategies: list[str],
    initial_equity: float,
    fee_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, str]]], dict[str, dict[str, Any]]]:
    """Synchronous backtest grid: one cell per (symbol, registered strategy).

    Returns (cells, strategy_errors, oos_windows). Each failed run is kept with
    its reason in strategy_errors (BMTX-R1), never dropped silently.
    """
    cells: list[dict[str, Any]] = []
    strategy_errors: dict[str, list[tuple[str, str]]] = {}
    oos_windows: dict[str, dict[str, Any]] = {}
    for sym, df in bars_dict.items():
        split = _oos_split(len(df))
        oos_windows[sym] = _oos_window(df, split)
        for strat in strategies:
            fn = STRATEGY_REGISTRY.get(strat)
            if fn is None:
                continue
            try:
                bt = Backtest(df, fn, initial_cash=initial_equity, fee_bps=fee_bps)
                r = bt.run()
                # BMTX#6: holdout score on the final slice only. The strategies
                # use fixed default parameters, so nothing is fitted on it.
                holdout = Backtest(df, fn, initial_cash=initial_equity, fee_bps=fee_bps,
                                   eval_start=split).run()
                cells.append({
                    "label": f"{sym} {strat}",
                    "symbol": sym, "strategy": strat,
                    "sharpe": r.metrics["sharpe"],
                    "total_return": r.metrics["total_return"],
                    "max_drawdown": r.metrics["max_drawdown"],
                    "trades": r.metrics["trades"],
                    "final_equity": r.final_equity,
                    "oos_sharpe": holdout.metrics["sharpe"],
                    "oos_total_return": holdout.metrics["total_return"],
                    "oos_max_drawdown": holdout.metrics["max_drawdown"],
                })
            except Exception as exc:  # BMTX-R1: keep the reason, do not drop silently
                strategy_errors.setdefault(sym, []).append(
                    (strat, f"{type(exc).__name__}: {exc}")
                )
    return cells, strategy_errors, oos_windows


def _failure_warning(sym: str, reason: str) -> str:
    return f"BMTX: no usable live backtest for {sym} ({reason}); it is excluded from the matrix."


_PROVIDER_NEXT_ACTIONS = [
    "Check that the live OHLCV provider is configured and reachable.",
    "Verify that each requested symbol is a valid ticker for that provider.",
]
_PROVIDER_METHODOLOGY = "No backtest was run: live OHLCV history was unavailable, and no substitute history is used."


def _no_run_result(
    *,
    instrument: Instrument | None,
    symbols: list[str],
    strategies: list[str],
    days: int,
    fee_bps: float,
    failures: dict[str, str],
    unknown_strategies: list[str],
    strategy_errors: dict[str, list[tuple[str, str]]],
) -> FunctionResult:
    """BMTX-R1: bars loaded, yet no backtest completed. The cause is named.

    An unregistered strategy name is an input error, and a run that raised is
    an empty result. Neither is a provider outage, so ``provider_unavailable``
    is reserved for the case where no OHLCV history arrived.
    """
    raised: dict[str, str] = {}
    for errs in strategy_errors.values():
        for strat, msg in errs:
            raised.setdefault(strat, msg)
    parts = []
    if unknown_strategies:
        parts.append("not registered: " + ", ".join(unknown_strategies))
    if raised:
        parts.append("raised: " + "; ".join(f"{strat} ({msg})" for strat, msg in raised.items()))
    detail = "; ".join(parts) or "no registered strategy produced a run"
    if unknown_strategies and set(unknown_strategies) == set(strategies):
        return _unavailable(
            instrument=instrument,
            symbols=symbols,
            strategies=strategies,
            days=days,
            fee_bps=fee_bps,
            reason=f"No backtest completed: none of the requested strategies is registered ({detail}).",
            failures=failures,
            status="input_error",
            next_actions=[
                "Request registered strategy names: " + ", ".join(sorted(STRATEGY_REGISTRY)) + ".",
            ],
            methodology="No backtest was run: no requested strategy is registered, so no metrics are shown.",
        )
    return _unavailable(
        instrument=instrument,
        symbols=symbols,
        strategies=strategies,
        days=days,
        fee_bps=fee_bps,
        reason=f"No backtest completed for any requested symbol ({detail}).",
        failures=failures,
        status="empty",
        next_actions=[
            "Read the warnings for the error behind each failed strategy run, then retry with other strategies or symbols.",
        ],
        methodology="No backtest completed on the loaded bars, so no metrics are shown and no substitute history is used.",
    )


def _unavailable(
    *,
    instrument: Instrument | None,
    symbols: list[str],
    strategies: list[str],
    days: int,
    fee_bps: float,
    reason: str,
    failures: dict[str, str],
    status: str = "provider_unavailable",
    next_actions: list[str] | None = None,
    methodology: str = _PROVIDER_METHODOLOGY,
) -> FunctionResult:
    """Honest live-mode gap: no cells, no template values, explicit status and reason."""
    is_provider = status == "provider_unavailable"
    warnings = [reason] + [_failure_warning(sym, why) for sym, why in failures.items()]
    return FunctionResult(
        code="BMTX",
        instrument=instrument,
        data={
            "status": status,
            "reason": reason,
            "symbols": [],
            "requested_symbols": list(symbols),
            "unavailable_symbols": list(failures) or list(symbols),
            "strategies": list(strategies),
            "cells": [],
            "surface": [],
            "best_per_symbol": {},
            "top_10_by_sharpe": [],
            "summary": {
                "symbols": 0,
                "strategies": len(strategies),
                "runs": 0,
                "best_sharpe": None,
                "source_mode": "live_unavailable" if is_provider else "live_no_run",
            },
            "next_actions": list(next_actions) if next_actions is not None else list(_PROVIDER_NEXT_ACTIONS),
            "methodology": methodology,
        },
        sources=["yfinance"],
        warnings=warnings,
        metadata={"days": days, "fee_bps": fee_bps, "live": True,
                  "provider_errors": [reason] if is_provider else [],
                  "unavailable_symbols": list(failures) or list(symbols)},
    )


_DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]


def _requested_symbols(params: dict[str, Any]) -> list[str]:
    """Symbols from ``symbols`` (pane) or ``universe`` (seed control name).

    Both accept a comma-separated string (GET query) or a list.
    """
    raw = params.get("symbols") or params.get("universe") or list(_DEFAULT_UNIVERSE)
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return list(raw)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cost_inputs(params: dict[str, Any]) -> tuple[float, float, float, float]:
    """BMTX#5: read the seed-declared inputs instead of hard-coded constants.

    Returns (initial_equity, commission_bps, slippage_bps, total_cost_bps).
    The engine charges one fee rate per turnover, so commission and slippage
    are summed into it. ``fee_bps`` is still accepted as the commission when
    ``commission_bps`` is absent.
    """
    initial_equity = float(params.get("initial_equity") or 100_000.0)
    if params.get("commission_bps") is not None:
        commission_bps = float(params["commission_bps"])
    else:
        commission_bps = float(params.get("fee_bps", 5.0))
    slippage_bps = float(params["slippage_bps"]) if params.get("slippage_bps") is not None else 2.0
    return initial_equity, commission_bps, slippage_bps, commission_bps + slippage_bps


def _oos_split(n_bars: int) -> int:
    """BMTX#6: index where the final out-of-sample holdout starts."""
    test_bars = max(1, int(n_bars * OOS_TEST_FRACTION))
    return max(0, n_bars - test_bars)


def _oos_window(df: pd.DataFrame, split: int) -> dict[str, Any]:
    def _day(ts: Any) -> str:
        try:
            return pd.Timestamp(ts).date().isoformat()
        except Exception:  # noqa: BLE001 - non-datetime index keeps its raw label
            return str(ts)

    n = len(df)
    return {
        "train_bars": split,
        "test_bars": n - split,
        "test_fraction": OOS_TEST_FRACTION,
        "train_start": _day(df.index[0]),
        "train_end": _day(df.index[split - 1]) if split > 0 else None,
        "test_start": _day(df.index[split]),
        "test_end": _day(df.index[-1]),
    }


def _live_requested(params: dict[str, Any]) -> bool:
    """BMTX#4: an explicit ``live_backtest`` (even False) decides the mode.

    The router injects ``live=True`` as a default; a caller's explicit
    ``live_backtest=False`` must not be overridden by it.
    """
    if params.get("live_backtest") is not None:
        return _truthy(params["live_backtest"])
    return _truthy(params.get("live"))


_OFFLINE_REASON = (
    "Live backtest data was not requested, so no backtest ran and no metrics are shown. "
    "Set live_backtest=true to run backtests on live OHLCV history."
)


def _matrix_template(symbols: list[str], strategies: list[str]) -> dict[str, Any]:
    """Offline grid of the requested labels. Metric fields are explicit nulls.

    BMTX residual: the previous template invented Sharpe, return, drawdown and
    equity values under the requested tickers. No metric is computed or
    hard-coded here; only the labels the caller asked for are echoed.
    """
    syms = symbols[:8]
    strats = strategies[:5]
    cells: list[dict[str, Any]] = [
        {
            "label": f"{sym} {strat}",
            "symbol": sym,
            "strategy": strat,
            "sharpe": None,
            "total_return": None,
            "max_drawdown": None,
            "trades": None,
            "final_equity": None,
        }
        for sym in syms
        for strat in strats
    ]
    return {
        "status": "needs_input",
        "reason": _OFFLINE_REASON,
        "symbols": syms,
        "strategies": strats,
        "cells": cells,
        "surface": [
            {
                "label": cell["label"],
                "symbol": cell["symbol"],
                "strategy": cell["strategy"],
                "sharpe": None,
                "total_return": None,
                "max_drawdown": None,
            }
            for cell in cells
        ],
        "best_per_symbol": {},
        "top_10_by_sharpe": cells[:10],
        "summary": {
            "symbols": len(syms),
            "strategies": len(strats),
            "runs": 0,
            "best_sharpe": None,
            "source_mode": "needs_live_input",
        },
        "next_actions": [
            "Set live_backtest=true to compute backtests from live OHLCV history.",
        ],
        "methodology": (
            "No backtest was run. The grid lists the requested symbols and strategies with "
            "no metric values until live OHLCV history is requested."
        ),
        "field_dictionary": {
            "sharpe": "Annualized return/risk score from the backtest equity curve. Null without live data.",
            "total_return": "Final equity divided by initial equity minus one. Null without live data.",
            "max_drawdown": "Worst peak-to-trough equity decline during the test. Null without live data.",
            "surface": "Strategy-by-symbol grid used by the heatmap.",
        },
    }
