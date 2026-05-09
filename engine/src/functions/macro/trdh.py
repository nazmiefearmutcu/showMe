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
        exchanges = _parse_exchanges(params.get("exchanges") or params.get("exchange") or _DEFAULT_EXCHANGES)
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
                "hours_until_open": round(secs / 3600, 3) if secs is not None else None,
                "value": round(secs / 3600, 3) if secs is not None else None,
            })
        data = {
            "rows": rows,
            "surface": [
                {
                    "exchange": row.get("exchange"),
                    "status": "open" if row.get("is_open_now") else "closed",
                    "hours_until_open": row.get("hours_until_open"),
                    "value": row.get("hours_until_open"),
                }
                for row in rows
                if row.get("hours_until_open") is not None
            ],
            "cards": [
                {"label": "Open now", "value": sum(1 for row in rows if row.get("is_open_now"))},
                {"label": "Exchanges", "value": len(rows)},
            ],
            "methodology": (
                "TRDH evaluates each exchange with the local exchange calendar and timezone registry. "
                "next_open_utc is the next scheduled open in UTC; seconds_until_open and hours_until_open "
                "are computed from the current UTC timestamp. Holiday coverage depends on the local calendar registry."
            ),
            "field_dictionary": {
                "is_open_now": "Whether the exchange is currently inside a regular session.",
                "next_open_utc": "Next regular-session open in UTC.",
                "seconds_until_open": "Seconds until next regular open.",
                "timezone": "Exchange local timezone used for the session clock.",
            },
            "source_mode": "exchange_calendar_registry",
        }
        return FunctionResult(
            code=self.code,
            instrument=None,
            data=data,
            sources=["exchange_calendars"],
            metadata={"now_utc": now.isoformat(), "exchanges": exchanges},
        )


def _parse_exchanges(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip().upper() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(part).strip().upper() for part in value if str(part).strip()]
    else:
        parts = []
    return parts or _DEFAULT_EXCHANGES
