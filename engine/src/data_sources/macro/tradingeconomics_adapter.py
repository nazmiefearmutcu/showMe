"""TradingEconomics adapter (demo: guest:guest)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class TradingEconomicsAdapter(BaseDataSource):
    name = "tradingeconomics"
    supported_kinds = (DataKind.ECON_SERIES, DataKind.EVENTS, DataKind.QUOTE)
    rate_limit_rps = 1.0
    requires_api_key = False  # demo guest:guest

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("TRADINGECONOMICS_API_KEY", "guest:guest")
        self.base_url = (config or {}).get("base_url", "https://api.tradingeconomics.com")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def calendar(self, country: str | None = None,
                       importance: int | None = None,
                       start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        client = await self._client_()
        params = {"c": self.api_key, "f": "json"}
        path = "/calendar"
        if country:
            path = f"/calendar/country/{country}"
        if importance:
            params["importance"] = importance
        if start and end:
            path = f"{path}/{start}/{end}" if not country else path
        r = await client.get(path, params=params)
        r.raise_for_status()
        return r.json() or []

    async def fetch(self, request: DataRequest) -> Any:
        if request.kind == DataKind.EVENTS:
            country = request.extra.get("country")
            return await self.calendar(country=country, importance=request.extra.get("importance"),
                                        start=request.extra.get("start"), end=request.extra.get("end"))
        if request.kind == DataKind.ECON_SERIES:
            ind = request.extra.get("indicator", "gdp")
            country = request.extra.get("country", "united states")
            client = await self._client_()
            r = await client.get(f"/historical/country/{country}/indicator/{ind}",
                                  params={"c": self.api_key, "f": "json"})
            r.raise_for_status()
            return r.json()
        raise DataSourceError(f"unsupported kind {request.kind}")
