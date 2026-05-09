"""OpenSky — flight tracking. 4000/day public, more with auth."""

from __future__ import annotations

import os
from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest


class OpenSkyAdapter(BaseDataSource):
    name = "opensky"
    supported_kinds = (DataKind.OTHER,)
    rate_limit_rps = 0.05
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://opensky-network.org/api")
        self._client: httpx.AsyncClient | None = None
        self.user = os.environ.get("OPENSKY_USERNAME")
        self.pwd = os.environ.get("OPENSKY_PASSWORD")

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            auth = (self.user, self.pwd) if self.user and self.pwd else None
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds, auth=auth)
        return self._client

    async def fetch(self, request: DataRequest) -> Any:
        client = await self._client_()
        r = await client.get("/states/all")
        r.raise_for_status()
        return r.json()
