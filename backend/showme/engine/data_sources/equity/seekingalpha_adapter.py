"""SeekingAlpha transcript scraper (best-effort, public RSS only).

Plan §16.9 — TRAN için ücretsiz kaynak. SeekingAlpha rate-limit yapar;
biz sadece public RSS feed'inden meta veri çekiyoruz, full text için
investor relations sitesini deneriz.
"""

from __future__ import annotations

from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest


class SeekingAlphaAdapter(BaseDataSource):
    name = "seekingalpha"
    supported_kinds = (DataKind.NEWS, DataKind.OTHER)
    rate_limit_rps = 0.2
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (ShowMe/0.2)"},
                follow_redirects=True,
            )
        return self._client

    async def transcripts(self, ticker: str) -> list[dict[str, Any]]:
        client = await self._client_()
        feed_url = f"https://seekingalpha.com/api/sa/combined/{ticker}.xml"
        try:
            r = await client.get(feed_url)
            if r.status_code != 200:
                return []
        except Exception:
            return []
        try:
            import feedparser  # type: ignore
        except Exception:
            return []
        parsed = feedparser.parse(r.text)
        out: list[dict[str, Any]] = []
        for entry in parsed.entries:
            title = entry.get("title", "")
            if "transcript" not in title.lower() and "earnings call" not in title.lower():
                continue
            out.append({
                "ticker": ticker.upper(),
                "title": title,
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
            })
        return out

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            return []
        return await self.transcripts(sym)
