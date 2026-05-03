"""EVTS — Corporate Events Calendar."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.base_data_source import DataKind, DataRequest
from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import AssetClass, Instrument


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if getattr(value, "empty", False):
        return True
    if isinstance(value, dict):
        return not value or all(_is_empty(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value or all(_is_empty(item) for item in value)
    return False


@FunctionRegistry.register
class EVTSFunction(BaseFunction):
    code = "EVTS"
    name = "Corporate Events"
    asset_classes = (AssetClass.EQUITY,)
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if instrument is None:
            raise ValueError
        events: dict[str, Any] = {}
        live = _truthy(params.get("live_events") or params.get("live"))
        if live and self.deps.yfinance:
            try:
                timeout = max(1.0, min(float(params.get("yfinance_timeout", 4)), 6.0))
                events = await asyncio.wait_for(
                    self.deps.yfinance.fetch(DataRequest(
                        kind=DataKind.EVENTS,
                        instrument=instrument,
                        extra={"timeout": timeout},
                    )),
                    timeout=timeout + 1,
                )
            except Exception:
                pass
        if not events or all(_is_empty(v) for v in events.values()):
            events = {
                "calendar": [{
                    "event": "earnings",
                    "date": None,
                    "symbol": instrument.symbol,
                    "status": "no_event_feed",
                }],
                "dividends": [],
                "splits": [],
            }
        return FunctionResult(code=self.code, instrument=instrument, data=events,
                              sources=["yfinance" if live and self.deps.yfinance else "corporate_events_model"],
                              metadata={"live": live})


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
