"""TRDH — Trading hours from the Awareness exchange calendar.

Per exchange: today's session (exchange-local date), open/closed right now
(lunch breaks count as closed), next open and next close in UTC, the sessions
in the window (with early-close flags) and the closures (holidays and early
closes) from ``/calendar/holidays``. Sessions and closures are computed by
Awareness from exchange_calendars rule sets; nothing here is hard-coded.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    data_meta,
    holiday_row,
    iso_day,
    parse_csv,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)

# Legacy venue tokens the pane and older presets send -> exchange MIC.
LEGACY_MIC: dict[str, str] = {
    "NYSE": "XNYS", "NASDAQ": "XNAS", "LSE": "XLON", "FWB": "XFRA", "XETRA": "XETR",
    "EURONEXT": "XPAR", "PAR": "XPAR", "TSE": "XTKS", "TYO": "XTKS", "HKEX": "XHKG",
    "SSE": "XSHG", "TSX": "XTSE", "ASX": "XASX", "SIX": "XSWX", "BIST": "XIST", "IST": "XIST",
}
DEFAULT_MICS = ["XNYS", "XNAS", "XLON", "XFRA", "XTKS", "XHKG", "XASX", "XIST"]
EXCHANGE_NAMES: dict[str, str] = {
    "XNYS": "New York Stock Exchange", "XNAS": "Nasdaq", "XLON": "London Stock Exchange",
    "XFRA": "Frankfurt Stock Exchange", "XETR": "Xetra", "XPAR": "Euronext Paris",
    "XTKS": "Tokyo Stock Exchange", "XHKG": "Hong Kong Stock Exchange", "XASX": "ASX",
    "XIST": "Borsa Istanbul", "XSHG": "Shanghai Stock Exchange", "XTSE": "Toronto Stock Exchange",
    "XSWX": "SIX Swiss Exchange",
}
_METHODOLOGY = (
    "TRDH reads per-exchange sessions from the Awareness exchange calendar. is_open_now is true only inside "
    "a regular session and outside the lunch break. next_open_utc and next_close_utc are the next future "
    "session boundaries in UTC. today is the session whose exchange-local date is today (null on closed "
    "days). closures are holidays and early closes from the same calendar. Early closes carry "
    "early_close=true and their local close time."
)


def _resolve_mic(token: str) -> str:
    return LEGACY_MIC.get(token, token)


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _session_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": item.get("date"),
        "open_utc": item.get("open_utc"),
        "close_utc": item.get("close_utc"),
        "break_start_utc": item.get("break_start_utc"),
        "break_end_utc": item.get("break_end_utc"),
        "open_local": item.get("open_local"),
        "close_local": item.get("close_local"),
        "break_local": item.get("break_local"),
        "early_close": bool(item.get("early_close")),
    }


def _is_open(session: dict[str, Any], now: datetime) -> bool:
    open_at, close_at = _parse_utc(session.get("open_utc")), _parse_utc(session.get("close_utc"))
    if open_at is None or close_at is None or not (open_at <= now < close_at):
        return False
    brk_start, brk_end = _parse_utc(session.get("break_start_utc")), _parse_utc(session.get("break_end_utc"))
    return not (brk_start is not None and brk_end is not None and brk_start <= now < brk_end)


def _exchange_block(mic: str, payload: dict[str, Any], closures: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    tz_name = str(payload.get("timezone") or "UTC")
    sessions = [_session_row(item) for item in (payload.get("sessions") or []) if isinstance(item, dict)]
    sessions.sort(key=lambda row: str(row.get("open_utc") or ""))
    local_today = now.astimezone(ZoneInfo(tz_name)).date().isoformat()
    today = next((row for row in sessions if row.get("date") == local_today), None)
    is_open = any(_is_open(row, now) for row in sessions)
    next_opens = sorted(t for t in (_parse_utc(row["open_utc"]) for row in sessions) if t and t > now)
    next_closes = sorted(t for t in (_parse_utc(row["close_utc"]) for row in sessions) if t and t > now)
    return {
        "mic": mic,
        "name": EXCHANGE_NAMES.get(mic, mic),
        "timezone": tz_name,
        "regular_close_local": payload.get("regular_close_local"),
        "today": today,
        "is_open_now": is_open,
        "next_open_utc": next_opens[0].isoformat() if next_opens else None,
        "next_close_utc": next_closes[0].isoformat() if next_closes else None,
        "sessions": sessions,
        "closures": closures,
    }


@FunctionRegistry.register
class TRDHFunction(BaseFunction):
    code = "TRDH"
    name = "Trading Hours"
    category = "macro"
    description = (
        "Exchange trading hours: open or closed now (lunch breaks included), today's session, next "
        "open and close in UTC, early closes and holiday closures from the Awareness exchange calendar."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        now = datetime.now(UTC)
        days = parse_int(params.get("days"), default=14, floor=1, ceiling=60)
        requested = parse_csv(params.get("exchanges") or params.get("exchange"))
        mics: list[str] = []
        warnings: list[str] = []
        for token in (requested or DEFAULT_MICS):
            mic = _resolve_mic(token)
            if not (len(mic) == 4 and mic.isalpha() and mic.isupper()):
                warnings.append(f"Unknown exchange code skipped: {token}")
                continue
            if mic not in mics:
                mics.append(mic)
        if not mics:
            # Nothing was asked of Awareness, so this is a bad request, not a provider outage.
            reason = "No recognised exchange codes were requested."
            return FunctionResult(
                code=self.code,
                instrument=instrument,
                data={"status": "input_error", "reason": reason, "exchanges": [], "rows": []},
                sources=["no_live_source"],
                warnings=warnings + [reason],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )

        start = utc_today() - timedelta(days=1)
        end = utc_today() + timedelta(days=days)
        window = {"from": iso_day(start), "to": iso_day(end)}
        session_calls = await asyncio.gather(*[
            aw_get(self, "/calendar/sessions", {"exchange": mic, **window}) for mic in mics
        ])
        holiday_call = await aw_get(self, "/calendar/holidays", {**window, "exchanges": ",".join(mics)})
        holidays, holiday_error = holiday_call
        if holiday_error is not None:
            warnings.append(f"holidays: {holiday_error}")

        responses = []
        blocks: list[dict[str, Any]] = []
        for mic, (resp, error) in zip(mics, session_calls, strict=True):
            if resp is None:
                if error and "HTTP 422" in error:
                    warnings.append(f"Exchange not supported by the Awareness calendar: {mic}")
                    continue
                return unavailable_result("TRDH", instrument, error or f"awareness sessions unavailable for {mic}")
            responses.append(resp)
            closures = [
                holiday_row(item) for item in (holidays.data if holidays is not None else [])
                if isinstance(item, dict) and item.get("exchange") == mic
            ]
            blocks.append(_exchange_block(mic, resp.data or {}, closures, now))
        if holidays is not None:
            responses.append(holidays)

        return FunctionResult(
            code=self.code,
            instrument=instrument,
            data={
                "status": "ok" if blocks else "empty",
                "exchanges": blocks,
                "open_now": sum(1 for block in blocks if block["is_open_now"]),
                "meta": data_meta(responses),
                "window": window,
                "methodology": _METHODOLOGY,
                "field_dictionary": {
                    "is_open_now": "True inside a regular session and outside the lunch break.",
                    "next_open_utc": "Next future session open, UTC.",
                    "next_close_utc": "Next future session close, UTC.",
                    "early_close": "True when the session closes before the regular time.",
                },
                "reason": None if blocks else "No supported exchanges returned sessions.",
            },
            # Sessions and closures are both exchange-calendar data (area "holidays").
            sources=["awareness:holidays"] if blocks else [],
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings, extra={
                "now_utc": now.isoformat(),
                "exchanges": [block["mic"] for block in blocks],
            }),
        )
