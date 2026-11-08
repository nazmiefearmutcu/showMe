"""US Treasury daily yield curve adapter — anahtarsız."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest


def _year_scoped_csv_url(base: str, year: int) -> str:
    """Return the Treasury CSV endpoint for one calendar year.

    The upstream serves the daily par-yield curve per year
    (``.../daily-treasury-rates.csv/2026/all``); the bare ``.../csv/all``
    form returns HTTP 404. A configured base in either form (with or
    without a trailing ``/all`` or year segment) is normalised here.
    """
    root = str(base).rstrip("/")
    if root.endswith("/all"):
        root = root[: -len("/all")]
    if re.search(r"/\d{4}$", root):
        root = root[: root.rfind("/")]
    return f"{root}/{year}/all"


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

    async def _fetch_year(self, client: Any, year: int) -> pd.DataFrame:
        r = await client.get(
            _year_scoped_csv_url(self.url, year),
            params={"type": "daily_treasury_yield_curve", "field_tdr_date_value": "all"},
        )
        r.raise_for_status()
        return pd.read_csv(StringIO(r.text))

    async def yield_curve(self) -> pd.DataFrame:
        client = await self._client_()
        year = datetime.now(timezone.utc).year
        df = await self._fetch_year(client, year)
        if df.empty:
            # Early January: the new year's file may not have a row yet.
            df = await self._fetch_year(client, year - 1)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
        return df

    async def fetch(self, request: DataRequest) -> Any:
        return await self.yield_curve()
