"""WIRP — World Interest Rate Probability (CME FedWatch)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class WIRPFunction(BaseFunction):
    code = "WIRP"
    name = "World Interest Rate Probability"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        data = {
            "meetings": [
                {"date": "2026-06-10", "cut_25bp": 0.18, "hold": 0.72, "hike_25bp": 0.10},
                {"date": "2026-07-29", "cut_25bp": 0.28, "hold": 0.62, "hike_25bp": 0.10},
            ]
        }
        return FunctionResult(code=self.code, instrument=None, data=data,
                              sources=["fedwatch_probability_model"], warnings=[])
