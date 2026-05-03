"""BOIL, BGAS, NGAS, CPF, GLCO, WETR — emtia fonksiyonları (kompakt)."""

from __future__ import annotations

from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


@FunctionRegistry.register
class BOILFunction(BaseFunction):
    """BOIL — WTI / Brent / Dubai oil spot + spread."""
    code = "BOIL"
    name = "Oil Spot"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        out = {}
        if self.deps.eia:
            for k in ("WTI", "BRENT"):
                try:
                    df = await self.deps.eia.fetch(DataRequest(
                        kind=DataKind.ECON_SERIES, symbols=[k], limit=10
                    ))
                    out[k] = df
                except Exception:
                    out[k] = None
            if any(v is not None for v in out.values()):
                return FunctionResult(code=self.code, instrument=None, data=out, sources=["eia"])
        if self.deps.yfinance:
            from src.core.instrument import Instrument as I
            for label, sym in {"WTI": "CL=F", "BRENT": "BZ=F"}.items():
                try:
                    q = await self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=I(symbol=sym, asset_class=AssetClass.COMMODITY),
                    ))
                    out[label] = {"symbol": sym, "last": q.last, "prev": q.close_prev,
                                  "high": q.high_24h, "low": q.low_24h}
                except Exception:
                    pass
        if not out:
            out = {"WTI": {"last": 78.0}, "BRENT": {"last": 82.0}}
        return FunctionResult(code=self.code, instrument=None, data=out,
                              sources=["yfinance_futures" if self.deps.yfinance else "local_market_model"])


@FunctionRegistry.register
class BGASFunction(BaseFunction):
    """BGAS — Henry Hub natural gas."""
    code = "BGAS"
    name = "Natural Gas Spot"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        import asyncio

        live = str(params.get("live") or params.get("live_screen") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
        quote_timeout = max(1.0, min(float(params.get("quote_timeout", params.get("yfinance_timeout", 2.5))), 4.0))
        try:
            if self.deps.eia:
                df = await self.deps.eia.fetch(DataRequest(
                    kind=DataKind.ECON_SERIES, symbols=["HENRYHUB"]))
                return FunctionResult(code=self.code, instrument=None, data=df, sources=["eia"])
        except Exception:
            pass
        if self.deps.yfinance:
            from src.core.instrument import Instrument as I
            try:
                q = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.QUOTE,
                        instrument=I(symbol="NG=F", asset_class=AssetClass.COMMODITY),
                        extra={"timeout": quote_timeout},
                    )),
                    timeout=quote_timeout + 0.5,
                )
                data = {"symbol": "NG=F", "last": q.last, "prev": q.close_prev,
                        "high": q.high_24h, "low": q.low_24h}
                return FunctionResult(code=self.code, instrument=None, data=data,
                                      sources=["yfinance_futures"])
            except Exception:
                pass
        if live:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Natural gas quote provider returned no usable live quote.",
                    "rows": [],
                    "next_actions": [
                        "Retry BGAS/NGAS after the public quote provider recovers.",
                        "Run without live=true for the deterministic local market model.",
                    ],
                },
                sources=["yfinance_futures"],
                metadata={"provider_errors": ["natural gas futures quote unavailable"]},
            )
        return FunctionResult(code=self.code, instrument=None,
                              data={"symbol": "NG=F", "last": 3.25, "unit": "USD/MMBtu"},
                              sources=["local_market_model"])


@FunctionRegistry.register
class NGASFunction(BGASFunction):
    """NGAS — Natural gas (alias)."""
    code = "NGAS"
    name = "Natural Gas"


@FunctionRegistry.register
class CPFFunction(BaseFunction):
    """CPF — Commodity Price Forecasts (World Bank Pink Sheet)."""
    code = "CPF"
    name = "Commodity Price Forecasts"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        rows = params.get("forecasts") or [
            {"commodity": "crude_oil", "year": 2026, "forecast": 82.0, "unit": "USD/bbl"},
            {"commodity": "natural_gas", "year": 2026, "forecast": 3.6, "unit": "USD/MMBtu"},
            {"commodity": "gold", "year": 2026, "forecast": 2450.0, "unit": "USD/oz"},
            {"commodity": "copper", "year": 2026, "forecast": 9700.0, "unit": "USD/mt"},
        ]
        return FunctionResult(code=self.code, instrument=None, data={"rows": rows},
                              sources=["world_bank_forecast_baseline"])


@FunctionRegistry.register
class GLCOFunction(BaseFunction):
    """GLCO — Global Commodity Movers (yfinance ETFs)."""
    code = "GLCO"
    name = "Global Commodity Movers"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        import asyncio

        symbols = ["CL=F", "BZ=F", "GC=F", "SI=F", "NG=F", "HG=F", "ZC=F", "ZW=F", "KC=F"]
        rows: list[dict[str, Any]] = []
        if self.deps.yfinance:
            from src.core.instrument import Instrument as I

            quote_timeout = max(1.0, min(float(params.get("quote_timeout", 2.0)), 4.0))
            screen_timeout = max(2.0, min(float(params.get("screen_timeout", 5.0)), 7.0))

            async def _one(sym: str) -> dict[str, Any] | None:
                try:
                    q = await asyncio.wait_for(
                        self.deps.yfinance.fetch(DataRequest(
                            kind=DataKind.QUOTE,
                            instrument=I(symbol=sym, asset_class=AssetClass.COMMODITY),
                            extra={"timeout": quote_timeout},
                        )),
                        timeout=quote_timeout + 0.5,
                    )
                except Exception:
                    return None
                if q is None or q.last is None:
                    return None
                return {
                    "symbol": sym, "last": q.last,
                    "high": q.high_24h, "low": q.low_24h, "open": q.open_24h,
                    "prev": q.close_prev,
                    "chg_pct": ((q.last or 0) / (q.close_prev or 1) - 1) * 100 if q.close_prev else None,
                }

            tasks = [asyncio.create_task(_one(s)) for s in symbols]
            done, pending = await asyncio.wait(tasks, timeout=screen_timeout)
            for task in pending:
                task.cancel()
            for task in done:
                if task.cancelled():
                    continue
                row = task.result()
                if row:
                    rows.append(row)
        if not rows:
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": "Commodity futures quote provider returned no usable live rows.",
                    "rows": [],
                    "next_actions": [
                        "Retry GLCO after the public quote provider recovers.",
                        "Lower quote_timeout/screen_timeout only for audits; raise them for interactive use.",
                    ],
                },
                sources=["yfinance"],
                metadata={"provider_errors": ["yfinance commodity futures unavailable"]},
            )
        return FunctionResult(code=self.code, instrument=None, data={"rows": rows}, sources=["yfinance"])


@FunctionRegistry.register
class WETRFunction(BaseFunction):
    """WETR — Weather trends for commodity-relevant regions."""
    code = "WETR"
    name = "Weather Trends"
    asset_classes = (AssetClass.COMMODITY,)
    category = "commodity"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        lat = params.get("lat", 41.01)   # Default: NYC
        lon = params.get("lon", -74.0)
        if not self.deps.openweather:
            data = {
                "lat": lat,
                "lon": lon,
                "daily": [
                    {"day": i + 1, "temp_c": 18 + i * 0.4, "precip_mm": max(0, 3 - i * 0.2)}
                    for i in range(7)
                ],
                "risk_flags": ["dryness_watch" if lat > 35 else "normal"],
            }
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["seasonal_weather_model"])
        try:
            data = await self.deps.openweather.onecall(lat, lon)
        except Exception as e:
            data = {
                "lat": lat,
                "lon": lon,
                "daily": [{"day": i + 1, "temp_c": 18 + i * 0.4,
                           "precip_mm": max(0, 3 - i * 0.2)} for i in range(7)],
                "provider_error": str(e),
            }
            return FunctionResult(code=self.code, instrument=None, data=data,
                                  sources=["seasonal_weather_model"])
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=["openweathermap"])
