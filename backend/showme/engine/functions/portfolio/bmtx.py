"""BMTX — Backtest matrix (strategy × universe).

Verilen sembol listesini ve birden fazla strategy ismini paralel olarak
backtest eder; her hücrede Sharpe ve total return raporlar.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services.backtest_framework import Backtest, STRATEGY_REGISTRY

# Wall-clock budget for one matrix run (fetch + backtests).
LIVE_TIMEOUT_S = 9.0


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
        symbols = params.get("symbols") or [
            "SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMZN",
        ]
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        strategies = params.get("strategies") or list(STRATEGY_REGISTRY.keys())
        if isinstance(strategies, str):
            strategies = [s.strip() for s in strategies.split(",") if s.strip()]
        days = int(params.get("days", 365 * 3))
        fee_bps = float(params.get("fee_bps", 5.0))
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
        symbols = params.get("symbols") or [
            "SPY", "QQQ", "IWM", "AAPL", "MSFT", "TSLA", "NVDA", "AMZN",
        ]
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        strategies = params.get("strategies") or list(STRATEGY_REGISTRY.keys())
        if isinstance(strategies, str):
            strategies = [s.strip() for s in strategies.split(",") if s.strip()]
        days = int(params.get("days", 365 * 3))
        fee_bps = float(params.get("fee_bps", 5.0))
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
        cells = []
        strategy_errors: dict[str, list[str]] = {}
        for sym, df in bars_dict.items():
            for strat in strategies:
                fn = STRATEGY_REGISTRY.get(strat)
                if fn is None:
                    continue
                try:
                    bt = Backtest(df, fn, initial_cash=10_000, fee_bps=fee_bps)
                    r = bt.run()
                    cells.append({
                        "label": f"{sym} {strat}",
                        "symbol": sym, "strategy": strat,
                        "sharpe": r.metrics["sharpe"],
                        "total_return": r.metrics["total_return"],
                        "max_drawdown": r.metrics["max_drawdown"],
                        "trades": r.metrics["trades"],
                        "final_equity": r.final_equity,
                    })
                except Exception as exc:  # BMTX-R1: keep the reason, do not drop silently
                    strategy_errors.setdefault(sym, []).append(
                        (strat, f"{type(exc).__name__}: {exc}")
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
                failures[sym] = (
                    "all strategy backtests failed (" + "; ".join(reasons) + ")"
                    if reasons else "no registered strategy produced a run"
                )
                del bars_dict[sym]
        if not bars_dict:
            return _unavailable(
                instrument=instrument,
                symbols=symbols,
                strategies=strategies,
                days=days,
                fee_bps=fee_bps,
                reason="No backtest completed for any requested symbol.",
                failures=failures,
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
            }
            for cell in cells
        ]
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "status": "partial" if (failures or failed_cells) else "ok",
                "symbols": list(bars_dict.keys()),
                "unavailable_symbols": list(failures),
                "failed_cells": failed_cells,
                "strategies": strategies,
                "cells": cells,
                "surface": surface,
                "best_per_symbol": best_per_symbol,
                "top_10_by_sharpe": cells[:10],
                "summary": {
                    "symbols": len(bars_dict),
                    "strategies": len(strategies),
                    "runs": len(cells),
                    "best_sharpe": cells[0]["sharpe"] if cells else None,
                },
                "methodology": (
                    "Runs each selected strategy on each symbol's daily OHLCV history "
                    "with the selected fee, then ranks cells by Sharpe and total return. "
                    "IN-SAMPLE — each cell is scored on the same history it is ranked "
                    "over, so the top cell is favoured by the comparison itself. Use "
                    "BTFW to evaluate a chosen strategy/symbol pair out-of-sample."
                ),
                "field_dictionary": {
                    "sharpe": "Annualized return/risk score from the backtest equity curve.",
                    "total_return": "Final equity divided by initial equity minus one.",
                    "max_drawdown": "Worst peak-to-trough equity decline during the test.",
                    "trades": "Number of trade events created by the strategy.",
                    "surface": "Strategy-by-symbol grid used by the heatmap.",
                },
            },
            sources=sources,
            warnings=[_failure_warning(sym, reason) for sym, reason in failures.items()]
            + [
                f"BMTX: {cell['strategy']} failed on {cell['symbol']} ({cell['error']}); that cell is excluded."
                for cell in failed_cells if cell["symbol"] in ok_symbols
            ],
            metadata={"days": days, "fee_bps": fee_bps, "live": True,
                      "unavailable_symbols": list(failures)},
        )


def _failure_warning(sym: str, reason: str) -> str:
    return f"BMTX: no usable live backtest for {sym} ({reason}); it is excluded from the matrix."


def _unavailable(
    *,
    instrument: Instrument | None,
    symbols: list[str],
    strategies: list[str],
    days: int,
    fee_bps: float,
    reason: str,
    failures: dict[str, str],
) -> FunctionResult:
    """Honest live-mode outage: no cells, no template values, explicit reason."""
    warnings = [reason] + [_failure_warning(sym, why) for sym, why in failures.items()]
    return FunctionResult(
        code="BMTX",
        instrument=instrument,
        data={
            "status": "provider_unavailable",
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
                "source_mode": "live_unavailable",
            },
            "next_actions": [
                "Check that the live OHLCV provider is configured and reachable.",
                "Verify that each requested symbol is a valid ticker for that provider.",
            ],
            "methodology": "No backtest was run: live OHLCV history was unavailable, and no substitute history is used.",
        },
        sources=["yfinance"],
        warnings=warnings,
        metadata={"days": days, "fee_bps": fee_bps, "live": True,
                  "provider_errors": [reason], "unavailable_symbols": list(failures) or list(symbols)},
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
