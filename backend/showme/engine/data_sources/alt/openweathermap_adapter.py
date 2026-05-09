"""OpenWeatherMap adapter — temel sıcaklık + 7 günlük forecast."""

from __future__ import annotations

import os
from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class OpenWeatherMapAdapter(BaseDataSource):
    name = "openweathermap"
    supported_kinds = (DataKind.WEATHER,)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "OPENWEATHERMAP_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://api.openweathermap.org/data/3.0")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def onecall(self, lat: float, lon: float) -> dict[str, Any]:
        if not self.api_key:
            raise DataSourceError("OPENWEATHERMAP_API_KEY not set")
        client = await self._client_()
        r = await client.get("/onecall", params={
            "lat": lat, "lon": lon, "appid": self.api_key, "units": "metric",
        })
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        lat = request.extra.get("lat")
        lon = request.extra.get("lon")
        if lat is None or lon is None:
            raise DataSourceError("OpenWeatherMap requires lat/lon")
        return await self.onecall(float(lat), float(lon))
