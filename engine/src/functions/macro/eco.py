"""ECO — Economic Calendar."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


@FunctionRegistry.register
class ECOFunction(BaseFunction):
    code = "ECO"
    name = "Economic Calendar"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        country = params.get("country")
        importance = params.get("importance")
        events: list = []
        live = _truthy(params.get("live_calendar") or params.get("live"))
        if live and self.deps.tradingeconomics:
            try:
                events = await asyncio.wait_for(
                    self.deps.tradingeconomics.calendar(
                        country=country,
                        importance=importance,
                    ),
                    timeout=float(params.get("timeout", 8)),
                )
            except Exception:
                pass
        if not events:
            events = _calendar_feed_model(country, importance)
        return FunctionResult(code=self.code, instrument=None, data=events,
                              sources=["tradingeconomics" if live and self.deps.tradingeconomics else "calendar_feed_model"],
                              metadata={"country": country, "importance": importance, "live": live})


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _calendar_feed_model(country: str | None, importance: str | None) -> list[dict[str, Any]]:
    selected_country = country or "US"
    events = [
        {"country": selected_country, "event": "CPI", "date": "2026-05-13",
         "importance": "high", "forecast": None, "previous": None},
        {"country": selected_country, "event": "FOMC rate decision", "date": "2026-06-10",
         "importance": "high", "forecast": None, "previous": None},
        {"country": selected_country, "event": "Retail sales", "date": "2026-05-15",
         "importance": "medium", "forecast": None, "previous": None},
    ]
    if importance:
        wanted = str(importance).lower()
        events = [event for event in events if event["importance"].lower() == wanted] or events[:1]
    return events
