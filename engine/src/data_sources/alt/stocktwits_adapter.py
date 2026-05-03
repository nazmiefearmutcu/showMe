"""StockTwits adapter — public stream JSON (200/hour anonymous)."""

from __future__ import annotations

from typing import Any

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class StockTwitsAdapter(BaseDataSource):
    name = "stocktwits"
    supported_kinds = (DataKind.SOCIAL,)
    rate_limit_rps = 0.055
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://api.stocktwits.com/api/2")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def stream(self, symbol: str) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get(f"{self.base_url}/streams/symbol/{symbol}.json")
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("StockTwits needs symbol")
        data = await self.stream(sym)
        msgs = data.get("messages", []) or []
        bullish = sum(1 for m in msgs if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish")
        bearish = sum(1 for m in msgs if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish")
        return {
            "symbol": sym,
            "messages": msgs[: request.limit or 30],
            "bullish_count": bullish,
            "bearish_count": bearish,
            "total": len(msgs),
        }
