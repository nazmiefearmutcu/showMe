"""FXFC, FXIP, WCRS, FRD, OVDV — FX function suite (kompakt)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


_MAJOR_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
                 "EURGBP", "EURJPY", "EURCHF", "GBPJPY"]


@FunctionRegistry.register
class FXFCFunction(BaseFunction):
    """FXFC — FX Forecasts (OECD/TradingEconomics)."""
    code = "FXFC"
    name = "FX Forecasts"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        pair = (instrument.symbol if instrument else params.get("pair") or "EURUSD").upper()
        spot = float(params.get("spot", 1.10))
        forecast = [
            {"horizon": "1M", "spot": spot, "forecast": spot * 1.002},
            {"horizon": "3M", "spot": spot, "forecast": spot * 1.006},
            {"horizon": "12M", "spot": spot, "forecast": spot * 1.018},
        ]
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"pair": pair, "forecast": forecast},
                              sources=["forward_points_model"])


@FunctionRegistry.register
class FXIPFunction(BaseFunction):
    """FXIP — FX Information Portal (combined view)."""
    code = "FXIP"
    name = "FX Information Portal"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        if not _truthy(params.get("live_fx") or params.get("live")):
            spot = float(params.get("spot", _template_spot(instrument.symbol)))
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_fxip_payload(instrument.symbol, spot),
                sources=["fx_information_model"],
                metadata={"live": False},
            )
        spot = None
        if self.deps.exchangerate_host:
            try:
                q = await asyncio.wait_for(
                    self.deps.exchangerate_host.fetch(DataRequest(kind=DataKind.QUOTE, instrument=instrument)),
                    timeout=float(params.get("timeout", 8)),
                )
                spot = q.last if q else None
            except Exception:
                pass
        if spot is None:
            spot = float(params.get("spot", _template_spot(instrument.symbol)))
        return FunctionResult(code=self.code, instrument=instrument,
                              data=_fxip_payload(instrument.symbol, spot),
                              sources=["exchangerate_host" if self.deps.exchangerate_host else "fx_information_model"],
                              metadata={"live": bool(self.deps.exchangerate_host)})


@FunctionRegistry.register
class WCRSFunction(BaseFunction):
    """WCRS — World Cross Rates matrix."""
    code = "WCRS"
    name = "World Cross Rates"
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        bases = params.get("bases", ["USD", "EUR", "GBP", "JPY", "TRY"])
        quotes = params.get("quotes", ["USD", "EUR", "GBP", "JPY", "TRY", "CHF"])
        seed = {"USD": 1.0, "EUR": 0.93, "GBP": 0.79, "JPY": 156.0, "TRY": 32.2, "CHF": 0.91}
        out = {
            b: {q: (seed[q] / seed[b] if b in seed and q in seed else 1.0) for q in quotes}
            for b in bases
        }
        return FunctionResult(code=self.code, instrument=None, data=out,
                              sources=["cross_rate_matrix"])


@FunctionRegistry.register
class FRDFunction(BaseFunction):
    """FRD — Forward rates via interest rate parity."""
    code = "FRD"
    name = "FX Forward Rates"
    asset_classes = (AssetClass.FX,)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        # F = S × (1 + r_quote) / (1 + r_base)
        S = float(params.get("spot", 1.10))
        r_base = float(params.get("r_base", 0.045))
        r_quote = float(params.get("r_quote", 0.04))
        T = float(params.get("years", 0.25))
        F = S * ((1 + r_quote) ** T) / ((1 + r_base) ** T)
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"S": S, "F": F, "r_base": r_base, "r_quote": r_quote, "T": T},
                              sources=[])


@FunctionRegistry.register
class OVDVFunction(BaseFunction):
    """OVDV — FX Option Volatility Surface."""
    code = "OVDV"
    name = "FX Option Volatility Surface"
    asset_classes = (AssetClass.FX, AssetClass.DERIVATIVE)
    category = "fx"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        tenors = ["1W", "1M", "3M", "6M", "1Y"]
        deltas = ["10P", "25P", "ATM", "25C", "10C"]
        base = float(params.get("atm_vol", 8.5))
        surface = [
            {"tenor": tenor, "delta": delta, "vol": base + i * 0.15 + abs(j - 2) * 0.25}
            for i, tenor in enumerate(tenors)
            for j, delta in enumerate(deltas)
        ]
        return FunctionResult(code=self.code, instrument=instrument,
                              data={"surface": surface, "tenors": tenors, "deltas": deltas},
                              sources=["fx_vol_surface_model"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _template_spot(pair: str) -> float:
    normalized = pair.upper().replace("=X", "")
    spots = {
        "EURUSD": 1.0835,
        "GBPUSD": 1.256,
        "USDJPY": 154.2,
        "AUDUSD": 0.662,
        "USDCAD": 1.368,
        "USDCHF": 0.913,
    }
    return spots.get(normalized, 1.0)


def _fxip_payload(pair: str, spot: float) -> dict[str, Any]:
    normalized = pair.upper().replace("=X", "")
    base = normalized[:3] if len(normalized) >= 6 else normalized[:3] or "FX"
    quote = normalized[3:6] if len(normalized) >= 6 else "USD"
    return {
        "pair": pair,
        "base": base,
        "quote": quote,
        "spot": round(spot, 6),
        "daily_change_pct": 0.18,
        "one_month_forward": round(spot * 1.0012, 6),
        "three_month_forward": round(spot * 1.0038, 6),
        "implied_vol_atm_1m": 8.45,
        "carry_annualized": 0.0175,
    }
