"""Mempool.space adapter — Bitcoin mempool fees, blocks, hash rate.

DATA PIPELINE:
    Source: https://mempool.space/api
    Free, no auth, rate-limit polite (~1/s ok).
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest


class MempoolAdapter(BaseDataSource):
    name = "mempool"
    supported_kinds = (DataKind.OTHER,)
    rate_limit_rps = 1.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://mempool.space/api")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10)
        return self._client

    async def fees(self) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get("/v1/fees/recommended")
        r.raise_for_status()
        return r.json()

    async def mempool_stats(self) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get("/mempool")
        r.raise_for_status()
        return r.json()

    async def blocks(self, limit: int = 10) -> list[dict[str, Any]]:
        client = await self._client_()
        r = await client.get("/v1/blocks")
        r.raise_for_status()
        return (r.json() or [])[:limit]

    async def hashrate(self) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get("/v1/mining/hashrate/3m")
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        op = (request.extra or {}).get("op", "fees")
        if op == "fees": return await self.fees()
        if op == "mempool": return await self.mempool_stats()
        if op == "blocks": return await self.blocks(limit=request.limit or 10)
        if op == "hashrate": return await self.hashrate()
        return await self.fees()
