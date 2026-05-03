"""TRDH — Trading Hours awareness.

Önemli borsalar için:
  - is_open (now)
  - next_open / next_close (UTC)
  - seconds_until_open / close
  - daily session string (local)

Source: ``src.reference.calendar_registry`` + ``exchange_registry``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument
from src.reference.calendar_registry import CalendarRegistry
from src.reference.exchange_registry import EXCHANGES


_DEFAULT_EXCHANGES = ["NYSE", "NASDAQ", "LSE", "FWB", "TYO", "HKEX",
                       "ASX", "BIST", "BINANCE", "DERIBIT"]


@FunctionRegistry.register
class TRDHFunction(BaseFunction):
    code = "TRDH"
    name = "Trading Hours"
    category = "macro"
    description = "Per-exchange trading session status + next open/close (UTC)."

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        cal = CalendarRegistry()
        exchanges = params.get("exchanges") or _DEFAULT_EXCHANGES
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for code in exchanges:
            ex = EXCHANGES.get(code)
            if ex is None:
                continue
            is_open = cal.is_open(code, now)
            nxt = cal.next_open(code, now)
            secs = int((nxt - now).total_seconds()) if nxt else None
            rows.append({
                "exchange": code, "name": ex.name, "country": ex.country,
                "currency": ex.currency,
                "open_local": ex.open_local, "close_local": ex.close_local,
                "timezone": ex.timezone,
                "is_open_now": is_open,
                "next_open_utc": nxt.isoformat() if nxt else None,
                "seconds_until_open": secs,
            })
        return FunctionResult(
            code=self.code, instrument=None, data=rows,
            sources=["exchange_calendars"],
            metadata={"now_utc": now.isoformat()},
        )
