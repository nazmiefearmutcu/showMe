"""NI — News by Topic (BANKS, EARN, FED, CHIPS, OIL, TECH, MACRO, WAR, M&A, IPO).

Each preset maps onto awareness taxonomy tags (``topics`` and ``asset_classes``
filters, OR within a list, AND across the two). Awareness has no semiconductor or
bank tag, so CHIPS, TECH and BANKS are the nearest tags and are labelled as such
in the methodology.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.functions.news.awareness_news import (
    bounded_int,
    client_for,
    fetch_news,
    filters_echo,
    ok_result,
    story_detail,
    text_param,
    unavailable_result,
)

DEFAULT_TOPIC = "MACRO"

# Preset key -> awareness taxonomy filters (topics = OR, asset_classes = AND with topics).
TOPIC_PRESETS: dict[str, dict[str, list[str]]] = {
    "BANKS": {"topics": ["funding_liquidity", "credit_stress", "earnings"], "asset_classes": ["equities"]},
    "EARN": {"topics": ["earnings", "guidance"]},
    "FED": {"topics": ["central_bank"]},
    "CHIPS": {"topics": ["supply_chain", "trade_tariffs", "product_launch"], "asset_classes": ["equities"]},
    "OIL": {"topics": ["energy"]},
    "TECH": {"topics": ["product_launch", "cyber_outage"], "asset_classes": ["equities"]},
    "MACRO": {"topics": ["inflation", "employment", "growth_recession", "fiscal_policy"]},
    "WAR": {"topics": ["geopolitics", "sanctions"]},
    "M&A": {"topics": ["m_and_a"]},
    "IPO": {"topics": ["ipo"]},
}


@FunctionRegistry.register
class NIFunction(BaseFunction):
    code = "NI"
    name = "News by Topic"
    category = "news"
    description = (
        "Sourced news for one topic preset (earnings, Fed, oil, M&A, IPO and more) from the "
        "Awareness taxonomy, one row per story at quality standard or better."
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

            requested = text_param(params.get("topic")).upper() or DEFAULT_TOPIC
            hidden_note = None
            topic = requested
            if topic not in TOPIC_PRESETS:
                hidden_note = f"unknown topic '{requested}'; showing {DEFAULT_TOPIC}"
                topic = DEFAULT_TOPIC
            preset = TOPIC_PRESETS[topic]
            hours = bounded_int(params.get("hours"), 48, 1, 168)
            limit = bounded_int(params.get("limit"), 50, 1, 200)
            response, rows = await fetch_news(
                client,
                {
                    "hours": hours,
                    "limit": limit,
                    "min_quality": "standard",
                    "topics": preset.get("topics", []),
                    "asset_classes": preset.get("asset_classes", []),
                },
            )
        except AwarenessUnavailable as exc:
            return unavailable_result(self.code, instrument, exc.reason)

        data = {
            "status": "ok" if rows else "empty",
            "topic": topic,
            "rows": rows,
            "count": len(rows),
            "next_cursor": response.meta.get("next_cursor"),
            "filters": filters_echo(hours=hours, limit=limit, **preset),
            "hidden_note": hidden_note,
        }
        if not rows:
            data["next_actions"] = ["Widen the hours window or pick another topic."]
        return ok_result(self.code, instrument, data, [response])
