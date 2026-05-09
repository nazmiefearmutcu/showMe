"""Polymarket adapter — public CLOB markets snapshot.

DATA PIPELINE:
    Source: https://gamma-api.polymarket.com/markets (public, anahtarsız)
    Latency: <1s
"""

from __future__ import annotations

from typing import Any

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
                     limit: int = 30, tag_id: int | None = None) -> list[dict[str, Any]]:
        client = await self._client_()
        params: dict[str, Any] = {"limit": limit, "order": "volume",
                                    "ascending": "false"}
        if active:
            params["active"] = "true"
        if closed:
            params["closed"] = "true"
        if tag_id:
            params["tag_id"] = tag_id
        if query:
            params["search"] = query
        r = await client.get("/markets", params=params)
        r.raise_for_status()
        return r.json() or []

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
