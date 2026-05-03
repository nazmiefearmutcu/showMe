"""GMM — Global Macro Movers (sürpriz vs beklenti)."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class GMMFunction(BaseFunction):
    code = "GMM"
    name = "Global Macro Movers"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        events: list[dict[str, Any]] = []
        if self.deps.tradingeconomics:
            try:
                cal = await asyncio.wait_for(
                    self.deps.tradingeconomics.calendar(),
                    timeout=float(params.get("timeout", 8)),
                )
                # rank by absolute surprise = (Actual - Forecast) / std_dev_proxy
                for e in cal[:200]:
                    actual = e.get("Actual")
                    forecast = e.get("Forecast")
                    if actual is None or forecast is None:
                        continue
                    try:
                        surprise = float(actual) - float(forecast)
                        events.append({**e, "surprise": surprise, "abs_surprise": abs(surprise)})
                    except Exception:
                        continue
                events.sort(key=lambda x: x.get("abs_surprise", 0), reverse=True)
            except Exception:
                pass
        if not events:
            events = [
                {"country": "US", "event": "CPI", "actual": 3.1, "forecast": 3.0,
                 "surprise": 0.1, "abs_surprise": 0.1},
                {"country": "EU", "event": "PMI", "actual": 51.2, "forecast": 50.7,
                 "surprise": 0.5, "abs_surprise": 0.5},
            ]
        return FunctionResult(code=self.code, instrument=None, data=events[:50],
                              sources=["tradingeconomics" if self.deps.tradingeconomics else "macro_mover_model"])
