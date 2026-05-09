"""ECO — Economic Calendar."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
        days = _int_param(params.get("days"), default=30, floor=1, ceiling=180)
        events: list = []
        provider_errors: list[str] = []
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
            except Exception as exc:
                provider_errors.append(f"tradingeconomics: {exc}")
        if not events:
            events = _calendar_feed_model(country, importance)
        rows = _normalize_events(events, country=country, importance=importance, days=days)
        source_mode = "tradingeconomics" if live and self.deps.tradingeconomics and not provider_errors else "calendar_feed_model"
        for row in rows:
            row.setdefault("source_mode", source_mode)
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "events": rows,
                "rows": rows,
                "surface": _importance_surface(rows),
                "cards": [
                    {"label": "Events", "value": len(rows)},
                    {"label": "Country", "value": country or "ALL"},
                    {"label": "Importance", "value": importance or "ALL"},
                ],
                "methodology": (
                    "ECO filters economic calendar events by country, importance, and forward date window. "
                    "Surprise is actual minus forecast when both values exist; blank actual/forecast fields "
                    "mean the event has not printed or the provider did not supply estimates."
                ),
                "field_dictionary": {
                    "date": "Scheduled event date.",
                    "importance": "Provider impact bucket.",
                    "forecast": "Consensus estimate when available.",
                    "actual": "Released value when available.",
                    "surprise": "Actual minus forecast.",
                },
                "source_mode": source_mode,
            },
            sources=[source_mode],
            warnings=provider_errors,
            metadata={"country": country, "importance": importance, "days": days, "live": live},
        )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _calendar_feed_model(country: str | None, importance: str | None) -> list[dict[str, Any]]:
    selected_country = country or "US"
    today = datetime.now(timezone.utc).date()
    events = [
        {"country": selected_country, "event": "CPI", "date": (today + timedelta(days=9)).isoformat(),
         "importance": "high", "forecast": 2.9, "previous": 3.1, "unit": "% y/y"},
        {"country": selected_country, "event": "FOMC rate decision", "date": (today + timedelta(days=37)).isoformat(),
         "importance": "high", "forecast": 3.75, "previous": 4.0, "unit": "%"},
        {"country": selected_country, "event": "Retail sales", "date": (today + timedelta(days=11)).isoformat(),
         "importance": "medium", "forecast": 0.3, "previous": 0.1, "unit": "% m/m"},
    ]
    if importance:
        wanted = str(importance).lower()
        events = [event for event in events if event["importance"].lower() == wanted] or events[:1]
    return events


def _normalize_events(events: list[Any], *, country: Any, importance: Any, days: int) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = start + timedelta(days=days + 1)
    wanted_country = str(country or "").upper()
    wanted_importance = str(importance or "").lower()
    rows: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        row = {str(k).lower(): v for k, v in raw.items()}
        event_country = str(row.get("country") or row.get("region") or "").upper()
        event_importance = str(row.get("importance") or row.get("impact") or "").lower()
        if wanted_country and event_country and event_country != wanted_country:
            continue
        if wanted_importance and wanted_importance != "all" and event_importance and wanted_importance not in event_importance:
            continue
        date_text = str(row.get("date") or row.get("datetime") or row.get("time") or "")
        event_date = _parse_date(date_text)
        if event_date and not (start <= event_date <= end):
            continue
        forecast = _num(row.get("forecast"))
        actual = _num(row.get("actual"))
        rows.append({
            "date": event_date.isoformat() if event_date else date_text[:16],
            "country": event_country or (wanted_country or "US"),
            "event": row.get("event") or row.get("name") or row.get("title") or "Economic event",
            "importance": row.get("importance") or row.get("impact") or "medium",
            "forecast": forecast,
            "actual": actual,
            "previous": _num(row.get("previous")),
            "surprise": round(actual - forecast, 6) if actual is not None and forecast is not None else None,
            "unit": row.get("unit") or "",
        })
    return sorted(rows, key=lambda item: str(item.get("date") or ""))


def _importance_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("importance") or "unknown").lower()
        counts[key] = counts.get(key, 0) + 1
    return [{"importance": key, "value": value} for key, value in sorted(counts.items())]


def _parse_date(value: str) -> Any:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _num(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return round(float(str(value).replace("%", "").replace(",", "")), 6)
    except ValueError:
        return None


def _int_param(value: Any, *, default: int, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(floor, min(ceiling, parsed))
