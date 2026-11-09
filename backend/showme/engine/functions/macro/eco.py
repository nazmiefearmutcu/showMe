"""ECO — Economic Calendar (Awareness merged calendar).

Rows come from the Awareness economic calendar (Nasdaq + ForexFactory +
BEA + central-bank schedules, merged and deduplicated upstream). ECO never
invents a schedule: when Awareness is down it answers ``provider_unavailable``
with the client's reason. Holidays for the selected countries ride along from
``/calendar/holidays``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.functions.calendar._common import (
    aw_get,
    country_codes,
    data_meta,
    holiday_row,
    importance_level,
    iso_day,
    parse_bool,
    parse_day,
    parse_int,
    provenance_metadata,
    unavailable_result,
    utc_today,
)

_IMPORTANCE_LABEL = {1: "low", 2: "medium", 3: "high"}
_CENTRAL_BANK_RE = re.compile(r"\b(rate decision|interest rate|fomc|ecb|boe|boj|tcmb|monetary policy)\b", re.IGNORECASE)

_METHODOLOGY = (
    "ECO lists Awareness economic-calendar events for the requested countries, importance floor and "
    "date window. importance 3 is high, 2 medium, 1 low. Values pass through from Awareness in the unit "
    "the provider reports (K/M/B suffixes are already scaled upstream, never multiplied here). surprise is "
    "actual minus forecast when both exist; surprise_direction is above, below or inline. Holidays are the "
    "public and market closures in the window for the same countries. Nothing is estimated or filled in."
)

_FIELD_DICTIONARY = {
    "date": "Scheduled release time (UTC).",
    "importance": "1 low, 2 medium, 3 high (provider impact bucket).",
    "forecast": "Consensus estimate as published.",
    "actual": "Released value as published; blank until released.",
    "previous": "Prior-period value as published.",
    "surprise": "Actual minus forecast in the same unit; inline when zero.",
    "is_central_bank": "True for central-bank decisions and policy speeches.",
}


def _econ_row(item: dict[str, Any]) -> dict[str, Any]:
    importance = parse_int(item.get("importance"), default=1, floor=1, ceiling=3)
    title = str(item.get("title") or "").strip() or "Economic event"
    category = str(item.get("category") or "")
    return {
        "id": item.get("id"),
        "date": item.get("scheduled_at"),
        "all_day": bool(item.get("all_day")),
        "country": item.get("country"),
        "currency": item.get("currency"),
        "event": title,
        "category": category,
        "importance": importance,
        "importance_label": _IMPORTANCE_LABEL[importance],
        "actual": item.get("actual"),
        "forecast": item.get("forecast"),
        "previous": item.get("previous"),
        "revised": item.get("revised"),
        "actual_value": item.get("actual_value"),
        "forecast_value": item.get("forecast_value"),
        "previous_value": item.get("previous_value"),
        "unit": item.get("unit"),
        "surprise": item.get("surprise"),
        "surprise_direction": item.get("surprise_direction"),
        "status": item.get("status"),
        "description": item.get("description"),
        "sources": item.get("sources") or [],
        "is_central_bank": category.lower() == "central_bank" or bool(_CENTRAL_BANK_RE.search(title)),
    }


def _parse_instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@FunctionRegistry.register
class ECOFunction(BaseFunction):
    code = "ECO"
    name = "Economic Calendar"
    category = "macro"
    description = (
        "Economic release calendar by country and importance with consensus, previous and actual values, "
        "surprise direction, central-bank flags and public or market holidays, from Awareness."
    )

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if parse_bool(params.get("reference")):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "input_error",
                    "reason": "reference schedule removed — data is live from Awareness",
                    "rows": [],
                    "next_actions": ["Drop the reference parameter; ECO reads the live Awareness calendar."],
                },
                sources=["no_live_source"],
                metadata={"fallback": True, "live": False, "data_mode": "provider_unavailable"},
            )

        today = utc_today()
        start = parse_day(params.get("from")) or today
        days = parse_int(params.get("days"), default=7, floor=1, ceiling=60)
        end = start + timedelta(days=days)
        countries = country_codes(params.get("country") or params.get("countries"))
        importance = importance_level(params.get("importance"), default=1)
        status_filter = str(params.get("status") or "").strip().lower()

        calendar_query: dict[str, Any] = {"from": iso_day(start), "to": iso_day(end), "min_importance": importance}
        if countries:
            calendar_query["countries"] = ",".join(countries)
        if status_filter:
            calendar_query["status"] = status_filter
        holiday_query: dict[str, Any] = {"from": iso_day(start), "to": iso_day(end)}
        if countries:
            holiday_query["countries"] = ",".join(countries)

        (calendar, calendar_error), (holidays, holiday_error) = await asyncio.gather(
            aw_get(self, "/calendar/economic", calendar_query),
            aw_get(self, "/calendar/holidays", holiday_query),
        )
        if calendar_error is not None or calendar is None:
            return unavailable_result(
                self.code,
                None,
                calendar_error or "awareness returned no response",
                extra={"events": [], "holidays": [], "country": ",".join(countries) or "ALL"},
            )

        warnings: list[str] = []
        # A failed holiday call is a degraded answer, not an empty one: the pane must say holidays were not checked.
        holidays_status = "unavailable" if holiday_error is not None else "ok"
        degraded: list[str] = []
        if holiday_error is not None:
            warnings.append(f"holidays unavailable, not checked: {holiday_error}")
            degraded.append("holidays")
        responses = [calendar] + ([holidays] if holidays is not None else [])

        rows = [_econ_row(item) for item in calendar.data if isinstance(item, dict)]
        rows.sort(key=lambda row: str(row.get("date") or ""))
        now = datetime.now(UTC)
        next_high = next(
            (
                row for row in rows
                if row["importance"] >= 3 and str(row.get("status") or "").lower() == "scheduled"
                and (_parse_instant(row.get("date")) or now) >= now
            ),
            None,
        )
        holiday_rows = [holiday_row(item) for item in (holidays.data if holidays is not None else []) if isinstance(item, dict)]

        surface: dict[str, int] = {}
        for row in rows:
            key = row["importance_label"]
            surface[key] = surface.get(key, 0) + 1

        status = "ok" if rows else "empty"
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": status,
                "rows": rows,
                "events": rows,
                "next_high_impact": next_high,
                "holidays": holiday_rows,
                "holidays_status": holidays_status,
                "degraded": bool(degraded),
                "degraded_parts": degraded,
                "surface": [{"importance": key, "value": value} for key, value in sorted(surface.items())],
                "cards": [
                    {"label": "Events", "value": len(rows)},
                    {"label": "Country", "value": ",".join(countries) or "ALL"},
                    {"label": "Importance", "value": _IMPORTANCE_LABEL[importance]},
                ],
                "filters": {
                    "from": iso_day(start),
                    "to": iso_day(end),
                    "days": days,
                    "countries": countries,
                    "min_importance": importance,
                    "status": status_filter or None,
                },
                "meta": data_meta(responses),
                "methodology": _METHODOLOGY,
                "field_dictionary": _FIELD_DICTIONARY,
                "as_of": datetime.now(UTC).isoformat(),
                "reason": None if rows else "No economic events match the selected countries and importance.",
            },
            sources=["awareness:econ"] + (["awareness:holidays"] if holidays is not None else []),
            warnings=warnings,
            metadata=provenance_metadata(responses, provider_errors=warnings, extra={
                "country": ",".join(countries) or "ALL",
                "importance": _IMPORTANCE_LABEL[importance],
                "days": days,
                "degraded": bool(degraded),
                "degraded_parts": degraded,
            }),
        )
