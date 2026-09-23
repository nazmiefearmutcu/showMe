"""Polymarket adapter — public CLOB markets snapshot.

DATA PIPELINE:
    Source: https://gamma-api.polymarket.com/markets (public, anahtarsız)
    Latency: <1s
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest,
)


class PolymarketAdapter(BaseDataSource):
    name = "polymarket"
    supported_kinds = (DataKind.OTHER, DataKind.EVENTS)
    rate_limit_rps = 2.0
    requires_api_key = False

    BASE = "https://gamma-api.polymarket.com"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.BASE, timeout=15)
        return self._client

    async def search(self, query: str | None = None, *,
                     active: bool = True, closed: bool = False,
                     limit: int = 30, tag_id: int | None = None,
                     min_liquidity: float = 0) -> list[dict[str, Any]]:
        client = await self._client_()
        return await fetch_markets(client, query, limit=limit, active=active,
                                   closed=closed, tag_id=tag_id,
                                   min_liquidity=min_liquidity)

    async def market(self, slug: str) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get(f"/markets/slug/{slug}")
        r.raise_for_status()
        return r.json() or {}

    async def fetch(self, request: DataRequest) -> Any:
        q = (request.extra or {}).get("query") or (
            request.symbols[0] if request.symbols else None
        )
        return await self.search(q, limit=request.limit or 30)


async def fetch_markets(client: httpx.AsyncClient, query: str | None = None, *,
                        active: bool = True, closed: bool = False,
                        limit: int = 100, tag_id: int | None = None,
                        min_liquidity: float = 0) -> list[dict[str, Any]]:
    """Filter before the provider limit, and page through its 100-row windows."""
    target = min(max(limit, 1), 400)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(4):
        params: dict[str, Any] = {"limit": min(100, target - len(rows)),
                                 "offset": offset, "order": "volume24hr",
                                 "ascending": "false", "archived": "false",
                                 "closed": str(closed).lower(),
                                 "liquidity_num_min": max(0, min_liquidity)}
        if active:
            params["active"] = "true"
        if active and not closed:
            params["end_date_min"] = datetime.now(timezone.utc).isoformat()
        if tag_id:
            params["tag_id"] = tag_id
        if query:
            params["search"] = query
        r = await client.get("https://gamma-api.polymarket.com/markets", params=params)
        r.raise_for_status()
        page = r.json() or []
        if isinstance(page, dict):
            page = page.get("data") or page.get("markets") or []
        if not isinstance(page, list) or not page:
            break
        offset += len(page)
        added = 0
        for row in page:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id") or row.get("slug") or row.get("question"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
        if len(rows) >= target or not added:
            break
    return rows[:target]
