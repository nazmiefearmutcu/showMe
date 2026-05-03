"""Alpha Vantage adapter — quotes, fundamentals, technical indicators.

DATA PIPELINE:
    Source: https://www.alphavantage.co/query
    Plan: 5 calls/min, 500/day free.
    Latency: <1s.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from src.utils.throttle import throttle


class AlphaVantageAdapter(BaseDataSource):
    name = "alphavantage"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV, DataKind.FUNDAMENTALS)
    rate_limit_rps = 0.083
    requires_api_key = True
    api_key_env = "ALPHAVANTAGE_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get(
            "base_url", "https://www.alphavantage.co/query"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    @throttle(rps=0.083)
    async def _get(self, **params: Any) -> dict[str, Any]:
        if not self.api_key:
            raise DataSourceError("ALPHAVANTAGE_API_KEY not set")
        client = await self._client_()
        r = await client.get(self.base_url, params={**params, "apikey": self.api_key})
        r.raise_for_status()
        data = r.json()
        if "Note" in data or "Information" in data:
            raise DataSourceError(f"AlphaVantage rate-limited: {data.get('Note') or data.get('Information')}")
        return data

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("AlphaVantage needs symbol")
        if request.kind == DataKind.QUOTE:
            data = await self._get(function="GLOBAL_QUOTE", symbol=sym)
            q = data.get("Global Quote", {})
            from src.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=float(q.get("05. price", 0) or 0),
                open_24h=float(q.get("02. open", 0) or 0),
                high_24h=float(q.get("03. high", 0) or 0),
                low_24h=float(q.get("04. low", 0) or 0),
                close_prev=float(q.get("08. previous close", 0) or 0),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            interval = (request.interval or "1d").lower()
            if interval in ("1d", "daily", "d"):
                data = await self._get(function="TIME_SERIES_DAILY",
                                       symbol=sym, outputsize="full")
                series = data.get("Time Series (Daily)", {})
            else:
                data = await self._get(function="TIME_SERIES_INTRADAY",
                                       symbol=sym, interval=interval)
                series = data.get(f"Time Series ({interval})", {})
            df = pd.DataFrame(series).T.astype(float)
            df.columns = [c.split(". ", 1)[1] for c in df.columns]
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df = df.rename(columns={
                "open": "open", "high": "high", "low": "low",
                "close": "close", "volume": "volume",
            })
            return df
        if request.kind == DataKind.FUNDAMENTALS:
            return {
                "overview": await self._get(function="OVERVIEW", symbol=sym),
                "income": await self._get(function="INCOME_STATEMENT", symbol=sym),
                "balance": await self._get(function="BALANCE_SHEET", symbol=sym),
                "cashflow": await self._get(function="CASH_FLOW", symbol=sym),
                "earnings": await self._get(function="EARNINGS", symbol=sym),
            }
        raise DataSourceError(f"unsupported kind {request.kind}")
