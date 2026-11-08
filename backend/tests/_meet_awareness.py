"""Offline Awareness stand-in for MEET tests.

MEET's calendar now comes from ``/calendar/economic`` on the Awareness service. Test modules
that used to feed ForexFactory-shaped rows through ``_http_client`` route the same rows through
``FakeAwareness`` instead, so the assertions about filters, modes and ordering keep their meaning.
Nothing here performs network I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from showme.engine.data_sources.awareness import AwarenessResponse, AwarenessUnavailable

_CURRENCY_TO_ISO = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "TRY": "TR", "CNY": "CN",
    "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ",
}
_IMPACT_LEVEL = {"high": 3, "medium": 2, "low": 1}


def _utc_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def economic_rows_from_ff(payload: Any) -> list[dict[str, Any]]:
    """ForexFactory-shaped test rows -> awareness ``/calendar/economic`` rows."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload or []):
        if not isinstance(item, dict):
            continue
        when = _utc_text(item.get("date"))
        title = str(item.get("title") or "").strip()
        if not when or not title:
            continue
        currency = str(item.get("country") or "").strip().upper()
        rows.append({
            "id": f"test-econ-{index}",
            "country": _CURRENCY_TO_ISO.get(currency, currency),
            "currency": currency,
            "title": title,
            "category": "other",
            "scheduled_at": when,
            "all_day": False,
            "importance": _IMPACT_LEVEL.get(str(item.get("impact") or "medium").lower(), 2),
            "actual": item.get("actual") or None,
            "forecast": item.get("forecast") or None,
            "previous": item.get("previous") or None,
            "revised": None,
            "actual_value": None,
            "forecast_value": None,
            "previous_value": None,
            "unit": item.get("unit") or None,
            "surprise": None,
            "surprise_direction": None,
            "status": "scheduled",
            "description": None,
            "sources": [{"provider": "test", "url": None, "fetched_at": when, "basis": "fixture"}],
        })
    return rows


class FakeAwareness:
    """Answers the endpoints MEET reads; unknown paths are empty, never invented."""

    def __init__(self, *, economic: list[dict[str, Any]] | None = None,
                 news: list[dict[str, Any]] | None = None,
                 holidays: list[dict[str, Any]] | None = None,
                 down: str | None = None) -> None:
        self._economic = list(economic or [])
        self._news = list(news or [])
        self._holidays = list(holidays or [])
        self._down = down
        self.calls: list[str] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> AwarenessResponse:
        self.calls.append(path)
        if self._down:
            raise AwarenessUnavailable(self._down)
        if path.endswith("/calendar/economic"):
            data: list[dict[str, Any]] = self._economic
        elif path.endswith("/news"):
            data = self._news
        elif path.endswith("/calendar/holidays"):
            data = self._holidays
        else:
            data = []
        meta = {
            "generated_at": datetime.now(UTC).isoformat(),
            "count": len(data),
            "providers": [{"provider": "test.fixture", "status": "ok", "last_ok_at": None, "last_error": None}],
            "filters": dict(params or {}),
            "notes": [],
        }
        return AwarenessResponse(data=list(data), meta=meta, url=path)


def awareness_from_ff_client(client: Any) -> FakeAwareness:
    """Build the fake from a test module's ``_FakeFFClient`` (its stored payload)."""
    payload = getattr(client, "_payload", None) if client is not None else None
    return FakeAwareness(economic=economic_rows_from_ff(payload))
