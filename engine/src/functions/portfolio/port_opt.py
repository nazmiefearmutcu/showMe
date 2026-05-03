"""PORT_OPT — Markowitz portfolio optimizer (multiple solver modes)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.optimizer import (
    efficient_frontier, max_sharpe, min_volatility, risk_parity,
)


@FunctionRegistry.register
class PortOptFunction(BaseFunction):
    code = "PORT_OPT"
    name = "Portfolio Optimizer"
    category = "portfolio"
    description = "Markowitz min-vol / max-Sharpe / risk-parity / efficient frontier."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols: list[str] = params.get("symbols") or [
            "SPY", "QQQ", "IWM", "TLT", "GLD", "EFA", "EEM", "VNQ", "DBC",
        ]
        days = int(params.get("days", 365 * 3))
        mode = (params.get("mode") or "frontier").lower()
        rf = float(params.get("risk_free", 0.04))
        allow_short = bool(params.get("allow_short", False))
        live = _truthy(params.get("live_optimization") or params.get("live_returns") or params.get("live"))
        async def _ret(s: str) -> tuple[str, pd.Series]:
            try:
                if not self.deps.yfinance:
                    raise RuntimeError("no yfinance")
                inst = await self.deps.symbol_registry.resolve(s) if self.deps.symbol_registry else None
                if not inst:
                    inst = Instrument(symbol=s, asset_class=AssetClass.EQUITY)
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=inst,
                        start=datetime.utcnow() - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=float(params.get("quote_timeout", 8)),
                )
                return s, df["close"].pct_change().dropna()
            except Exception:
                return s, pd.Series(dtype=float)
        if live and self.deps.yfinance:
            results = await asyncio.gather(*(_ret(s) for s in symbols))
            rets = pd.DataFrame({s: r for s, r in results}).dropna(how="any")
        else:
            rets = pd.DataFrame()
        if rets.empty or len(rets.columns) < 2:
            from src.functions.portfolio.rpar import _template_returns
            rets = _template_returns(symbols, days)
            sources = ["computed_return_model"]
        else:
            sources = ["yfinance"]
        out: dict[str, Any] = {"symbols": list(rets.columns), "samples": int(len(rets))}
        if mode in ("frontier", "all"):
            ef = efficient_frontier(rets, allow_short=allow_short, risk_free=rf)
            out["efficient_frontier"] = [
                {"return": p.expected_return, "vol": p.volatility,
                 "sharpe": p.sharpe, "weights": p.weights} for p in ef
            ]
        if mode in ("max_sharpe", "all"):
            ms = max_sharpe(rets, risk_free=rf, allow_short=allow_short)
            out["max_sharpe"] = {
                "weights": ms.weights, "return": ms.expected_return,
                "vol": ms.volatility, "sharpe": ms.sharpe,
            }
        if mode in ("min_vol", "all"):
            mv = min_volatility(rets, allow_short=allow_short)
            out["min_volatility"] = {
                "weights": mv.weights, "return": mv.expected_return,
                "vol": mv.volatility, "sharpe": mv.sharpe,
            }
        if mode in ("risk_parity", "all"):
            rp = risk_parity(rets)
            out["risk_parity"] = {
                "weights": rp.weights, "return": rp.expected_return,
                "vol": rp.volatility, "sharpe": rp.sharpe,
            }
        return FunctionResult(code=self.code, instrument=None, data=out,
                              sources=sources,
                              metadata={"mode": mode, "days": days,
                                         "risk_free": rf,
                                         "allow_short": allow_short,
                                         "live": live})


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
