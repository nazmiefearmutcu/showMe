"""ECO — Economic Calendar."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


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
        source_mode = "calendar_feed_model"

        if live:
            if self.deps.tradingeconomics:
                try:
                    events = await asyncio.wait_for(
                        self.deps.tradingeconomics.calendar(
                            country=country,
                            importance=importance,
                        ),
                        timeout=float(params.get("timeout", 8)),
                    )
                    if events:
                        source_mode = "tradingeconomics"
                except Exception as exc:
                    provider_errors.append(f"tradingeconomics: {exc}")

            if not events and self.deps.finnhub:
                try:
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    end_str = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
                    events = await asyncio.wait_for(
                        self.deps.finnhub.economic_calendar(
                            start=today_str,
                            end=end_str,
                        ),
                        timeout=float(params.get("timeout", 8)),
                    )
                    if events:
                        source_mode = "finnhub"
                except Exception as exc:
                    provider_errors.append(f"finnhub: {exc}")

        if not events:
            events = _calendar_feed_model(country, importance)
            source_mode = "calendar_feed_model"

        rows = _normalize_events(events, country=country, importance=importance, days=days)
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
    today = datetime.now(timezone.utc).date()
    raw_events = [
        # --- US ---
        {"country": "US", "event": "FOMC Interest Rate Decision", "offset": -2, "importance": "high", "forecast": 4.5, "actual": 4.5, "previous": 4.75, "unit": "%"},
        {"country": "US", "event": "Non Farm Payrolls", "offset": -1, "importance": "high", "forecast": 180, "actual": 210, "previous": 175, "unit": "K"},
        {"country": "US", "event": "Unemployment Rate", "offset": -1, "importance": "high", "forecast": 3.9, "actual": 3.8, "previous": 3.9, "unit": "%"},
        {"country": "US", "event": "CPI MoM", "offset": 0, "importance": "high", "forecast": 0.2, "actual": 0.3, "previous": 0.1, "unit": "%"},
        {"country": "US", "event": "CPI YoY", "offset": 0, "importance": "high", "forecast": 3.1, "actual": 3.2, "previous": 3.0, "unit": "%"},
        {"country": "US", "event": "Initial Jobless Claims", "offset": 2, "importance": "low", "forecast": 215, "actual": None, "previous": 220, "unit": "K"},
        {"country": "US", "event": "Retail Sales MoM", "offset": 4, "importance": "medium", "forecast": 0.3, "actual": None, "previous": 0.1, "unit": "%"},
        {"country": "US", "event": "PPI MoM", "offset": 5, "importance": "medium", "forecast": 0.1, "actual": None, "previous": 0.2, "unit": "%"},
        {"country": "US", "event": "GDP Growth Rate QoQ (Est)", "offset": 10, "importance": "high", "forecast": 2.1, "actual": None, "previous": 1.8, "unit": "%"},
        {"country": "US", "event": "S&P Global Manufacturing PMI", "offset": 15, "importance": "medium", "forecast": 50.5, "actual": None, "previous": 49.9, "unit": ""},
        {"country": "US", "event": "Michigan Consumer Sentiment", "offset": 20, "importance": "low", "forecast": 72.5, "actual": None, "previous": 70.2, "unit": ""},

        # --- EU ---
        {"country": "EU", "event": "ECB Interest Rate Decision", "offset": -3, "importance": "high", "forecast": 3.75, "actual": 3.5, "previous": 3.75, "unit": "%"},
        {"country": "EU", "event": "Inflation Rate YoY (Flash)", "offset": -1, "importance": "high", "forecast": 2.4, "actual": 2.4, "previous": 2.6, "unit": "%"},
        {"country": "EU", "event": "Unemployment Rate", "offset": 1, "importance": "medium", "forecast": 6.5, "actual": None, "previous": 6.5, "unit": "%"},
        {"country": "EU", "event": "GDP Growth Rate QoQ (Flash)", "offset": 3, "importance": "high", "forecast": 0.2, "actual": None, "previous": 0.1, "unit": "%"},
        {"country": "EU", "event": "ZEW Economic Sentiment Index", "offset": 6, "importance": "medium", "forecast": 43.0, "actual": None, "previous": 42.9, "unit": ""},
        {"country": "EU", "event": "Industrial Production MoM", "offset": 12, "importance": "low", "forecast": 0.5, "actual": None, "previous": -0.2, "unit": "%"},
        {"country": "EU", "event": "HCOB Eurozone Manufacturing PMI", "offset": 18, "importance": "medium", "forecast": 47.2, "actual": None, "previous": 47.3, "unit": ""},

        # --- UK ---
        {"country": "UK", "event": "BoE Interest Rate Decision", "offset": -2, "importance": "high", "forecast": 5.0, "actual": 5.0, "previous": 5.25, "unit": "%"},
        {"country": "UK", "event": "Inflation Rate YoY", "offset": 0, "importance": "high", "forecast": 2.1, "actual": 2.0, "previous": 2.3, "unit": "%"},
        {"country": "UK", "event": "Unemployment Rate (3M)", "offset": 2, "importance": "medium", "forecast": 4.3, "actual": None, "previous": 4.2, "unit": "%"},
        {"country": "UK", "event": "GDP Growth Rate MoM", "offset": 5, "importance": "high", "forecast": 0.1, "actual": None, "previous": 0.2, "unit": "%"},
        {"country": "UK", "event": "Retail Sales MoM", "offset": 8, "importance": "medium", "forecast": -0.3, "actual": None, "previous": 0.5, "unit": "%"},
        {"country": "UK", "event": "S&P Global Services PMI", "offset": 14, "importance": "medium", "forecast": 52.9, "actual": None, "previous": 53.1, "unit": ""},

        # --- TR ---
        {"country": "TR", "event": "TCMB Interest Rate Decision", "offset": -4, "importance": "high", "forecast": 45.0, "actual": 45.0, "previous": 45.0, "unit": "%"},
        {"country": "TR", "event": "Inflation Rate YoY (CPI)", "offset": -1, "importance": "high", "forecast": 68.2, "actual": 69.8, "previous": 67.1, "unit": "%"},
        {"country": "TR", "event": "Unemployment Rate", "offset": 1, "importance": "medium", "forecast": 8.7, "actual": None, "previous": 8.8, "unit": "%"},
        {"country": "TR", "event": "Industrial Production YoY", "offset": 3, "importance": "medium", "forecast": 2.1, "actual": None, "previous": 1.3, "unit": "%"},
        {"country": "TR", "event": "GDP Growth Rate YoY", "offset": 7, "importance": "high", "forecast": 4.0, "actual": None, "previous": 4.5, "unit": "%"},
        {"country": "TR", "event": "Current Account Balance", "offset": 11, "importance": "medium", "forecast": -2.1, "actual": None, "previous": -1.8, "unit": "B USD"},
        {"country": "TR", "event": "Retail Sales YoY", "offset": 16, "importance": "low", "forecast": 9.5, "actual": None, "previous": 10.2, "unit": "%"},
    ]
    events = []
    for item in raw_events:
        event_date = today + timedelta(days=item["offset"])
        events.append({
            "country": item["country"],
            "event": item["event"],
            "date": event_date.isoformat(),
            "importance": item["importance"],
            "forecast": item["forecast"],
            "actual": item["actual"],
            "previous": item["previous"],
            "unit": item["unit"],
        })
    return events



# S05 BUGHUNT B4: trading-economics tags UK/EU/JP events with ISO 3166 alpha-2
# codes ("UK", "EU", "JP") AND human-readable forms ("United Kingdom",
# "European Union", "Japan"); the UI's SegmentedControl meanwhile defaults to
# "GB"/"EZ" etc. Without a canonical normalisation, picking "UK" silently
# drops every live row whose `country` field reads "United Kingdom". The map
# folds known aliases onto a single canonical token before equality matching.
_COUNTRY_ALIASES: dict[str, str] = {
    "GB": "UK", "GBR": "UK", "UK": "UK", "UNITED KINGDOM": "UK", "BRITAIN": "UK",
    "EZ": "EU", "EUR": "EU", "EU": "EU", "EUROZONE": "EU", "EUROPEAN UNION": "EU", "EMU": "EU",
    "US": "US", "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "JP": "JP", "JPN": "JP", "JAPAN": "JP",
    "DE": "DE", "DEU": "DE", "GERMANY": "DE",
    "FR": "FR", "FRA": "FR", "FRANCE": "FR",
    "TR": "TR", "TUR": "TR", "TURKEY": "TR", "TÜRKIYE": "TR", "TURKIYE": "TR",
    "CN": "CN", "CHN": "CN", "CHINA": "CN",
    "IN": "IN", "IND": "IN", "INDIA": "IN",
    "BR": "BR", "BRA": "BR", "BRAZIL": "BR",
}


def _canonical_country(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    return _COUNTRY_ALIASES.get(raw, raw)


def _normalize_events(events: list[Any], *, country: Any, importance: Any, days: int) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc).date() - timedelta(days=1)
    end = start + timedelta(days=days + 1)
    wanted_country = _canonical_country(country)
    wanted_importance = str(importance or "").lower()
    rows: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        row = {str(k).lower(): v for k, v in raw.items()}
        event_country = _canonical_country(row.get("country") or row.get("region"))
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
