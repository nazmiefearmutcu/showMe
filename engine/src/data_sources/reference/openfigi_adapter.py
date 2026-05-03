"""OpenFIGI adapter — universal symbol → FIGI/exchange resolution.

Public API: https://www.openfigi.com/api
Anonymous: 25 req/min. With API key: 250 req/min.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest
from src.utils.throttle import throttle


class OpenFIGIAdapter(BaseDataSource):
    name = "openfigi"
    supported_kinds = (DataKind.REFDATA,)
    rate_limit_rps = 0.41
    requires_api_key = False
    api_key_env = "OPENFIGI_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.openfigi.com/v3"
        )
        self.api_key = os.environ.get(self.api_key_env)
        # Authenticated bumps the per-min budget to 250 → ~4 rps.
        if self.api_key:
            self.rate_limit_rps = 4.0
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-OPENFIGI-APIKEY"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers,
                timeout=self.timeout_seconds,
            )
        return self._client

    @throttle(rps=4.0)
    async def lookup_by(
        self, *, id_type: str, id_value: str,
        exch_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """Look up by any OpenFIGI idType (ID_ISIN / ID_CUSIP / ID_SEDOL / TICKER)."""
        client = await self._client_()
        body: list[dict[str, Any]] = [{"idType": id_type, "idValue": id_value}]
        if exch_code:
            body[0]["exchCode"] = exch_code
        try:
            r = await client.post("/mapping", json=body)
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._record_failure(exc)
                await asyncio.sleep(1)
                return []
            raise
        if not results:
            return []
        first = results[0].get("data") or []
        return first or []

    @throttle(rps=4.0)
    async def lookup(self, ticker: str, exch_code: str | None = None) -> dict[str, Any] | None:
        """Resolve a ticker to its OpenFIGI record. Returns first hit."""
        client = await self._client_()
        body = [{"idType": "TICKER", "idValue": ticker.upper()}]
        if exch_code:
            body[0]["exchCode"] = exch_code
        try:
            r = await client.post("/mapping", json=body)
            r.raise_for_status()
            results = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._record_failure(exc)
                await asyncio.sleep(1)
                return None
            raise
        if not results:
            return None
        first = results[0].get("data") or []
        return first[0] if first else None

    async def fetch(self, request: DataRequest) -> Any:
        if request.kind != DataKind.REFDATA:
            return None
        if not request.symbols and request.instrument:
            request.symbols = [request.instrument.symbol]
        out: list[dict[str, Any]] = []
        for sym in request.symbols:
            r = await self.lookup(sym)
            if r:
                out.append(r)
        return out
