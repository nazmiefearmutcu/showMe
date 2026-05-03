"""exchangerate.host — ücretsiz FX rates, anahtarsız.

DATA PIPELINE:
    Source: https://api.exchangerate.host
    Latency: ~300ms
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from src.core.quote import Quote, utcnow


class ExchangerateHostAdapter(BaseDataSource):
    name = "exchangerate_host"
    supported_kinds = (DataKind.QUOTE, DataKind.OHLCV)
    rate_limit_rps = 5.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url", "https://api.exchangerate.host"
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
            )
        return self._client

    async def latest(self, base: str, quotes: list[str] | None = None) -> dict[str, float]:
        client = await self._client_()
        params = {"base": base.upper()}
        if quotes:
            params["symbols"] = ",".join(q.upper() for q in quotes)
        r = await client.get("/latest", params=params)
        r.raise_for_status()
        return r.json().get("rates", {})

    async def timeseries(
        self, base: str, quote: str, start: str, end: str
    ) -> pd.DataFrame:
        client = await self._client_()
        r = await client.get("/timeseries", params={
            "base": base.upper(), "symbols": quote.upper(),
            "start_date": start, "end_date": end,
        })
        r.raise_for_status()
        rates = r.json().get("rates", {})
        rows = [{"date": d, "value": v.get(quote.upper())} for d, v in rates.items()]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym or len(sym) < 6:
            raise DataSourceError("exchangerate.host needs a 6-char FX pair")
        base, quote = sym[:3].upper(), sym[3:6].upper()
        if request.kind == DataKind.QUOTE:
            rates = await self.latest(base, [quote])
            return Quote(
                symbol=sym, timestamp=utcnow(), last=rates.get(quote),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            start = request.start.strftime("%Y-%m-%d") if request.start else "2024-01-01"
            end = request.end.strftime("%Y-%m-%d") if request.end else None
            from datetime import date
            end = end or date.today().strftime("%Y-%m-%d")
            df = await self.timeseries(base, quote, start, end)
            df["close"] = df["value"]
            df["open"] = df["value"]
            df["high"] = df["value"]
            df["low"] = df["value"]
            df["volume"] = 0
            return df.drop(columns="value")
        raise DataSourceError(f"unsupported kind {request.kind}")
