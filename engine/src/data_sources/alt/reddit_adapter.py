"""Reddit social adapter — read-only via PRAW (or HTTP JSON fallback)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest


class RedditAdapter(BaseDataSource):
    name = "reddit"
    supported_kinds = (DataKind.SOCIAL,)
    rate_limit_rps = 1.0
    requires_api_key = False  # public JSON works without OAuth (rate-limited)

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.subreddits: list[str] = (config or {}).get(
            "subreddits", ["wallstreetbets", "stocks", "investing"]
        )
        self.user_agent = os.environ.get("REDDIT_USER_AGENT", "showme-bot/0.1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={"User-Agent": self.user_agent},
            )
        return self._client

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        client = await self._client_()
        out: list[dict[str, Any]] = []
        ticker = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        for sr in self.subreddits:
            url = f"https://www.reddit.com/r/{sr}/search.json" if ticker else f"https://www.reddit.com/r/{sr}.json"
            params = {"q": ticker, "restrict_sr": "1", "limit": request.limit or 25,
                      "sort": "new"} if ticker else {"limit": request.limit or 25}
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
            except Exception:
                continue
            data = r.json()
            for child in data.get("data", {}).get("children", []):
                p = child.get("data", {})
                out.append({
                    "subreddit": sr,
                    "title": p.get("title"),
                    "score": p.get("score"),
                    "num_comments": p.get("num_comments"),
                    "url": "https://reddit.com" + (p.get("permalink") or ""),
                    "created_at": datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc).isoformat(),
                    "author": p.get("author"),
                })
        return out
