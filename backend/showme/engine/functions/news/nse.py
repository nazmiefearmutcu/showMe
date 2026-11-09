"""NSE — News Search Engine (Awareness full-text search).

``q`` runs awareness full-text search over sourced stories (company names work, e.g.
"Berkshire"). ``symbol`` filters by entity when no ``q`` is given. The quality floor
is never lowered silently: when nothing matches at ``standard``, the response says
how many rows sit below it (``hidden_note``) and carries a ``relax`` hint.
"""

from __future__ import annotations

from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument
from showme.engine.data_sources.awareness import AwarenessClient, AwarenessUnavailable
from showme.engine.functions.news.awareness_news import (
    bounded_int,
    choice,
    client_for,
    fetch_news,
    filters_echo,
    input_required_result,
    ok_result,
    story_detail,
    text_param,
    unavailable_result,
)
from showme.engine.functions.news.cn import normalise_symbol


@FunctionRegistry.register
class NSEFunction(BaseFunction):
    code = "NSE"
    name = "News Search Engine"
    category = "news"
    description = (
        "Full-text search over sourced Awareness stories by company name, ticker or topic words, "
        "over a configurable window, with the quality floor shown rather than silently lowered."
    )

    _awareness: AwarenessClient | None = None  # test seam; None uses the process client

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        client = client_for(self._awareness)
        story_id = text_param(params.get("story_id"))
        query = text_param(params.get("q"))
        symbol = normalise_symbol(params.get("symbol")) if not query else ""
        if not query and not symbol and not story_id:
            return input_required_result(
                self.code,
                instrument,
                "NSE needs a search query (q), for example a company name or ticker.",
                "Type a company name or ticker and search again.",
            )
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

            hours = bounded_int(params.get("hours"), 720, 1, 1440)
            limit = bounded_int(params.get("limit"), 50, 1, 200)
            min_quality = choice(params.get("min_quality"), ("premium", "standard", "low"), "standard")
            base_query: dict[str, Any] = {"hours": hours, "limit": limit, "q": query}
            if symbol:
                base_query["symbols"] = [symbol]
            response, rows = await fetch_news(client, {**base_query, "min_quality": min_quality})
            hidden_note = None
            relax = None
            if not rows and min_quality == "standard":
                relax = {"min_quality": "low"}
                hidden_note = await _lower_floor_note(client, base_query)
        except AwarenessUnavailable as exc:
            return unavailable_result(self.code, instrument, exc.reason)

        data = {
            "status": "ok" if rows else "empty",
            "query": query,
            "symbol": symbol,
            "rows": rows,
            "count": len(rows),
            "next_cursor": response.meta.get("next_cursor"),
            "filters": filters_echo(q=query, symbol=symbol, hours=hours, limit=limit, min_quality=min_quality),
            "hidden_note": hidden_note,
            "relax": relax,
        }
        if not rows:
            data["next_actions"] = ["Try the company name instead of a ticker, or widen the hours window."]
        return ok_result(self.code, instrument, data, [response])


async def _lower_floor_note(client: AwarenessClient, base_query: dict[str, Any]) -> str:
    """How many matching rows the standard floor hides (counted, never shown as results)."""
    try:
        _, lower_rows = await fetch_news(client, {**base_query, "min_quality": "low"})
    except AwarenessUnavailable as exc:
        return f"no rows at quality standard; could not count rows below it ({exc.reason})"
    if not lower_rows:
        return "no rows match this search at any quality level in the window"
    return (
        f"{len(lower_rows)} row(s) match this search but sit below the standard quality floor and "
        "are hidden; retry with min_quality=low to include them"
    )
