"""Notion adapter — meeting notes, research databases, page search.

DATA PIPELINE:
    Source: https://api.notion.com/v1
    Auth: NOTION_API_TOKEN ("Internal Integration Token").
    Rate-limit: 3 req/s (Notion's own limit).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class NotionAdapter(BaseDataSource):
    name = "notion"
    supported_kinds = (DataKind.OTHER, DataKind.NEWS)
    rate_limit_rps = 3.0
    requires_api_key = True
    api_key_env = "NOTION_API_TOKEN"

    NOTION_VERSION = "2022-06-28"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.token = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://api.notion.com/v1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=15,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": self.NOTION_VERSION,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def search(self, query: str, *, page_size: int = 25) -> list[dict[str, Any]]:
        if not self.token:
            raise DataSourceError("NOTION_API_TOKEN not set")
        client = await self._client_()
        r = await client.post("/search", json={"query": query, "page_size": page_size})
        r.raise_for_status()
        return ((r.json() or {}).get("results") or [])

    async def page(self, page_id: str) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get(f"/pages/{page_id}")
        r.raise_for_status()
        return r.json()

    async def page_blocks(self, page_id: str, *, page_size: int = 100) -> list[dict[str, Any]]:
        client = await self._client_()
        r = await client.get(f"/blocks/{page_id}/children",
                              params={"page_size": page_size})
        r.raise_for_status()
        return ((r.json() or {}).get("results") or [])

    async def query_database(self, database_id: str,
                              filter_: dict | None = None,
                              page_size: int = 50) -> list[dict[str, Any]]:
        client = await self._client_()
        body: dict[str, Any] = {"page_size": page_size}
        if filter_:
            body["filter"] = filter_
        r = await client.post(f"/databases/{database_id}/query", json=body)
        r.raise_for_status()
        return ((r.json() or {}).get("results") or [])

    async def fetch(self, request: DataRequest) -> Any:
        q = (request.extra or {}).get("query") or (
            request.symbols[0] if request.symbols else None
        )
        if not q:
            raise DataSourceError("Notion requires a query")
        return await self.search(q, page_size=request.limit or 25)
