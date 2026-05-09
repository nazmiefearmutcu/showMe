"""Finnhub News adapter — uses the same API key as FinnhubAdapter."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class FinnhubNewsAdapter(BaseDataSource):
    name = "finnhub_news"
    supported_kinds = (DataKind.NEWS,)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "FINNHUB_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://finnhub.io/api/v1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        if not self.api_key:
            raise DataSourceError("FINNHUB_API_KEY not set")
        client = await self._client_()
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if sym:
            start = (request.start or (datetime.utcnow() - timedelta(days=14))).strftime("%Y-%m-%d")
            end = (request.end or datetime.utcnow()).strftime("%Y-%m-%d")
            r = await client.get("/company-news", params={
                "symbol": sym, "from": start, "to": end, "token": self.api_key,
            })
        else:
            r = await client.get("/news", params={
                "category": request.extra.get("category", "general"),
                "token": self.api_key,
            })
        r.raise_for_status()
        return r.json() or []
