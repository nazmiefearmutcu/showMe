"""GREEKS — Portfolio-level options Greeks aggregation."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services import greeks as greeks_svc


@FunctionRegistry.register
class GREEKSFunction(BaseFunction):
    code = "GREEKS"
    name = "Portfolio Greeks"
    category = "portfolio"
    description = "Sum delta/gamma/vega/theta/rho across an option book."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        positions = params.get("positions") or []
        if not positions:
            return FunctionResult(code=self.code, instrument=None,
                                  data={"delta": 0, "gamma": 0, "vega": 0, "theta": 0,
                                        "rho": 0, "positions": 0},
                                  sources=["empty_book"])
        try:
            agg = greeks_svc.aggregate_book(positions)
        except Exception as e:
            return FunctionResult(code=self.code, instrument=None, data={},
                                  warnings=[f"aggregate: {e}"])
        return FunctionResult(code=self.code, instrument=None, data=agg,
                              sources=["greeks"])
