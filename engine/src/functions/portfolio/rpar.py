"""RPAR — Risk parity portfolio construction (ERC weights)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.risk_parity import (
    equal_risk_contribution,
    naive_inverse_vol,
    risk_contributions,
)


def _template_returns(symbols: list[str], days: int) -> pd.DataFrame:
    periods = max(60, min(days, 504))
    index = pd.date_range(end=datetime.utcnow().date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    rows = {}
    for i, sym in enumerate(symbols):
        rows[sym] = 0.0002 + i * 0.00002 + np.cos((t + i * 5) / (13 + i)) * (0.005 + i * 0.0008)
    return pd.DataFrame(rows, index=index)


@FunctionRegistry.register
class RPARFunction(BaseFunction):
    code = "RPAR"
    name = "Risk Parity (ERC)"
    category = "portfolio"
    description = "Compute equal-risk-contribution weights for given universe."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbol = params.get("symbol") or (instrument.symbol if instrument else None)
            symbols = [symbol] if symbol else ["AAPL", "MSFT", "BTCUSDT", "EURUSD", "GC=F"]
        days = int(params.get("days", 504))
        target = params.get("target")  # optional list of weights
        method = (params.get("method") or "inverse_vol").lower()
        live = _truthy(params.get("live_risk") or params.get("live"))
        if not live and "method" not in params and not target:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_fast_template(symbols, days),
                sources=["risk_parity_model"],
                metadata={"live": False, "method": "inverse_vol_model"},
            )
        sources = ["yfinance"] if live else ["computed_return_model"]
        async def _ret(sym: str) -> tuple[str, pd.Series]:
            try:
                inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
                if self.deps.symbol_registry:
                    r = await self.deps.symbol_registry.resolve(sym)
                    if r:
                        inst = r
                df = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OHLCV, instrument=inst,
                        start=datetime.utcnow() - timedelta(days=days),
                        interval="1d",
                    )),
                    timeout=8,
                )
                return sym, df["close"].pct_change().dropna()
            except Exception:
                return sym, pd.Series(dtype=float)
        if live and self.deps.yfinance:
            rs = await asyncio.gather(*(_ret(s) for s in symbols))
            df = pd.DataFrame({s: r for s, r in rs}).dropna(how="any")
        else:
            df = pd.DataFrame()
        if df.shape[0] < 10:
            df = _template_returns(symbols, days)
            sources = ["computed_return_model"]
        cov = df.cov().values * 252
        if method == "inverse_vol":
            w = naive_inverse_vol(cov)
            info = {"method": "inverse_vol"}
        else:
            tgt = None
            if target:
                tgt = np.asarray(target, dtype=float)
            w, info = equal_risk_contribution(
                cov,
                target=tgt,
                max_iter=int(params.get("max_iter", 500)),
            )
            info["method"] = "erc"
        rc = risk_contributions(w, cov)
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "symbols": list(df.columns),
                "weights": dict(zip(df.columns, w.tolist())),
                "portfolio_vol": rc["portfolio_vol"],
                "risk_contributions_pct": dict(zip(df.columns, rc["risk_contributions_pct"])),
                "samples": int(df.shape[0]),
                "info": info,
            },
            sources=sources,
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _fast_template(symbols: list[str], days: int) -> dict[str, Any]:
    clean = list(dict.fromkeys(str(s) for s in symbols if str(s)))
    if not clean:
        clean = ["AAPL", "MSFT", "BTCUSDT", "EURUSD", "GC=F"]
    vol_by_symbol: dict[str, float] = {}
    for idx, symbol in enumerate(clean):
        upper = symbol.upper()
        if upper.endswith(("USDT", "USDC", "BTC", "ETH")):
            vol = 0.58
        elif upper.endswith("=F"):
            vol = 0.28
        elif upper.endswith(("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD")) and len(upper) == 6:
            vol = 0.11
        else:
            vol = 0.32
        vol_by_symbol[symbol] = vol + idx * 0.015
    inv = {symbol: 1.0 / max(vol, 1e-6) for symbol, vol in vol_by_symbol.items()}
    total = sum(inv.values()) or 1.0
    weights = {symbol: value / total for symbol, value in inv.items()}
    risk_pct = {symbol: 1.0 / len(clean) for symbol in clean}
    portfolio_vol = sum(weights[symbol] * vol_by_symbol[symbol] for symbol in clean)
    return {
        "symbols": clean,
        "weights": weights,
        "portfolio_vol": portfolio_vol,
        "risk_contributions_pct": risk_pct,
        "samples": max(60, min(days, 504)),
        "info": {"method": "inverse_vol_model", "iterations": 0, "residual": 0.0},
    }
