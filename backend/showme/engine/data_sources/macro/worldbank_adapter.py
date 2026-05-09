"""World Bank Indicators API — anahtarsız."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class WorldBankAdapter(BaseDataSource):
    name = "worldbank"
    supported_kinds = (DataKind.ECON_SERIES,)
    rate_limit_rps = 5.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.worldbank.org/v2"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
            )
        return self._client

    async def indicator(
        self, country: str, indicator: str, *,
        start: int = 1990, end: int = 2025,
    ) -> pd.DataFrame:
        client = await self._client_()
        url = f"/country/{country}/indicator/{indicator}"
        params = {"format": "json", "date": f"{start}:{end}", "per_page": 200}
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return pd.DataFrame()
        rows = data[1] or []
        df = pd.DataFrame([
            {"year": int(row["date"]), "value": row["value"]}
            for row in rows if row.get("value") is not None
        ])
        return df.set_index("year").sort_index() if not df.empty else df

    async def fetch(self, request: DataRequest) -> Any:
        country = request.extra.get("country", "USA")
        indicator = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not indicator:
            raise DataSourceError("WorldBank requires indicator code (e.g. 'FP.CPI.TOTL.ZG')")
        return await self.indicator(country, indicator)
