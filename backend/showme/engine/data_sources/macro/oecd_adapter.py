"""OECD SDMX-JSON adapter — anahtarsız."""

from __future__ import annotations

from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class OECDAdapter(BaseDataSource):
    name = "oecd"
    supported_kinds = (DataKind.ECON_SERIES,)
    rate_limit_rps = 2.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://stats.oecd.org/SDMX-JSON/data"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def fetch(self, request: DataRequest) -> Any:
        ds = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not ds:
            raise DataSourceError("OECD requires dataset code (e.g. 'EO/USA.GDPV.A')")
        client = await self._client_()
        r = await client.get(f"/{ds}")
        r.raise_for_status()
        # SDMX-JSON parsing simplifié — return raw dict; downstream decides.
        return r.json()
