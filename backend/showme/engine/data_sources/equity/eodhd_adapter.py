"""EOD Historical Data adapter — global EOD prices, fundamentals.

Plan: $20/ay 60+ borsa. Anahtar yoksa adapter sessiz devre dışı.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class EODHDAdapter(BaseDataSource):
    name = "eodhd"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV, DataKind.FUNDAMENTALS, DataKind.EVENTS)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "EODHD_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://eodhd.com/api")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
        return self._client

    async def _get(self, path: str, **params: Any) -> Any:
        if not self.api_key:
            raise DataSourceError("EODHD_API_KEY not set")
        client = await self._client_()
        r = await client.get(path, params={**params, "api_token": self.api_key, "fmt": "json"})
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("EODHD needs symbol")
        if request.kind == DataKind.OHLCV:
            data = await self._get(f"/eod/{sym}", from_=request.start.strftime("%Y-%m-%d") if request.start else None,
                                   to=request.end.strftime("%Y-%m-%d") if request.end else None)
            df = pd.DataFrame(data)
            if df.empty:
                return df
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            return df.rename(columns={"adjusted_close": "adj_close"})
        if request.kind == DataKind.QUOTE:
            data = await self._get(f"/real-time/{sym}")
            from showme.engine.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=data.get("close"), open_24h=data.get("open"),
                high_24h=data.get("high"), low_24h=data.get("low"),
                volume_24h=data.get("volume"), source=self.name,
            )
        if request.kind == DataKind.FUNDAMENTALS:
            return await self._get(f"/fundamentals/{sym}")
        if request.kind == DataKind.EVENTS:
            return {
                "splits": await self._get(f"/splits/{sym}"),
                "dividends": await self._get(f"/div/{sym}"),
            }
        raise DataSourceError(f"unsupported kind {request.kind}")
