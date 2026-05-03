"""TCA — Trade Cost Analysis (post-trade)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.services import tca


@FunctionRegistry.register
class TCAFunction(BaseFunction):
    code = "TCA"
    name = "Trade Cost Analysis"
    category = "trade"
    description = "Implementation shortfall, slippage, opportunity cost across fills."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        broker = params.get("broker")
        symbol = params.get("symbol") or (instrument.symbol if instrument else None)
        limit = int(params.get("limit", 200))
        result = tca.analyze_orders(broker=broker, symbol=symbol, limit=limit)
        return FunctionResult(
            code=self.code, instrument=instrument,
            data=result,
            sources=["order_history"],
        )
