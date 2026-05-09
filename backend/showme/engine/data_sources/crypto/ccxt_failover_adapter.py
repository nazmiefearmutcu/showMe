"""CCXT failover adapter.

Plan §EK D: data router fallback. Binance kapanırsa Bybit/OKX/Coinbase'e
geç. CCXT kütüphanesi varsa ondan yararlan, yoksa per-exchange REST'e
düş.

DATA PIPELINE:
    Source: ccxt (lazy) → /fapi/v1/ticker (Binance) → /v5/market/tickers (Bybit) → ...
    Latency budget: <300 ms warm.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError,
)
from showme.engine.core.quote import Quote, utcnow


_FALLBACK_CHAIN = ["binance", "bybit", "okx", "coinbase", "kraken"]


class CCXTFailoverAdapter(BaseDataSource):
    name = "ccxt_failover"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV)
    rate_limit_rps = 6.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.chain: list[str] = (config or {}).get("chain", _FALLBACK_CHAIN)
        self._client: httpx.AsyncClient | None = None
        self._ccxt: Any = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def _try_ccxt(self, exchange: str, symbol: str) -> dict[str, Any] | None:
        try:
            if self._ccxt is None:
                import ccxt  # type: ignore
                self._ccxt = ccxt
            ex_cls = getattr(self._ccxt, exchange, None)
            if ex_cls is None:
                return None
            ex = ex_cls({"enableRateLimit": True})
            sym_normalized = self._normalize_symbol(exchange, symbol)
            t = await asyncio.to_thread(ex.fetch_ticker, sym_normalized)
            return t
        except Exception:
            return None

    @staticmethod
    def _normalize_symbol(exchange: str, sym: str) -> str:
        s = sym.upper()
        if "/" in s:
            return s
        # Convert "BTCUSDT" → "BTC/USDT" for CCXT.
        for q in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR"):
            if s.endswith(q) and len(s) > len(q):
                return f"{s[:-len(q)]}/{q}"
        return s

    async def _try_rest(self, exchange: str, symbol: str) -> Quote | None:
        client = await self._client_()
        s = symbol.upper()
        try:
            if exchange == "binance":
                r = await client.get(
                    "https://fapi.binance.com/fapi/v1/ticker/24hr",
                    params={"symbol": s},
                )
                if r.status_code == 200:
                    j = r.json()
                    return Quote(
                        symbol=s, timestamp=utcnow(),
                        last=float(j.get("lastPrice", 0) or 0),
                        bid=float(j.get("bidPrice", 0) or 0) or None,
                        ask=float(j.get("askPrice", 0) or 0) or None,
                        volume_24h=float(j.get("volume", 0) or 0),
                        high_24h=float(j.get("highPrice", 0) or 0),
                        low_24h=float(j.get("lowPrice", 0) or 0),
                        close_prev=float(j.get("openPrice", 0) or 0),
                        source="binance",
                    )
            if exchange == "bybit":
                r = await client.get(
                    "https://api.bybit.com/v5/market/tickers",
                    params={"category": "linear", "symbol": s},
                )
                if r.status_code == 200:
                    items = (r.json().get("result") or {}).get("list") or []
                    if items:
                        j = items[0]
                        return Quote(
                            symbol=s, timestamp=utcnow(),
                            last=float(j.get("lastPrice", 0) or 0),
                            volume_24h=float(j.get("volume24h", 0) or 0),
                            high_24h=float(j.get("highPrice24h", 0) or 0),
                            low_24h=float(j.get("lowPrice24h", 0) or 0),
                            close_prev=float(j.get("prevPrice24h", 0) or 0),
                            source="bybit",
                        )
            if exchange == "okx":
                pair = self._normalize_symbol("okx", s).replace("/", "-") + "-SWAP"
                r = await client.get(
                    "https://www.okx.com/api/v5/market/ticker",
                    params={"instId": pair},
                )
                if r.status_code == 200:
                    items = (r.json() or {}).get("data") or []
                    if items:
                        j = items[0]
                        return Quote(
                            symbol=s, timestamp=utcnow(),
                            last=float(j.get("last", 0) or 0),
                            volume_24h=float(j.get("vol24h", 0) or 0),
                            high_24h=float(j.get("high24h", 0) or 0),
                            low_24h=float(j.get("low24h", 0) or 0),
                            close_prev=float(j.get("open24h", 0) or 0),
                            source="okx",
                        )
            if exchange == "coinbase":
                pair = self._normalize_symbol("coinbase", s).replace("USDT", "USD")
                r = await client.get(
                    f"https://api.coinbase.com/v2/prices/{pair.replace('/', '-')}/spot",
                )
                if r.status_code == 200:
                    j = (r.json() or {}).get("data") or {}
                    return Quote(
                        symbol=s, timestamp=utcnow(),
                        last=float(j.get("amount", 0) or 0),
                        source="coinbase",
                    )
            if exchange == "kraken":
                pair = self._normalize_symbol("kraken", s).replace("/", "")
                r = await client.get(
                    "https://api.kraken.com/0/public/Ticker", params={"pair": pair},
                )
                if r.status_code == 200:
                    j = (r.json() or {}).get("result") or {}
                    if j:
                        v = next(iter(j.values()))
                        return Quote(
                            symbol=s, timestamp=utcnow(),
                            last=float(v.get("c", [0])[0] or 0),
                            volume_24h=float(v.get("v", [0, 0])[1] or 0),
                            high_24h=float(v.get("h", [0, 0])[1] or 0),
                            low_24h=float(v.get("l", [0, 0])[1] or 0),
                            source="kraken",
                        )
        except Exception:
            return None
        return None

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("ccxt_failover needs symbol")
        if request.kind == DataKind.QUOTE:
            for ex in self.chain:
                q = await self._try_rest(ex, sym)
                if q is not None:
                    return q
            for ex in self.chain:
                # CCXT is a deeper fallback for quote; REST is much faster cold.
                t = await self._try_ccxt(ex, sym)
                if t is not None:
                    return Quote(
                        symbol=sym, timestamp=utcnow(),
                        last=t.get("last"), bid=t.get("bid"), ask=t.get("ask"),
                        volume_24h=t.get("baseVolume"),
                        high_24h=t.get("high"), low_24h=t.get("low"),
                        close_prev=t.get("previousClose"),
                        source=f"ccxt:{ex}",
                    )
            raise DataSourceError(f"all crypto exchanges failed for {sym}")
        if request.kind == DataKind.OHLCV:
            # CCXT-backed only
            try:
                if self._ccxt is None:
                    import ccxt  # type: ignore
                    self._ccxt = ccxt
            except Exception:
                raise DataSourceError("ccxt not installed (pip install ccxt)")
            for ex in self.chain:
                try:
                    cls = getattr(self._ccxt, ex)
                    ohlc = await asyncio.to_thread(
                        cls({"enableRateLimit": True}).fetch_ohlcv,
                        self._normalize_symbol(ex, sym),
                        request.interval or "1h",
                        None, request.limit or 200,
                    )
                    if not ohlc:
                        continue
                    df = pd.DataFrame(ohlc, columns=["t", "open", "high", "low", "close", "volume"])
                    df["ts"] = pd.to_datetime(df["t"], unit="ms")
                    return df.set_index("ts").drop(columns="t")
                except Exception:
                    continue
            raise DataSourceError(f"OHLCV failed across all exchanges for {sym}")
        raise DataSourceError(f"unsupported kind {request.kind}")
