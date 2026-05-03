"""CoinGecko adapter — public crypto market data, anahtarsız (30/min).

DATA PIPELINE:
    Source: https://api.coingecko.com/api/v3
    Free: 30 calls/min. Pro: COINGECKO_API_KEY ile 500/min.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


# Common Binance-style → CoinGecko id map.
_ID_MAP = {
    "BTC":  "bitcoin",   "BTCUSDT": "bitcoin",
    "ETH":  "ethereum",  "ETHUSDT": "ethereum",
    "BNB":  "binancecoin", "BNBUSDT": "binancecoin",
    "SOL":  "solana",    "SOLUSDT": "solana",
    "ADA":  "cardano",   "ADAUSDT": "cardano",
    "XRP":  "ripple",    "XRPUSDT": "ripple",
    "DOGE": "dogecoin",  "DOGEUSDT": "dogecoin",
    "MATIC":"polygon-pos","MATICUSDT":"polygon-pos",
    "DOT":  "polkadot",  "DOTUSDT": "polkadot",
    "AVAX": "avalanche-2","AVAXUSDT":"avalanche-2",
    "LINK": "chainlink", "LINKUSDT":"chainlink",
    "TRX":  "tron",      "TRXUSDT": "tron",
    "TON":  "the-open-network", "TONUSDT":"the-open-network",
    "SHIB": "shiba-inu", "SHIBUSDT":"shiba-inu",
    "LTC":  "litecoin",  "LTCUSDT": "litecoin",
    "BCH":  "bitcoin-cash","BCHUSDT":"bitcoin-cash",
    "UNI":  "uniswap",   "UNIUSDT": "uniswap",
    "ATOM": "cosmos",    "ATOMUSDT":"cosmos",
}


class CoinGeckoAdapter(BaseDataSource):
    name = "coingecko"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV, DataKind.REFDATA)
    rate_limit_rps = 0.5
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("COINGECKO_API_KEY", "")
        self.base_url = (config or {}).get("base_url", "https://api.coingecko.com/api/v3")
        if self.api_key:
            self.rate_limit_rps = 8.0
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["x-cg-pro-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=15, headers=headers,
            )
        return self._client

    @staticmethod
    def _to_id(symbol: str) -> str:
        return _ID_MAP.get(symbol.upper(), symbol.lower())

    async def quote(self, symbol: str, vs: str = "usd") -> dict[str, Any]:
        client = await self._client_()
        cg_id = self._to_id(symbol)
        r = await client.get("/simple/price", params={
            "ids": cg_id, "vs_currencies": vs,
            "include_24hr_change": "true", "include_24hr_vol": "true",
            "include_market_cap": "true",
        })
        r.raise_for_status()
        return (r.json() or {}).get(cg_id, {})

    async def ohlc(self, symbol: str, vs: str = "usd",
                   days: int = 30) -> pd.DataFrame:
        """OHLCV ticks. CoinGecko provides 4-hour candles for 30-90d range."""
        client = await self._client_()
        cg_id = self._to_id(symbol)
        r = await client.get(f"/coins/{cg_id}/ohlc",
                              params={"vs_currency": vs, "days": days})
        r.raise_for_status()
        rows = r.json() or []
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        return df.set_index("ts")

    async def market_chart(self, symbol: str, vs: str = "usd",
                            days: int | str = 30) -> pd.DataFrame:
        """Price + market_cap + total_volume time series (better resolution)."""
        client = await self._client_()
        cg_id = self._to_id(symbol)
        r = await client.get(f"/coins/{cg_id}/market_chart",
                              params={"vs_currency": vs, "days": days})
        r.raise_for_status()
        data = r.json() or {}
        prices = data.get("prices") or []
        caps = data.get("market_caps") or []
        vols = data.get("total_volumes") or []
        if not prices:
            return pd.DataFrame()
        df = pd.DataFrame({
            "ts": [pd.Timestamp(p[0], unit="ms") for p in prices],
            "price": [p[1] for p in prices],
            "market_cap": [c[1] if i < len(caps) else None for i, c in enumerate(caps)],
            "volume": [v[1] if i < len(vols) else None for i, v in enumerate(vols)],
        })
        return df.set_index("ts")

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("CoinGecko needs symbol")
        if request.kind == DataKind.QUOTE:
            data = await self.quote(sym)
            from src.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=data.get("usd"),
                volume_24h=data.get("usd_24h_vol"),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            return await self.ohlc(sym, days=int((request.extra or {}).get("days", 30)))
        if request.kind == DataKind.REFDATA:
            client = await self._client_()
            r = await client.get(f"/coins/{self._to_id(sym)}",
                                   params={"localization": "false", "tickers": "false",
                                           "community_data": "false", "developer_data": "false"})
            r.raise_for_status()
            return r.json()
        raise DataSourceError(f"unsupported kind {request.kind}")
