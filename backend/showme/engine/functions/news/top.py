"""TOP — Top News (sourced story leads from the Awareness news service).

Reads ``GET /v1/markets/news?story=true`` so every row is one collapsed story at
quality >= standard, with publisher tier, quality reasons, importance and
FinBERT sentiment already computed by awareness. No RSS, GDELT or model path.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.functions.news.awareness_news import (
    bounded_float,
    bounded_int,
    client_for,
    csv_list,
    fetch_news,
    filters_echo,
    ok_result,
    story_detail,
    text_param,
    unavailable_result,
)


@FunctionRegistry.register
class TOPFunction(BaseFunction):
    code = "TOP"
    name = "Top News"
    asset_classes = ()  # global
    category = "news"
    description = (
        "Top sourced news stories from the Awareness service: one row per story at quality "
        "standard or better, ranked by awareness importance, with publisher tier and sentiment."
    )

    _awareness: AwarenessClient | None = None  # test seam; None uses the process client

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        client = client_for(self._awareness)
        story_id = text_param(params.get("story_id"))
        try:
            if story_id:
                story, responses = await story_detail(client, story_id)
                data: dict[str, Any] = {
                    "status": "ok" if story else "empty",
                    "story": story,
                    "rows": [],
                    "count": 0,
                    "next_cursor": None,
                    "filters": {"story_id": story_id},
                    "hidden_note": None if story else "story not found in the Awareness service",
                }
                return ok_result(self.code, instrument, data, responses)

            hours = _hours(params)
            limit = bounded_int(params.get("limit"), 50, 1, 200)
            min_quality, floor_warnings = _quality_floor(params.get("min_quality"))
            topics = csv_list(params.get("topics"), lower=True)
            asset_classes = csv_list(params.get("asset_classes"), lower=True)
            countries = csv_list(params.get("countries"), upper=True)
            # ``query`` is the legacy name of ``q``; routed profile defaults no longer inject it.
            query = text_param(params.get("q")) or text_param(params.get("query"))
            # ``_epoch`` is the Welcome feed's cache-buster: it changes the request key, never the data.
            _ = params.get("_epoch")
            response, rows = await fetch_news(
                client,
                {
                    "hours": hours,
                    "limit": limit,
                    "min_quality": min_quality,
                    "topics": topics,
                    "asset_classes": asset_classes,
                    "countries": countries,
                    "q": query,
                },
            )
        except AwarenessUnavailable as exc:
            return unavailable_result(self.code, instrument, exc.reason)

        data = {
            "status": "ok" if rows else "empty",
            "rows": rows,
            "count": len(rows),
            "next_cursor": response.meta.get("next_cursor"),
            "filters": filters_echo(
                hours=hours,
                limit=limit,
                min_quality=min_quality,
                topics=topics,
                asset_classes=asset_classes,
                countries=countries,
                q=query,
            ),
            "hidden_note": None,
        }
        if not rows:
            data["next_actions"] = ["Widen the hours window or remove the topic, asset class or country filters."]
        return ok_result(self.code, instrument, data, [response], extra_warnings=floor_warnings)


# TOP never shows low-quality news: the floor is premium or standard only.
TOP_QUALITY_FLOORS = ("premium", "standard")


def _quality_floor(value: Any) -> tuple[str, list[str]]:
    """``min_quality`` for TOP. Anything outside premium/standard (``low`` included) is clamped to standard and reported."""
    requested = str(value or "").strip().lower()
    if not requested:
        return "standard", []
    if requested in TOP_QUALITY_FLOORS:
        return requested, []
    return "standard", [
        f"min_quality '{requested}' is not offered on TOP; showing standard and above "
        "(TOP never shows low-quality news)."
    ]


def _hours(params: dict[str, Any]) -> int:
    """``hours`` (1-168, default 24); the legacy ``max_age_days`` maps to days x 24."""
    if params.get("hours") not in (None, ""):
        return bounded_int(params.get("hours"), 24, 1, 168)
    if params.get("max_age_days") not in (None, ""):
        return bounded_int(bounded_float(params.get("max_age_days"), 1.0, 0.0, 7.0) * 24, 24, 1, 168)
    if params.get("days") not in (None, ""):
        return bounded_int(bounded_float(params.get("days"), 1.0, 0.0, 7.0) * 24, 24, 1, 168)
    return 24
