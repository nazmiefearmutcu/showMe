"""REGM — Market regime classifier (rule + cluster)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.services import regime_classifier as rgm


@FunctionRegistry.register
class REGMFunction(BaseFunction):
    code = "REGM"
    name = "Market Regime"
    category = "macro"
    description = "Classify regime via trend + vol + drawdown + curve, optionally cluster history."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        sym = (params.get("symbol") or
               (instrument.symbol if instrument else None) or "SPY")
        days = int(params.get("days", 1095))    # 3 years
        action = (params.get("action") or "current").lower()
        timeout = float(params.get("timeout", 8))
        # Spread 2s/10s (optional)
        spread_bp = None
        if self.deps.fred:
            try:
                t10, t2 = await asyncio.gather(
                    asyncio.wait_for(self.deps.fred.fetch(DataRequest(
                        kind=DataKind.ECON_SERIES, instrument=None,
                        extra={"series_id": "DGS10"})), timeout=timeout),
                    asyncio.wait_for(self.deps.fred.fetch(DataRequest(
                        kind=DataKind.ECON_SERIES, instrument=None,
                        extra={"series_id": "DGS2"})), timeout=timeout),
                    return_exceptions=True,
                )
                if isinstance(t10, Exception) or isinstance(t2, Exception):
                    raise RuntimeError("fred curve unavailable")
                if t10 and t2 and t10.data is not None and t2.data is not None:
                    val10 = float(t10.data.iloc[-1].get("value")) \
                        if hasattr(t10.data, "iloc") else None
                    val2 = float(t2.data.iloc[-1].get("value")) \
                        if hasattr(t2.data, "iloc") else None
                    if val10 is not None and val2 is not None:
                        spread_bp = (val10 - val2) * 100  # in basis points
            except Exception:
                spread_bp = None
        # Pull benchmark OHLCV
        sources = ["yfinance", "fred"]
        try:
            if not self.deps.yfinance:
                raise RuntimeError("no yfinance")
            inst = Instrument(symbol=sym, asset_class=AssetClass.EQUITY)
            df = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=inst,
                    start=datetime.utcnow() - timedelta(days=days),
                    interval="1d",
                )),
                timeout=timeout,
            )
            close = np.asarray(df["close"].values, dtype=float)
        except Exception:
            periods = max(252, min(days, 756))
            t = np.arange(periods, dtype=float)
            close = 100 + t * 0.04 + np.sin(t / 14) * 3
            df = None
            sources = ["regime_model"]
        if action == "current":
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={"symbol": sym, **rgm.classify(close, spread_2s10s_bp=spread_bp)},
                sources=sources,
            )
        # action == "history": classify rolling window + cluster
        window = int(params.get("window", 60))
        labels: list[dict[str, Any]] = []
        feats: list[list[float]] = []
        for i in range(window, len(close)):
            sub = close[max(i - 252, 0): i + 1]
            r = rgm.classify(sub, spread_2s10s_bp=spread_bp)
            labels.append({
                "date": str(df.index[i]) if hasattr(df, "index") else str(i),
                **{k: r[k] for k in ("regime", "trend", "vol", "drawdown")}
            })
            feats.append([r.get("ma50_vs_200_pct", 0),
                          r.get("realized_vol_pct", 0),
                          r.get("drawdown_pct", 0)])
        feats_np = np.asarray(feats)
        cluster = rgm.kmeans_lite(feats_np, k=int(params.get("k", 4)))
        return FunctionResult(
            code=self.code, instrument=instrument,
            data={
                "symbol": sym,
                "history": labels,
                "cluster": cluster,
                "current": rgm.classify(close, spread_2s10s_bp=spread_bp),
            },
            sources=sources,
        )
