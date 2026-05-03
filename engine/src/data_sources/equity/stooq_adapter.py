"""Stooq adapter — global EOD CSV, anahtarsız.

DATA PIPELINE:
    Source: https://stooq.com/q/d/l/?s={sym}&i=d
    Latency: <1.5s (CSV download)
    Caveat: HTML scraping; cache aggressively (1h+).
"""

from __future__ import annotations

import os
from io import StringIO
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class StooqAdapter(BaseDataSource):
    name = "stooq"
    supported_kinds = (DataKind.OHLCV,)
    rate_limit_rps = 0.5
    requires_api_key = True
    api_key_env = "STOOQ_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://stooq.com/q/d/l")
        self.api_key = os.environ.get(self.api_key_env, "")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True)
        return self._client

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("Stooq needs symbol")
        if not self.api_key:
            raise DataSourceError("STOOQ_API_KEY not set; use yfinance OHLCV fallback")
        client = await self._client_()
        r = await client.get(self.base_url, params={"s": sym.lower(), "i": "d", "apikey": self.api_key})
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
        df.columns = [c.lower() for c in df.columns]
        return df
