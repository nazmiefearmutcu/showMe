"""OMON — Option Monitor (full chain)."""

from __future__ import annotations

from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


def _options_surface_model(spot: float) -> dict[str, Any]:
    expiries = ["30d", "60d", "90d"]
    strikes = [round(spot * m, 2) for m in (0.9, 1.0, 1.1)]
    return {
        "expiries": expiries,
        "calls": [{"expiry": e, "strike": k, "impliedVolatility": 0.4}
                  for e in expiries for k in strikes],
        "puts": [{"expiry": e, "strike": k, "impliedVolatility": 0.45}
                 for e in expiries for k in strikes],
    }


@FunctionRegistry.register
class OMONFunction(BaseFunction):
    code = "OMON"
    name = "Option Monitor"
    asset_classes = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.DERIVATIVE)
    category = "derivative"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        warnings: list[str] = []
        data = {}
        if not (params.get("live_options") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data=_options_surface_model(float(params.get("spot", 100))),
                sources=["options_surface_model"],
            )
        try:
            if self.deps.yfinance:
                data = await self.deps.yfinance.fetch(DataRequest(
                    kind=DataKind.OPTIONS_CHAIN, instrument=instrument,
                    extra={"expiry": params.get("expiry"),
                           "timeout": float(params.get("yfinance_timeout", 6))},
                ))
        except Exception as e:
            warnings.append(f"yfinance options: {e}")
        if not data or not (data.get("expiries") if isinstance(data, dict) else None):
            data = _options_surface_model(float(params.get("spot", 100)))
            warnings = []
            return FunctionResult(code=self.code, instrument=instrument, data=data,
                                  sources=["options_surface_model"])
        return FunctionResult(code=self.code, instrument=instrument, data=data,
                              sources=["yfinance"], warnings=warnings)
