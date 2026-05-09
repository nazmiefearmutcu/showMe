"""GDELT 2.0 DOC API — ücretsiz, 65 dil, 15dk gecikmeli haber.

DATA PIPELINE:
    Source: https://api.gdeltproject.org/api/v2/doc/doc
    Latency: <1.5s
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class GDELTAdapter(BaseDataSource):
    name = "gdelt"
    supported_kinds = (DataKind.NEWS,)
    rate_limit_rps = 0.2
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.gdeltproject.org/api/v2/doc/doc"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
            )
        return self._client

    async def search(
        self, query: str, *,
        max_records: int = 50,
        start: datetime | None = None,
        end: datetime | None = None,
        sort: str = "DateDesc",
        mode: str = "ArtList",
    ) -> list[dict[str, Any]]:
        client = await self._client_()
        params: dict[str, Any] = {
            "query": query,
            "format": "json",
            "maxrecords": max(1, min(int(max_records), 250)),
            "sort": sort,
            "mode": mode,
        }
        if start:
            params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
        if end:
            params["enddatetime"] = end.strftime("%Y%m%d%H%M%S")
        r = await client.get(self.base_url, params=params)
        r.raise_for_status()
        try:
            return (r.json() or {}).get("articles", []) or []
        except Exception:
            return []

    async def fetch(self, request: DataRequest) -> list[dict[str, Any]]:
        q = request.extra.get("query") or (
            request.instrument.symbol if request.instrument else None
        ) or (request.symbols[0] if request.symbols else None)
        if not q:
            raise DataSourceError("GDELT requires a query")
        return await self.search(
            q, start=request.start, end=request.end,
            max_records=request.limit or 50,
        )
