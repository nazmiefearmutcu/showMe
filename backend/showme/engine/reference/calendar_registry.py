"""Calendar registry: market open/close and exchange holidays.

Uses the ``exchange_calendars`` package when available (preferred path), and
falls back to a tiny built-in shim. Only the API needed by ShowMe is exposed
so we can swap implementations without touching call sites.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from showme.engine.reference.exchange_registry import EXCHANGES


class CalendarRegistry:
    """Minimal calendar surface: is_open, next_open/close, sessions(list[date])."""

    def __init__(self) -> None:
        self._ec = None  # exchange_calendars module if importable
        try:
            import exchange_calendars as ec  # type: ignore[import-untyped]
            self._ec = ec
        except Exception:
            self._ec = None

    def is_open(self, exchange_code: str, when: datetime | None = None) -> bool:
        ex = EXCHANGES.get(exchange_code.upper())
        if ex is None:
            return False
        when = when or datetime.now(tz=timezone.utc)
        if ex.code in {"BINANCE", "BYBIT", "OKX", "DERIBIT", "COINBASE"}:
            return True  # crypto = 24/7
        local = when.astimezone(ZoneInfo(ex.timezone))
        if local.weekday() >= 5:
            return False
        h_o, m_o = (int(x) for x in ex.open_local.split(":"))
        h_c, m_c = (int(x) for x in ex.close_local.split(":"))
        return time(h_o, m_o) <= local.time() <= time(h_c, m_c)

    def next_open(self, exchange_code: str, after: datetime | None = None) -> datetime | None:
        ex = EXCHANGES.get(exchange_code.upper())
        if ex is None:
            return None
        after = after or datetime.now(tz=timezone.utc)
        if ex.code in {"BINANCE", "BYBIT", "OKX", "DERIBIT", "COINBASE"}:
            return after
        local = after.astimezone(ZoneInfo(ex.timezone))
        h_o, m_o = (int(x) for x in ex.open_local.split(":"))
        cand = local.replace(hour=h_o, minute=m_o, second=0, microsecond=0)
        if cand <= local:
            cand = cand + timedelta(days=1)
        while cand.weekday() >= 5:
            cand = cand + timedelta(days=1)
        return cand.astimezone(timezone.utc)

    def session_dates(self, exchange_code: str, start: date, end: date) -> list[date]:
        out: list[date] = []
        d = start
        while d <= end:
            if d.weekday() < 5:
                out.append(d)
            d = d + timedelta(days=1)
        # If exchange_calendars is available, replace with authoritative list.
        if self._ec is not None and exchange_code in self._ec.get_calendar_names():
            try:
                cal = self._ec.get_calendar(exchange_code)
                sessions = cal.sessions_in_range(start, end)
                return [s.date() for s in sessions]
            except Exception:
                pass
        return out
