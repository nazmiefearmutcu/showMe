"""IMF DataMapper API — anahtarsız."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class IMFAdapter(BaseDataSource):
    name = "imf"
    supported_kinds = (DataKind.ECON_SERIES,)
    rate_limit_rps = 2.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://www.imf.org/external/datamapper/api/v1"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def fetch(self, request: DataRequest) -> Any:
        ind = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        country = request.extra.get("country", "USA")
        if not ind:
            raise DataSourceError("IMF requires indicator code (e.g. 'NGDP_RPCH')")
        client = await self._client_()
        r = await client.get(f"/{ind}/{country}")
        r.raise_for_status()
        data = (r.json() or {}).get("values", {}).get(ind, {}).get(country, {})
        df = pd.DataFrame([{"year": int(k), "value": v} for k, v in data.items()])
        return df.set_index("year").sort_index() if not df.empty else df
