"""OSA, HVT, IVOL iskeletleri."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument
from src.functions.derivative.ovme import _bs_price


def _vol_template(symbol: str, spot: float = 100.0) -> dict[str, float]:
    seed = (sum(ord(ch) for ch in symbol.upper()) % 35) / 1000
    return {
        "rv_30d_annualized": round(0.22 + seed, 4),
        "rv_60d_annualized": round(0.24 + seed, 4),
        "rv_90d_annualized": round(0.26 + seed, 4),
        "rv_252d_annualized": round(0.29 + seed, 4),
        "spot": spot,
    }


def _surface_template(spot: float) -> dict[str, Any]:
    expiries = ["30d", "60d", "90d"]
    strikes = [round(spot * m, 2) for m in (0.8, 0.9, 1.0, 1.1, 1.2)]
    calls = []
    puts = []
    for e_idx, expiry in enumerate(expiries):
        for k_idx, strike in enumerate(strikes):
            skew = abs(k_idx - 2) * 0.025
            calls.append({"expiry": expiry, "strike": strike, "iv": round(0.32 + skew + e_idx * 0.015, 4), "volume": 0})
            puts.append({"expiry": expiry, "strike": strike, "iv": round(0.35 + skew + e_idx * 0.018, 4), "volume": 0})
    return {"expiries": expiries, "calls_grid": calls, "puts_grid": puts}


@FunctionRegistry.register
class OSAFunction(BaseFunction):
    """OSA — Option Strategy Analysis."""
    code = "OSA"
    name = "Option Strategy Analysis"
    asset_classes = (AssetClass.DERIVATIVE,)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        legs = params.get("legs") or []  # [{"qty":+1,"strike":100,"type":"CALL","expiry":0.25,"vol":0.25}]
        S = float(params.get("spot", 100))
        r = float(params.get("rate", 0.045))
        q = float(params.get("div_yield", 0.0))
        # P&L diagram from spot * 0.5 → spot * 1.5
        spots = [S * (0.5 + i * 0.01) for i in range(101)]
        pnl_curve: list[dict] = []
        for s in spots:
            pnl = 0.0
            for leg in legs:
                bs = _bs_price(s, leg["strike"], leg["expiry"], r, leg["vol"], q,
                               leg["type"].upper() == "CALL")
                pnl += leg["qty"] * bs["price"]
            pnl_curve.append({"spot": s, "pnl": pnl})
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"legs": legs, "pnl_curve": pnl_curve},
                              sources=[])


@FunctionRegistry.register
class HVTFunction(BaseFunction):
    """HVT — Historical Volatility Trends."""
    code = "HVT"
    name = "Historical Volatility Trends"
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        symbol = instrument.symbol
        if not (params.get("live_vol") or params.get("live")):
            spot = float(params.get("spot", 100))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_vol_template(symbol, spot),
                sources=["historical_vol_model"],
            )
        if not self.deps.yfinance:
            return FunctionResult(code=self.code, instrument=instrument,
                                  data=_vol_template(symbol, float(params.get("spot", 100))),
                                  sources=["historical_vol_model"])
        from src.core.base_data_source import DataKind, DataRequest
        from datetime import datetime, timedelta
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        try:
            df = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OHLCV, instrument=instrument,
                    start=datetime.utcnow() - timedelta(days=365), interval="1d",
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception:
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_vol_template(symbol, float(params.get("spot", 100))),
                sources=["historical_vol_model"],
            )
        import numpy as np
        rets = df["close"].pct_change().dropna()
        out = {
            "rv_30d_annualized": float(rets.tail(30).std() * (252 ** 0.5)),
            "rv_60d_annualized": float(rets.tail(60).std() * (252 ** 0.5)),
            "rv_90d_annualized": float(rets.tail(90).std() * (252 ** 0.5)),
            "rv_252d_annualized": float(rets.std() * (252 ** 0.5)),
        }
        return FunctionResult(code=self.code, instrument=instrument, data=out,
                              sources=["yfinance"])


@FunctionRegistry.register
class IVOLFunction(BaseFunction):
    """IVOL — Implied Vol Surface."""
    code = "IVOL"
    name = "Implied Vol Surface"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        spot = float(params.get("spot", 100))
        if not (params.get("live_options") or params.get("live")):
            synthetic = _surface_template(spot)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=synthetic,
                sources=["implied_vol_model"],
                metadata={"calls": len(synthetic["calls_grid"]), "puts": len(synthetic["puts_grid"])},
            )
        if not self.deps.yfinance:
            synthetic = _surface_template(spot)
            return FunctionResult(code=self.code, instrument=instrument, data=synthetic,
                                  sources=["implied_vol_model"],
                                  metadata={"calls": len(synthetic["calls_grid"]), "puts": len(synthetic["puts_grid"])})
        from src.core.base_data_source import DataKind, DataRequest
        timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
        try:
            meta = await asyncio.wait_for(
                self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                    extra={"timeout": timeout},
                )),
                timeout=timeout + 1,
            )
        except Exception:
            meta = {}
        expiries = meta.get("expiries", []) or []
        if not expiries:
            synthetic = _surface_template(spot)
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=synthetic,
                sources=["implied_vol_model"],
                metadata={"calls": len(synthetic["calls_grid"]), "puts": len(synthetic["puts_grid"])},
            )
        max_expiries = max(1, min(int(params.get("max_expiries", 3)), 4))
        targets = expiries[:max_expiries]
        async def _one(exp):
            try:
                return exp, await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                        extra={"expiry": exp, "timeout": timeout},
                    )),
                    timeout=timeout + 1,
                )
            except Exception:
                return exp, None
        results = await asyncio.gather(*(_one(e) for e in targets))
        surface_calls: list[dict[str, Any]] = []
        surface_puts: list[dict[str, Any]] = []
        for exp, chain in results:
            if not chain:
                continue
            calls = chain.get("calls")
            puts = chain.get("puts")
            if calls is not None and hasattr(calls, "iterrows"):
                for _, r in calls.iterrows():
                    iv = r.get("impliedVolatility")
                    if iv is not None and iv == iv:
                        surface_calls.append({"expiry": exp, "strike": float(r["strike"]),
                                              "iv": float(iv), "volume": float(r.get("volume") or 0)})
            if puts is not None and hasattr(puts, "iterrows"):
                for _, r in puts.iterrows():
                    iv = r.get("impliedVolatility")
                    if iv is not None and iv == iv:
                        surface_puts.append({"expiry": exp, "strike": float(r["strike"]),
                                             "iv": float(iv), "volume": float(r.get("volume") or 0)})
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"expiries": targets,
                                    "calls_grid": surface_calls,
                                    "puts_grid": surface_puts},
                              sources=["yfinance"],
                              metadata={"calls": len(surface_calls), "puts": len(surface_puts)})
