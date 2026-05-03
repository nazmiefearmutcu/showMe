"""Polygon.io adapter — REST + WS (real-time + 5y history)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from src.utils.throttle import throttle


class PolygonAdapter(BaseDataSource):
    name = "polygon"
    supported_kinds = (
        DataKind.QUOTE, DataKind.OHLCV, DataKind.TRADES,
        DataKind.OPTIONS_CHAIN, DataKind.NEWS,
    )
    rate_limit_rps = 0.083    # 5/min free; ~1/s when paid plan
    requires_api_key = True
    api_key_env = "POLYGON_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://api.polygon.io")
        self._client: httpx.AsyncClient | None = None
        if self.api_key:
            self.rate_limit_rps = 1.0  # paid tiers raise quota

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
            )
        return self._client

    @throttle(rps=1.0)
    async def _get(self, path: str, **params: Any) -> Any:
        if not self.api_key:
            raise DataSourceError("POLYGON_API_KEY not set")
        client = await self._client_()
        params.setdefault("apiKey", self.api_key)
        r = await client.get(path, params=params)
        if r.status_code == 429:
            raise DataSourceError("Polygon rate-limited")
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("Polygon needs symbol")
        if request.kind == DataKind.QUOTE:
            data = await self._get(f"/v2/last/trade/{sym}")
            from src.core.quote import Quote, utcnow
            res = data.get("results") or {}
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=res.get("p"),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            interval = request.interval or "1d"
            tf_map = {"1m": ("1", "minute"), "5m": ("5", "minute"), "15m": ("15", "minute"),
                       "1h": ("1", "hour"), "1d": ("1", "day"), "1w": ("1", "week")}
            mult, span = tf_map.get(interval, ("1", "day"))
            start = (request.start or datetime(2024, 1, 1)).strftime("%Y-%m-%d")
            end = (request.end or datetime.utcnow()).strftime("%Y-%m-%d")
            data = await self._get(f"/v2/aggs/ticker/{sym}/range/{mult}/{span}/{start}/{end}")
            results = data.get("results") or []
            df = pd.DataFrame([{
                "ts": pd.to_datetime(r["t"], unit="ms"),
                "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"],
                "volume": r["v"],
            } for r in results])
            return df.set_index("ts") if not df.empty else df
        if request.kind == DataKind.NEWS:
            data = await self._get("/v2/reference/news", **{"ticker": sym, "limit": request.limit or 50})
            return data.get("results") or []
        if request.kind == DataKind.OPTIONS_CHAIN:
            data = await self._get(f"/v3/snapshot/options/{sym}")
            return data.get("results") or []
        raise DataSourceError(f"unsupported kind {request.kind}")
