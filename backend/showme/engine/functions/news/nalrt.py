"""NALRT — Critical News Alerts (high-importance Awareness stories).

Scans the Awareness news stream for stories whose awareness importance score is at
or above ``min_importance`` within the ``hours`` window. ``critical`` is importance
>= 85, ``high`` is the rest of the qualifying rows. Every row is a real sourced
story with its publisher and link.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.functions.news.awareness_news import (
    bounded_float,
    bounded_int,
    client_for,
    fetch_news,
    filters_echo,
    ok_result,
    unavailable_result,
)

CRITICAL_IMPORTANCE = 85.0


@FunctionRegistry.register
class NewsAlertFunction(BaseFunction):
    code = "NALRT"
    name = "Critical News Alerts"
    category = "news"
    description = (
        "Sourced stories whose Awareness importance score clears a floor within a recent window, "
        "graded critical (85 and up) or high, each linked to its publisher article."
    )
    asset_classes = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.ETF, AssetClass.INDEX)

    _awareness: AwarenessClient | None = None  # test seam; None uses the process client

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        client = client_for(self._awareness)
        # ``max_alert_age_hours`` is the legacy name of the same freshness window.
        hours = bounded_int(params.get("hours", params.get("max_alert_age_hours")), 6, 1, 168)
        min_importance = bounded_float(
            params.get("min_importance", params.get("threshold")), 70.0, 0.0, 100.0
        )
        limit = bounded_int(params.get("limit"), 30, 1, 200)
        try:
            response, stories = await fetch_news(
                client,
                {
                    "hours": hours,
                    "min_importance": min_importance,
                    "limit": limit,
                    "min_quality": "standard",
                },
            )
        except AwarenessUnavailable as exc:
            return unavailable_result(self.code, instrument, exc.reason)

        rows: list[dict[str, Any]] = []
        for story in stories:
            importance = float(story.get("importance_score") or 0.0)
            if importance < min_importance:
                continue
            rows.append({**story, "severity": "critical" if importance >= CRITICAL_IMPORTANCE else "high"})
        rows.sort(key=lambda row: float(row.get("importance_score") or 0.0), reverse=True)
        top_score = max((float(row.get("importance_score") or 0.0) for row in rows), default=0.0)
        critical = sum(1 for row in rows if row["severity"] == "critical")
        data = {
            "status": "ok" if rows else "empty",
            "rows": rows,
            "alerts": rows,
            "count": len(rows),
            "alert_count": len(rows),
            "critical_count": critical,
            "top_importance_score": top_score,
            "threshold": min_importance,
            "freshness_max_hours": hours,
            "next_cursor": response.meta.get("next_cursor"),
            "filters": filters_echo(hours=hours, min_importance=min_importance, limit=limit),
            "hidden_note": None,
        }
        if not rows:
            data["next_actions"] = ["Lower min_importance or widen the hours window."]
        return ok_result(self.code, instrument, data, [response])
