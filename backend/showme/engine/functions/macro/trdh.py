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

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.reference.calendar_registry import CalendarRegistry
from showme.engine.reference.exchange_registry import EXCHANGES


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
            nxt_open = cal.next_open(code, now)
            nxt_close = cal.next_close(code, now)
            secs_open = int((nxt_open - now).total_seconds()) if nxt_open else None
            secs_close = int((nxt_close - now).total_seconds()) if nxt_close else None
            # When the exchange is open right now, "value" / "hours_until_open"
            # used to silently point at the *next* session — burying the
            # actually-useful number (time-to-close) and giving the UI a
            # 16h+ countdown on an open exchange. Report both deltas
            # explicitly so the chip can render the correct one.
            primary_delta_seconds = secs_close if is_open and secs_close is not None else secs_open
            rows.append({
                "exchange": code, "name": ex.name, "country": ex.country,
                "currency": ex.currency,
                "open_local": ex.open_local, "close_local": ex.close_local,
                "timezone": ex.timezone,
                "is_open_now": is_open,
                "next_open_utc": nxt_open.isoformat() if nxt_open else None,
                "next_close_utc": nxt_close.isoformat() if nxt_close else None,
                "seconds_until_open": secs_open,
                "seconds_until_close": secs_close,
                "hours_until_open": round(secs_open / 3600, 3) if secs_open is not None else None,
                "hours_until_close": round(secs_close / 3600, 3) if secs_close is not None else None,
                "value": round(primary_delta_seconds / 3600, 3) if primary_delta_seconds is not None else None,
            })
        data = {
            "rows": rows,
            "surface": [
                {
                    "exchange": row.get("exchange"),
                    "status": "open" if row.get("is_open_now") else "closed",
                    "hours_until_open": row.get("hours_until_open"),
                    "hours_until_close": row.get("hours_until_close"),
                    "value": row.get("value"),
                }
                for row in rows
                if row.get("value") is not None
            ],
            "cards": [
                {"label": "Open now", "value": sum(1 for row in rows if row.get("is_open_now"))},
                {"label": "Exchanges", "value": len(rows)},
            ],
            "methodology": (
                "TRDH evaluates each exchange with the local exchange calendar and timezone registry. "
                "next_open_utc is the next scheduled open in UTC; next_close_utc is the next scheduled "
                "close in UTC. seconds_until_open / seconds_until_close are computed from the current UTC "
                "timestamp. `value` is the seconds-to-close-of-current-session for open exchanges, otherwise "
                "seconds-to-next-open; this makes the UI countdown point at the next state change. "
                "Holiday coverage depends on the local calendar registry."
            ),
            "field_dictionary": {
                "is_open_now": "Whether the exchange is currently inside a regular session.",
                "next_open_utc": "Next regular-session open in UTC.",
                "next_close_utc": "Next regular-session close in UTC.",
                "seconds_until_open": "Seconds until next regular open.",
                "seconds_until_close": "Seconds until next regular close.",
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
