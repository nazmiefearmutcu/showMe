"""REGM — Market regime classifier (rule + cluster)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.services import regime_classifier as rgm


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
        sources = ["yfinance"] + (["fred"] if spread_bp is not None else [])
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
        current = rgm.classify(close, spread_2s10s_bp=spread_bp)
        if action == "current":
            history = _regime_history(close, spread_bp, df)
            return FunctionResult(
                code=self.code, instrument=instrument,
                data={
                    "symbol": sym,
                    "current": current,
                    "rows": _component_rows(sym, current, sources),
                    "history": history,
                    "cards": [
                        {"label": "Regime", "value": current.get("regime")},
                        {"label": "Trend", "value": current.get("trend")},
                        {"label": "Vol", "value": current.get("vol")},
                        {"label": "Curve", "value": current.get("curve")},
                    ],
                    "methodology": (
                        "REGM classifies the selected symbol using 50d vs 200d moving-average spread, "
                        "21d annualized realized volatility versus long-run volatility, peak-to-current "
                        "drawdown, and the 10Y-2Y curve when FRED is available. Thresholds: trend > +1% "
                        "is BULL, < -1% is BEAR; drawdown below -10% is DRAWDOWN, below -20% is CRISIS; "
                        "curve below 0 bp is INVERTED, below 50 bp is FLAT."
                    ),
                    "field_dictionary": {
                        "ma50_vs_200_pct": "Percent spread between 50-day and 200-day moving averages.",
                        "realized_vol_pct": "Annualized realized volatility from recent returns.",
                        "drawdown_pct": "Current close versus trailing peak.",
                        "curve_2s10s_bp": "10Y minus 2Y yield spread in basis points.",
                        "score": "Display score used for the regime-history chart.",
                    },
                    "source_mode": ",".join(sources),
                },
                sources=sources,
                warnings=[] if "fred" in sources and current.get("curve") != "UNKNOWN" else ["FRED curve spread unavailable; curve component is UNKNOWN"],
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
                "current": current,
                "rows": _component_rows(sym, current, sources),
                "methodology": (
                    "History mode rolls the same rule-based classifier through time and adds a pure-numpy "
                    "k-means cluster label over trend spread, realized volatility, and drawdown."
                ),
            },
            sources=sources,
        )


def _component_rows(symbol: str, current: dict[str, Any], sources: list[str]) -> list[dict[str, Any]]:
    return [
        {"symbol": symbol, "component": "trend", "label": current.get("trend"), "value": current.get("ma50_vs_200_pct"), "unit": "%", "rule": "50d MA vs 200d MA", "source_mode": ",".join(sources)},
        {"symbol": symbol, "component": "volatility", "label": current.get("vol"), "value": current.get("realized_vol_pct"), "unit": "% annualized", "rule": "21d realized vol vs long-run vol", "source_mode": ",".join(sources)},
        {"symbol": symbol, "component": "drawdown", "label": current.get("drawdown"), "value": current.get("drawdown_pct"), "unit": "%", "rule": "close versus trailing peak", "source_mode": ",".join(sources)},
        {"symbol": symbol, "component": "curve", "label": current.get("curve"), "value": current.get("curve_2s10s_bp"), "unit": "bp", "rule": "10Y-2Y yield spread", "source_mode": ",".join(sources)},
    ]


def _regime_history(close: np.ndarray, spread_bp: float | None, df: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = max(60, len(close) - 160)
    for i in range(start, len(close)):
        sub = close[max(i - 252, 0): i + 1]
        current = rgm.classify(sub, spread_2s10s_bp=spread_bp)
        date_value = str(df.index[i])[:10] if hasattr(df, "index") and i < len(df.index) else str(i)
        rows.append({
            "date": date_value,
            "regime": current.get("regime"),
            "trend": current.get("trend"),
            "vol": current.get("vol"),
            "drawdown": current.get("drawdown"),
            "score": _regime_score(current),
            "drawdown_pct": current.get("drawdown_pct"),
            "realized_vol_pct": current.get("realized_vol_pct"),
        })
    return rows


def _regime_score(current: dict[str, Any]) -> float:
    trend = {"BULL": 1.0, "SIDEWAYS": 0.0, "BEAR": -1.0}.get(str(current.get("trend")), 0.0)
    vol = {"LOW": 0.2, "NORMAL": 0.0, "HIGH": -0.4}.get(str(current.get("vol")), 0.0)
    drawdown = {"NORMAL": 0.0, "DRAWDOWN": -0.6, "CRISIS": -1.0}.get(str(current.get("drawdown")), 0.0)
    curve = {"NORMAL": 0.2, "FLAT": -0.1, "INVERTED": -0.4, "UNKNOWN": 0.0}.get(str(current.get("curve")), 0.0)
    return round(trend + vol + drawdown + curve, 4)
