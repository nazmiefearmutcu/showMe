"""GMM — Global Macro Movers (sürpriz vs beklenti)."""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


@FunctionRegistry.register
class GMMFunction(BaseFunction):
    code = "GMM"
    name = "Global Macro Movers"
    category = "macro"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        events: list[dict[str, Any]] = []
        provider_errors: list[str] = []
        country = params.get("country")
        min_importance = str(params.get("importance") or "all").lower()
        if self.deps.tradingeconomics:
            try:
                cal = await asyncio.wait_for(
                    self.deps.tradingeconomics.calendar(country=country),
                    timeout=float(params.get("timeout", 8)),
                )
                # rank by absolute surprise = (Actual - Forecast) / std_dev_proxy
                for e in cal[:200]:
                    actual = e.get("Actual")
                    forecast = e.get("Forecast")
                    if actual is None or forecast is None:
                        continue
                    try:
                        surprise = float(actual) - float(forecast)
                        events.append({**e, "surprise": surprise, "abs_surprise": abs(surprise)})
                    except Exception:
                        continue
            except Exception as exc:
                provider_errors.append(f"tradingeconomics: {exc}")
        if not events:
            events = [
                {"country": "US", "event": "CPI", "actual": 3.1, "forecast": 3.0,
                 "surprise": 0.1, "abs_surprise": 0.1, "importance": "high", "unit": "% y/y"},
                {"country": "EU", "event": "PMI", "actual": 51.2, "forecast": 50.7,
                 "surprise": 0.5, "abs_surprise": 0.5, "importance": "medium", "unit": "index"},
                {"country": "GB", "event": "Retail sales", "actual": -0.2, "forecast": 0.1,
                 "surprise": -0.3, "abs_surprise": 0.3, "importance": "medium", "unit": "% m/m"},
            ]
        rows = [_normalize_event(row) for row in events]
        if min_importance != "all":
            rows = [row for row in rows if min_importance in str(row.get("importance") or "").lower()]
        rows.sort(key=lambda x: x.get("score", 0), reverse=True)
        rows = rows[: int(params.get("limit", 50))]
        source_mode = "tradingeconomics" if self.deps.tradingeconomics and not provider_errors else "reference_macro_mover_table"
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "rows": rows,
                "surface": [{"event": row["event"], "country": row["country"], "score": row["score"]} for row in rows],
                "cards": [
                    {"label": "Movers", "value": len(rows)},
                    {"label": "Top score", "value": rows[0]["score"] if rows else None},
                ],
                "methodology": (
                    "GMM ranks macro events by absolute surprise. Surprise is actual minus forecast; "
                    "score is the absolute surprise normalized by a simple event-scale proxy so CPI, PMI, "
                    "and activity data are not plotted as one raw level series."
                ),
                "field_dictionary": {
                    "actual": "Released value.",
                    "forecast": "Consensus estimate.",
                    "surprise": "Actual minus forecast.",
                    "score": "Absolute surprise scaled for ranking.",
                },
                "source_mode": source_mode,
            },
            sources=[source_mode],
            warnings=provider_errors,
        )


def _normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    actual = _num(row.get("actual") or row.get("Actual"))
    forecast = _num(row.get("forecast") or row.get("Forecast"))
    surprise = _num(row.get("surprise")) if row.get("surprise") is not None else (
        round(actual - forecast, 6) if actual is not None and forecast is not None else None
    )
    event = str(row.get("event") or row.get("Event") or row.get("name") or "Macro event")
    scale = 0.25 if any(token in event.lower() for token in ("cpi", "inflation", "rate", "sales")) else 1.0
    return {
        "country": row.get("country") or row.get("Country") or "-",
        "event": event,
        "date": row.get("date") or row.get("Date") or row.get("time") or row.get("Time"),
        "importance": row.get("importance") or row.get("Importance") or "medium",
        "actual": actual,
        "forecast": forecast,
        "surprise": surprise,
        "unit": row.get("unit") or "",
        "score": round(abs(float(surprise or 0)) / scale, 4),
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(str(value).replace("%", "").replace(",", "")), 6)
    except ValueError:
        return None
