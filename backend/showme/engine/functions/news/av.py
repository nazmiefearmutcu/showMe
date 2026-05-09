"""AV — Audio/Video Archive (podcasts + earnings call replays)."""

from __future__ import annotations

import re
from typing import Any

from showme.engine.core.base_function import BaseFunction, FunctionRegistry, FunctionResult
from showme.engine.core.instrument import Instrument


_PODCAST_FEEDS = [
    "https://feeds.npr.org/510289/podcast.xml",  # Planet Money
    "https://feeds.npr.org/510325/podcast.xml",  # The Indicator from Planet Money
    "https://feeds.npr.org/510318/podcast.xml",  # Up First, for current audio headlines
    "https://feeds.simplecast.com/3hnxp7yk",      # Finance/business interview archive
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
        limit = max(1, min(int(params.get("limit", 25) or 25), 100))
        query = str(params.get("query") or "").strip()
        if not (params.get("live_media") or params.get("live")):
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "model",
                    "reason": "Live media was disabled for this run.",
                    "rows": _media_template(),
                    "query": query,
                },
                sources=["podcast_directory_model"],
                metadata={"live": False},
            )
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        parsed_feeds = 0
        try:
            import feedparser
            import asyncio
            import httpx
            timeout = float(params.get("media_timeout", 6))
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "showMe-media-archive/1.0"},
            ) as client:
                rs = await asyncio.gather(*(client.get(u) for u in _PODCAST_FEEDS), return_exceptions=True)
            for feed_url, r in zip(_PODCAST_FEEDS, rs, strict=False):
                if isinstance(r, Exception):
                    errors.append(f"{feed_url}: {r}")
                    continue
                if getattr(r, "status_code", 0) >= 400:
                    errors.append(f"{feed_url}: HTTP {r.status_code}")
                    continue
                feed = feedparser.parse(r.text)
                if not feed.entries:
                    errors.append(f"{feed_url}: no RSS entries")
                    continue
                parsed_feeds += 1
                for entry in feed.entries[: max(limit * 3, 15)]:
                    row = _media_row(feed.feed, entry)
                    if _matches_query(row, query):
                        items.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc) or type(exc).__name__)
        items = _dedupe(items)[:limit]
        if not items:
            reason = "Podcast RSS feeds returned no matching playable media."
            return FunctionResult(
                code=self.code,
                instrument=None,
                data={
                    "status": "provider_unavailable",
                    "reason": reason,
                    "rows": [],
                    "query": query,
                    "feed_count": parsed_feeds,
                    "next_actions": [
                        "Clear or broaden the media query.",
                        "Open Raw function payload to inspect RSS provider errors.",
                    ],
                },
                sources=["podcast_rss"],
                metadata={"provider_errors": errors, "live": True},
            )
        return FunctionResult(
            code=self.code,
            instrument=None,
            data={
                "status": "ok",
                "rows": items,
                "query": query,
                "feed_count": parsed_feeds,
                "count": len(items),
            },
            sources=["podcast_rss"],
            metadata={"provider_errors": errors, "live": True},
        )


def _media_row(feed: Any, entry: Any) -> dict[str, Any]:
    enclosures = list(entry.get("enclosures") or [])
    enclosure = enclosures[0] if enclosures else {}
    article_url = entry.get("link")
    audio_url = enclosure.get("href")
    duration = entry.get("itunes_duration") or entry.get("duration")
    summary = _strip_html(entry.get("summary") or entry.get("description") or "")
    return {
        "feed": feed.get("title"),
        "source": feed.get("title"),
        "title": entry.get("title"),
        "url": audio_url or article_url,
        "source_url": article_url,
        "published": entry.get("published"),
        "duration": duration,
        "media_type": enclosure.get("type") or "audio",
        "audio_url": audio_url,
        "summary": summary[:700],
    }


def _matches_query(row: dict[str, Any], query: str) -> bool:
    q = (query or "").strip().lower()
    if q in {"", "market", "markets", "market news", "audio", "video", "podcast"}:
        return True
    haystack = " ".join(str(row.get(key) or "") for key in ("feed", "title", "summary")).lower()
    terms = [term for term in re.findall(r"[a-z0-9]+", q) if len(term) > 2]
    return all(term in haystack for term in terms[:4]) if terms else True


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("audio_url") or row.get("link") or row.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()
