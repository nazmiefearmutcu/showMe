"""FINRA OTC Transparency adapter (Dark Pool / ATS volumes).

DATA PIPELINE:
    Source: https://api.finra.org/data/group/otcMarket
    Free, T+1 reporting; ATS_W_AGG (weekly aggregate) and ATS_NMS files.
    Auth: optional OAuth client credentials via FINRA_API_KEY/SECRET.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from src.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class FINRAAdapter(BaseDataSource):
    name = "finra"
    supported_kinds = (DataKind.TRADES, DataKind.OTHER)
    rate_limit_rps = 1.0
    requires_api_key = False  # public dataset works without auth (rate-limited)

    BASE = "https://api.finra.org/data/group/otcMarket"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get("FINRA_API_KEY", "")
        self.api_secret = os.environ.get("FINRA_API_SECRET", "")
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20)
        return self._client

    async def _maybe_auth(self) -> None:
        if not self.api_key or not self.api_secret:
            return
        if self._token:
            return
        try:
            client = await self._client_()
            r = await client.post(
                "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self.api_key, self.api_secret),
            )
            if r.status_code == 200:
                self._token = (r.json() or {}).get("access_token")
        except Exception:
            self._token = None

    async def ats_weekly(self, symbol: str | None = None,
                         limit: int = 200) -> pd.DataFrame:
        """Last weeks of FINRA ATS (Alternative Trading System) volume.

        Anonymous endpoint returns JSON with columns: weekStartDate, ATSCode,
        issueSymbolIdentifier, totalWeeklyShareQuantity, totalWeeklyTradeCount, ...
        """
        await self._maybe_auth()
        client = await self._client_()
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["compareFilters"] = f'[{{"fieldName":"issueSymbolIdentifier","fieldValue":"{symbol.upper()}","compareType":"EQUAL"}}]'
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            r = await client.get(f"{self.BASE}/name/weeklySummary", params=params,
                                  headers=headers)
            if r.status_code == 401:
                raise DataSourceError("FINRA auth required for this dataset")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            raise DataSourceError(f"finra: {e}")
        if not isinstance(data, list):
            return pd.DataFrame()
        return pd.DataFrame(data)

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        return await self.ats_weekly(sym, limit=request.limit or 100)
