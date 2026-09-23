"""Calendar registry: market open/close and exchange holidays.

Uses the ``exchange_calendars`` package when available (preferred path), and
falls back to a tiny built-in shim. Only the API needed by ShowMe is exposed
so we can swap implementations without touching call sites.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from showme.engine.reference.exchange_registry import EXCHANGES

# HNT-14: ShowMe exchange codes that exist under a different name in the
# ``exchange_calendars`` package. Unmapped codes (and crypto venues) keep
# the weekday-only behavior.
_EC_ALIASES = {
    "FWB": "XETR",
    "TYO": "JPX",
    "HKEX": "XHKG",
    "BIST": "XIST",
}


class CalendarRegistry:
    """Minimal calendar surface: is_open, next_open/close, sessions(list[date])."""

    def __init__(self) -> None:
        self._ec = None  # exchange_calendars module if importable
        try:
            import exchange_calendars as ec  # type: ignore[import-untyped]
            self._ec = ec
        except Exception:
            self._ec = None

    def _session_calendar(self, exchange_code: str):
        """Return the exchange_calendars calendar for the code, or None."""
        if self._ec is None:
            return None
        code = _EC_ALIASES.get(exchange_code.upper(), exchange_code.upper())
        try:
            if code not in self._ec.get_calendar_names():
                return None
            return self._ec.get_calendar(code)
        except Exception:
            return None

    def _is_session(self, exchange_code: str, day: date) -> bool:
        """Authoritative session check; True when no calendar is available.

        A missing/unmappable calendar or a raised lookup keeps the legacy
        weekday-only behavior instead of guessing a holiday.
        """
        cal = self._session_calendar(exchange_code)
        if cal is None:
            return True
        try:
            return bool(cal.is_session(day))
        except Exception:
            return True

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
        # HNT-14: weekend check alone reported exchanges "open" on official
        # holidays (Thanksgiving/Christmas); consult the authoritative
        # session calendar when the package provides one.
        if not self._is_session(ex.code, local.date()):
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
        # HNT-14: skip weekends AND non-session (holiday) dates; bounded so a
        # calendar with no future sessions can never spin forever.
        for _ in range(60):
            if cand.weekday() < 5 and self._is_session(ex.code, cand.date()):
                break
            cand = cand + timedelta(days=1)
        else:
            return None
        return cand.astimezone(timezone.utc)

    def next_close(self, exchange_code: str, after: datetime | None = None) -> datetime | None:
        """Next close timestamp in UTC for ``exchange_code``.

        For 24/7 venues returns ``None`` (no scheduled close). For others the
        next session's close (today if before close, otherwise the next
        weekday's close). Used by TRDH so currently-open exchanges report a
        meaningful "until close" delta instead of the next-open delta.
        """
        ex = EXCHANGES.get(exchange_code.upper())
        if ex is None:
            return None
        after = after or datetime.now(tz=timezone.utc)
        if ex.code in {"BINANCE", "BYBIT", "OKX", "DERIBIT", "COINBASE"}:
            return None
        local = after.astimezone(ZoneInfo(ex.timezone))
        h_c, m_c = (int(x) for x in ex.close_local.split(":"))
        cand = local.replace(hour=h_c, minute=m_c, second=0, microsecond=0)
        if cand <= local:
            cand = cand + timedelta(days=1)
        # HNT-14: skip weekends AND non-session (holiday) dates; bounded so a
        # calendar with no future sessions can never spin forever.
        for _ in range(60):
            if cand.weekday() < 5 and self._is_session(ex.code, cand.date()):
                break
            cand = cand + timedelta(days=1)
        else:
            return None
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
