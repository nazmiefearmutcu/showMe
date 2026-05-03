"""US Treasury daily yield curve adapter — anahtarsız."""

from __future__ import annotations

from io import StringIO
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import BaseDataSource, DataKind, DataRequest


class USTreasuryAdapter(BaseDataSource):
    name = "ustreasury"
    supported_kinds = (DataKind.ECON_SERIES,)
    rate_limit_rps = 0.5

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.url = (config or {}).get(
            "base_url",
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all",
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def yield_curve(self) -> pd.DataFrame:
        client = await self._client_()
        r = await client.get(self.url, params={"type": "daily_treasury_yield_curve",
                                                "field_tdr_date_value": "all"})
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
        return df

    async def fetch(self, request: DataRequest) -> Any:
        return await self.yield_curve()
