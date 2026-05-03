"""Sentinel Hub satellite imagery adapter.

DATA PIPELINE:
    Source: https://services.sentinel-hub.com/api/v1
    Auth: SENTINELHUB_CLIENT_ID + SENTINELHUB_CLIENT_SECRET (OAuth2)
    Free quota: 30 000 requests/month.

API:
    process_image(bbox, date_from, date_to, dataset="sentinel-2-l2a") → bytes (PNG/TIFF)
    statistics(bbox, date_from, date_to)                              → JSON
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError,
)


_TOKEN_URL = "https://services.sentinel-hub.com/oauth/token"


class SentinelHubAdapter(BaseDataSource):
    name = "sentinelhub"
    supported_kinds = (DataKind.SATELLITE,)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "SENTINELHUB_CLIENT_ID"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.client_id = os.environ.get("SENTINELHUB_CLIENT_ID", "")
        self.client_secret = os.environ.get("SENTINELHUB_CLIENT_SECRET", "")
        self.base_url = (config or {}).get(
            "base_url", "https://services.sentinel-hub.com/api/v1"
        )
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def _maybe_refresh_token(self) -> None:
        if self._token and time.time() < self._token_exp - 60:
            return
        if not (self.client_id and self.client_secret):
            raise DataSourceError("Sentinel Hub credentials missing")
        client = await self._client_()
        r = await client.post(_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        r.raise_for_status()
        j = r.json()
        self._token = j.get("access_token")
        self._token_exp = time.time() + int(j.get("expires_in") or 3600)

    async def process_image(self, *, bbox: tuple[float, float, float, float],
                             date_from: str, date_to: str,
                             width: int = 512, height: int = 512,
                             dataset: str = "sentinel-2-l2a") -> bytes:
        """Returns a PNG image (true-color RGB) for the bbox / date window."""
        await self._maybe_refresh_token()
        client = await self._client_()
        evalscript = """//VERSION=3
        function setup() { return {input: ["B04","B03","B02"], output: {bands: 3}}; }
        function evaluatePixel(s) { return [s.B04*2.5, s.B03*2.5, s.B02*2.5]; }"""
        body = {
            "input": {
                "bounds": {"bbox": list(bbox), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                "data": [{
                    "type": dataset,
                    "dataFilter": {
                        "timeRange": {"from": date_from + "T00:00:00Z",
                                       "to":   date_to   + "T23:59:59Z"},
                    },
                }],
            },
            "output": {"width": width, "height": height,
                        "responses": [{"identifier": "default",
                                          "format": {"type": "image/png"}}]},
            "evalscript": evalscript,
        }
        r = await client.post(
            f"{self.base_url}/process", json=body,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        r.raise_for_status()
        return r.content

    async def statistics(self, *, bbox: tuple[float, float, float, float],
                          date_from: str, date_to: str,
                          dataset: str = "sentinel-2-l2a") -> dict[str, Any]:
        await self._maybe_refresh_token()
        client = await self._client_()
        body = {
            "input": {
                "bounds": {"bbox": list(bbox)},
                "data": [{"type": dataset,
                            "dataFilter": {"timeRange": {
                                "from": date_from + "T00:00:00Z",
                                "to":   date_to   + "T23:59:59Z"}}}],
            },
            "aggregation": {
                "timeRange": {"from": date_from + "T00:00:00Z",
                                 "to":   date_to   + "T23:59:59Z"},
                "aggregationInterval": {"of": "P30D"},
                "evalscript":
                    """//VERSION=3
                    function setup() { return {input: [{bands:["B04","B08"]}],
                                                output: [{id:"ndvi",bands:1,sampleType:"FLOAT32"}]}; }
                    function evaluatePixel(s) {
                        return {ndvi: [(s.B08 - s.B04) / (s.B08 + s.B04)]};
                    }""",
            },
            "calculations": {"default": {}},
        }
        r = await client.post(
            f"{self.base_url}/statistics", json=body,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        bbox = (request.extra or {}).get("bbox")
        date_from = (request.extra or {}).get("date_from")
        date_to = (request.extra or {}).get("date_to")
        if not (bbox and date_from and date_to):
            raise DataSourceError("Sentinel Hub requires bbox, date_from, date_to")
        op = (request.extra or {}).get("op", "image")
        if op == "stats":
            return await self.statistics(bbox=tuple(bbox),
                                            date_from=date_from, date_to=date_to)
        return await self.process_image(bbox=tuple(bbox),
                                           date_from=date_from, date_to=date_to)
