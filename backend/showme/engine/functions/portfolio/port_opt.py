"""PORT_OPT — Markowitz portfolio optimizer (multiple solver modes)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.return_series import align_return_series, close_to_daily_returns
from showme.engine.services.optimizer import (
    efficient_frontier, max_sharpe, min_volatility, risk_parity,
)


@FunctionRegistry.register
class PortOptFunction(BaseFunction):
    code = "PORT_OPT"
    name = "Portfolio Optimizer"
    category = "portfolio"
    description = "Markowitz min-vol / max-Sharpe / risk-parity / efficient frontier."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        # Fix A7-C3: GET ?symbols=AAPL,MSFT,NVDA arrives as a string and used
        # to iterate character-by-character into ["A","P","S"]. Mirror the
        # guard BLAK/RPAR already implement.
        symbols = params.get("symbols") or [
            "SPY", "QQQ", "IWM", "TLT", "GLD", "EFA", "EEM", "VNQ", "DBC",
        ]
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
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
                        start=datetime.now(timezone.utc) - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=float(params.get("quote_timeout", 8)),
                )
                return s, close_to_daily_returns(df)
            except Exception:
                return s, pd.Series(dtype=float)
        if live and self.deps.yfinance:
            results = await asyncio.gather(*(_ret(s) for s in symbols))
            rets = align_return_series(results)
        else:
            rets = pd.DataFrame()
        if rets.empty or len(rets.columns) < 2:
            from showme.engine.functions.portfolio.rpar import _template_returns
            rets = _template_returns(symbols, days)
            sources = ["computed_return_model"]
        else:
            sources = ["yfinance"]
        out: dict[str, Any] = {"symbols": list(rets.columns), "samples": int(len(rets))}
        if mode in ("frontier", "all"):
            ef = efficient_frontier(rets, allow_short=allow_short, risk_free=rf)
            out["efficient_frontier"] = [
                {"label": f"vol {p.volatility:.2%}", "return": p.expected_return, "vol": p.volatility,
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
        weight_rows: list[dict[str, Any]] = []
        for section in ("max_sharpe", "min_volatility", "risk_parity"):
            result = out.get(section)
            if not isinstance(result, dict):
                continue
            weights = result.get("weights") or {}
            if not isinstance(weights, dict):
                continue
            for symbol, weight in weights.items():
                weight_rows.append({
                    "label": f"{section}:{symbol}",
                    "mode": section,
                    "symbol": symbol,
                    "weight": float(weight),
                    "weight_pct": float(weight) * 100,
                    "return": result.get("return"),
                    "vol": result.get("vol"),
                    "sharpe": result.get("sharpe"),
                })
        if weight_rows:
            out["rows"] = weight_rows
        out["summary"] = {
            "mode": mode,
            "symbols": len(rets.columns),
            "samples": int(len(rets)),
            "risk_free": rf,
            "allow_short": allow_short,
        }
        out["methodology"] = (
            "Estimate daily return covariance and annualized expected returns for the selected universe. "
            "The efficient frontier plots volatility on the x-axis and expected return on the y-axis; "
            "optimizer modes compute max-Sharpe, min-volatility, and risk-parity weights."
        )
        out["field_dictionary"] = {
            "vol": "Annualized portfolio volatility.",
            "return": "Annualized expected portfolio return.",
            "sharpe": "(return - risk_free_rate) / volatility.",
            "weight_pct": "Optimizer allocation weight for a symbol.",
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
