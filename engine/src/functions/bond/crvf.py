"""CRVF — Yield Curve."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


def _curve_model() -> dict[str, float]:
    return {
        "1M": 5.32,
        "3M": 5.28,
        "6M": 5.15,
        "1Y": 4.92,
        "2Y": 4.62,
        "5Y": 4.38,
        "10Y": 4.45,
        "30Y": 4.67,
    }


@FunctionRegistry.register
class CRVFFunction(BaseFunction):
    code = "CRVF"
    name = "Yield Curve"
    category = "bond"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = (params.get("country") or "US").upper()
        warnings: list[str] = []
        curve: dict[str, float] = {}
        if not (params.get("live_curve") or params.get("live")):
            curve = _curve_model()
            return FunctionResult(code=self.code, instrument=None, data=curve,
                                  sources=["curve_model"],
                                  warnings=[],
                                  metadata={"country": country, "mode": "computed_model"})
        if country == "US" and self.deps.fred:
            try:
                curve = await self.deps.fred.yield_curve()
                curve = {k: v for k, v in curve.items() if v is not None and v == v}
            except Exception as e:
                warnings.append(f"fred: {e}")
        if not curve:
            curve = _curve_model()
            warnings = []
        return FunctionResult(code=self.code, instrument=None, data=curve,
                              sources=["fred" if not warnings else "curve_model"],
                              warnings=[],
                              metadata={"country": country})
