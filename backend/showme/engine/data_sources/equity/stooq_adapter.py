"""Stooq adapter — global EOD CSV, anahtarsız.

DATA PIPELINE:
    Source: https://stooq.com/q/d/l/?s={sym}&i=d
    Latency: <1.5s (CSV download)
    Caveat: HTML scraping; cache aggressively (1h+).
"""

from __future__ import annotations

import re
from io import StringIO
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest, DataSourceError


class StooqAdapter(BaseDataSource):
    name = "stooq"
    supported_kinds = (DataKind.OHLCV,)
    rate_limit_rps = 0.5
    requires_api_key = False  # keyless CSV service

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get("base_url", "https://stooq.com/q/d/l")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True)
        return self._client

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        """Map a raw ticker to Stooq's form: US equities need a ``.us``
        suffix and class shares use a dash (``BRK.B`` → ``brk-b.us``).
        A 2+ letter trailing dot-suffix is an exchange code and stays."""
        clean = str(symbol or "").strip().lower()
        if not clean:
            return ""
        clean = re.sub(r"[.\-]([a-z])$", r"-\1", clean)
        if "." not in clean:
            return f"{clean}.us"
        return clean

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("Stooq needs symbol")
        client = await self._client_()
        r = await client.get(self.base_url, params={"s": self._stooq_symbol(sym), "i": "d"})
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
        df.columns = [c.lower() for c in df.columns]
        return df
