"""Finnhub adapter — quote, profile, fundamentals, estimates, recommendations, news.

DATA PIPELINE:
    Source: https://finnhub.io/api/v1
    Plan: 60 calls/min ücretsiz
    Latency: <500ms warm
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from showme.engine.utils.throttle import throttle


class FinnhubAdapter(BaseDataSource):
    name = "finnhub"
    supported_kinds = (
        DataKind.QUOTE, DataKind.OHLCV, DataKind.REFDATA,
        DataKind.FUNDAMENTALS, DataKind.EVENTS, DataKind.NEWS,
    )
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "FINNHUB_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://finnhub.io/api/v1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
                params={"token": self.api_key} if self.api_key else None,
            )
        return self._client

    @throttle(rps=1.0)
    async def _get(self, endpoint: str, **params: Any) -> Any:
        if not self.api_key:
            raise DataSourceError("FINNHUB_API_KEY not set")
        client = await self._client_()
        r = await client.get(endpoint, params={**params, "token": self.api_key})
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("Finnhub needs symbol")
        if request.kind == DataKind.QUOTE:
            data = await self._get("/quote", symbol=sym)
            from showme.engine.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=data.get("c"), close_prev=data.get("pc"),
                open_24h=data.get("o"), high_24h=data.get("h"), low_24h=data.get("l"),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            res = (request.interval or "D").upper()
            r = await self._get(
                "/stock/candle",
                symbol=sym, resolution=res,
                **{
                    "from": int((request.start or datetime(2020, 1, 1)).timestamp()),
                    "to": int((request.end or datetime.now()).timestamp()),
                },
            )
            if r.get("s") != "ok":
                return pd.DataFrame()
            df = pd.DataFrame({
                "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
                "close": r.get("c"), "volume": r.get("v"),
                "ts": pd.to_datetime(r.get("t"), unit="s"),
            }).set_index("ts")
            return df
        if request.kind == DataKind.REFDATA:
            data = await self._get("/stock/profile2", symbol=sym)
            from showme.engine.core.refdata import ReferenceData
            from showme.engine.core.quote import utcnow
            return ReferenceData(
                symbol=sym, name=data.get("name"), exchange=data.get("exchange"),
                country=data.get("country"), currency=data.get("currency"),
                industry=data.get("finnhubIndustry"),
                market_cap=(data.get("marketCapitalization") or 0) * 1_000_000,
                shares_outstanding=(data.get("shareOutstanding") or 0) * 1_000_000,
                website=data.get("weburl"),
                ipo_date=pd.to_datetime(data.get("ipo")) if data.get("ipo") else None,
                source=self.name, fetched_at=utcnow(),
            )
        if request.kind == DataKind.FUNDAMENTALS:
            return await self._get("/stock/financials-reported", symbol=sym, freq=request.extra.get("freq", "annual"))
        if request.kind == DataKind.EVENTS:
            return {
                "earnings": await self._get("/stock/earnings", symbol=sym),
                "calendar": await self._get("/calendar/earnings", symbol=sym),
                "splits": await self._get("/stock/split", symbol=sym),
                "dividends": await self._get("/stock/dividend2", symbol=sym),
            }
        if request.kind == DataKind.NEWS:
            return await self._get("/company-news", symbol=sym,
                                    **{"from": (request.start or datetime(2024, 1, 1)).strftime("%Y-%m-%d"),
                                       "to": (request.end or datetime.now()).strftime("%Y-%m-%d")})
        raise DataSourceError(f"unsupported kind {request.kind}")

    # ── Hot helpers used by EE/ANR functions ──
    async def recommendations(self, symbol: str) -> list[dict[str, Any]]:
        return await self._get("/stock/recommendation", symbol=symbol)

    async def price_target(self, symbol: str) -> dict[str, Any]:
        return await self._get("/stock/price-target", symbol=symbol)

    async def peers(self, symbol: str) -> list[str]:
        return await self._get("/stock/peers", symbol=symbol)

    async def metrics(self, symbol: str, metric: str = "all") -> dict[str, Any]:
        return await self._get("/stock/metric", symbol=symbol, metric=metric)
