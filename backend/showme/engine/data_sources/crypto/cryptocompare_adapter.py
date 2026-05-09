"""CryptoCompare adapter — multi-exchange aggregated crypto.

DATA PIPELINE:
    Source: https://min-api.cryptocompare.com/data
    Free anonymous: 100k req/month. Paid: CRYPTOCOMPARE_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class CryptoCompareAdapter(BaseDataSource):
    name = "cryptocompare"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV, DataKind.NEWS, DataKind.REFDATA)
    rate_limit_rps = 4.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("CRYPTOCOMPARE_API_KEY", "")
        self.base_url = (config or {}).get("base_url", "https://min-api.cryptocompare.com/data")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["authorization"] = f"Apikey {self.api_key}"
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=15, headers=headers)
        return self._client

    @staticmethod
    def _split(symbol: str) -> tuple[str, str]:
        s = symbol.upper()
        for q in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR"):
            if s.endswith(q) and len(s) > len(q):
                return s[: -len(q)], q
        return s, "USD"

    async def quote(self, symbol: str) -> dict[str, Any]:
        client = await self._client_()
        base, quote = self._split(symbol)
        r = await client.get("/pricemultifull",
                              params={"fsyms": base, "tsyms": quote})
        r.raise_for_status()
        d = ((r.json() or {}).get("RAW") or {}).get(base, {}).get(quote, {})
        return d

    async def histo_day(self, symbol: str, limit: int = 365,
                         exchange: str | None = None) -> pd.DataFrame:
        client = await self._client_()
        base, quote = self._split(symbol)
        params: dict[str, Any] = {"fsym": base, "tsym": quote, "limit": min(limit, 2000)}
        if exchange:
            params["e"] = exchange
        r = await client.get("/v2/histoday", params=params)
        r.raise_for_status()
        data = ((r.json() or {}).get("Data") or {}).get("Data") or []
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["ts"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("ts")[["open", "high", "low", "close", "volumefrom", "volumeto"]]
        return df.rename(columns={"volumefrom": "volume_base", "volumeto": "volume_quote"})

    async def news(self, categories: str | None = None,
                   lang: str = "EN", limit: int = 50) -> list[dict[str, Any]]:
        client = await self._client_()
        params: dict[str, Any] = {"lang": lang}
        if categories:
            params["categories"] = categories
        r = await client.get("/v2/news/", params=params)
        r.raise_for_status()
        payload = r.json() or {}
        if payload.get("Response") == "Error":
            raise DataSourceError(str(payload.get("Message") or "CryptoCompare news error"))
        return (payload.get("Data") or [])[:limit]

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if request.kind == DataKind.QUOTE:
            d = await self.quote(sym or "BTCUSDT")
            from showme.engine.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=d.get("PRICE"),
                bid=d.get("LASTVOLUME") and None,  # CC doesn't expose L1
                volume_24h=d.get("VOLUME24HOUR"),
                high_24h=d.get("HIGH24HOUR"), low_24h=d.get("LOW24HOUR"),
                close_prev=d.get("OPEN24HOUR"),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            return await self.histo_day(sym or "BTCUSDT", limit=request.limit or 365)
        if request.kind == DataKind.NEWS:
            return await self.news(categories=(request.extra or {}).get("category"))
        raise DataSourceError(f"unsupported kind {request.kind}")
