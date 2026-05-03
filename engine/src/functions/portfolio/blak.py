"""BLAK — Black-Litterman expected returns + implied portfolio."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services.black_litterman import (
    implied_optimal_weights,
    implied_returns,
    posterior,
)


def _template_returns(symbols: list[str], days: int) -> pd.DataFrame:
    periods = max(60, min(days, 504))
    index = pd.date_range(end=datetime.utcnow().date(), periods=periods, freq="B")
    periods = len(index)
    t = np.arange(periods, dtype=float)
    rows = {}
    for i, sym in enumerate(symbols):
        rows[sym] = 0.00025 + i * 0.00003 + np.sin((t + i * 7) / (11 + i)) * (0.006 + i * 0.001)
    return pd.DataFrame(rows, index=index)


@FunctionRegistry.register
class BLAKFunction(BaseFunction):
    code = "BLAK"
    name = "Black-Litterman"
    category = "portfolio"
    description = "Posterior expected returns combining market prior with views."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        symbols = params.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=["symbols required"])
        days = int(params.get("days", 504))
        delta = float(params.get("delta", 2.5))
        tau = float(params.get("tau", 0.05))
        market_caps = params.get("market_caps") or {}  # symbol → mcap
        views = params.get("views") or []
        live = _truthy(params.get("live_returns") or params.get("live"))
        sources = ["yfinance"] if live else ["computed_return_model"]
        async def _ret(sym: str) -> tuple[str, pd.Series, float]:
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
                rets = df["close"].pct_change().dropna()
                # Market cap proxy: last close × volume_avg, or override.
                mcap = float(market_caps.get(sym) or 0)
                if not mcap:
                    try:
                        mcap = float(df["close"].iloc[-1] * df["volume"].mean())
                    except Exception:
                        mcap = 1.0
                return sym, rets, mcap
            except Exception:
                return sym, pd.Series(dtype=float), 0.0
        if live and self.deps.yfinance:
            results = await asyncio.gather(*(_ret(s) for s in symbols))
            rets_dict = {s: r for s, r, _ in results}
            df = pd.DataFrame(rets_dict).dropna(how="any")
        else:
            results = [(s, pd.Series(dtype=float), 1.0) for s in symbols]
            df = pd.DataFrame()
        if df.shape[0] < 10:
            df = _template_returns(symbols, days)
            results = [(s, pd.Series(dtype=float), float(i + 1)) for i, s in enumerate(symbols)]
            sources = ["computed_return_model"]
        cov = df.cov().values * 252
        cols = list(df.columns)
        mcaps = np.array([next((m for s, _, m in results if s == c), 0.0) for c in cols])
        if mcaps.sum() <= 0:
            mcaps = np.ones(len(cols))
        w_mkt = mcaps / mcaps.sum()
        pi = implied_returns(cov, w_mkt, delta=delta)
        # Build P / Q from views: list of {"long":[...], "short":[...], "expected":0.05}
        P_rows: list[list[float]] = []
        Q: list[float] = []
        for v in views:
            row = [0.0] * len(cols)
            longs = v.get("long", [])
            shorts = v.get("short", [])
            for s in longs:
                if s in cols:
                    row[cols.index(s)] = 1.0 / max(len(longs), 1)
            for s in shorts:
                if s in cols:
                    row[cols.index(s)] = -1.0 / max(len(shorts), 1)
            if any(x != 0 for x in row):
                P_rows.append(row)
                Q.append(float(v.get("expected", 0.05)))
        P = np.asarray(P_rows) if P_rows else None
        Qv = np.asarray(Q) if Q else None
        pi_bl, sigma_bl = posterior(cov, w_mkt, P, Qv, delta=delta, tau=tau)
        w_opt = implied_optimal_weights(pi_bl, sigma_bl, delta=delta)
        return FunctionResult(
            code=self.code, instrument=None,
            data={
                "symbols": cols,
                "market_weights": dict(zip(cols, w_mkt.tolist())),
                "implied_returns_prior": dict(zip(cols, pi.tolist())),
                "posterior_returns": dict(zip(cols, pi_bl.tolist())),
                "implied_optimal_weights": dict(zip(cols, w_opt.tolist())),
                "delta": delta, "tau": tau,
                "n_views": len(P_rows),
                "samples": int(df.shape[0]),
            },
            sources=sources,
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
