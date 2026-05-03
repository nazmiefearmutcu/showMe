"""AV — Audio/Video Archive (podcasts + earnings call replays)."""

from __future__ import annotations

from typing import Any

from src.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from src.core.instrument import Instrument


_PODCAST_FEEDS = [
    "https://feeds.simplecast.com/3hnxp7yk",   # Bloomberg Surveillance
    "https://feeds.simplecast.com/Mw4dEZ_F",   # Odd Lots
    "https://feeds.simplecast.com/RfYJLUMb",   # Bloomberg Daybreak
    "https://feeds.megaphone.fm/all-in-with-chamath-jason-sacks-friedberg",
]


def _media_template() -> list[dict[str, Any]]:
    return [
        {"feed": "Market Audio", "title": "Macro and market briefing",
         "link": None, "published": None},
        {"feed": "Earnings Replay", "title": "Sample earnings call replay",
         "link": None, "published": None},
    ]


@FunctionRegistry.register
class AVFunction(BaseFunction):
    code = "AV"
    name = "Audio/Video Archive"
    category = "news"

    async def execute(self, instrument: Instrument | None = None, **params: Any) -> FunctionResult:
        if not (params.get("live_media") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data=_media_template(),
                sources=["podcast_directory"],
            )
        items: list[dict[str, Any]] = []
        source = "podcast_rss"
        try:
            import feedparser
            import asyncio
            import httpx
            timeout = float(params.get("media_timeout", 6))
            async with httpx.AsyncClient(timeout=timeout) as client:
                rs = await asyncio.gather(*(client.get(u) for u in _PODCAST_FEEDS), return_exceptions=True)
            for r in rs:
                if isinstance(r, Exception):
                    continue
                feed = feedparser.parse(r.text)
                for entry in feed.entries[:15]:
                    items.append({
                        "feed": feed.feed.get("title"),
                        "title": entry.get("title"),
                        "link": entry.get("link"),
                        "published": entry.get("published"),
                    })
        except Exception:
            pass
        if not items:
            items = _media_template()
            source = "podcast_directory"
        return FunctionResult(code=self.code, instrument=None, data=items,
                              sources=[source])
