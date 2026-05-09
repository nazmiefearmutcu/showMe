"""EIA (US Energy Information Administration) — petrol, gaz, elektrik.

DATA PIPELINE:
    Source: https://api.eia.gov/v2 (free api key, instant signup)
    Latency: <800ms
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class EIAAdapter(BaseDataSource):
    name = "eia"
    supported_kinds = (DataKind.ECON_SERIES, DataKind.QUOTE)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "EIA_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://api.eia.gov/v2")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
            )
        return self._client

    async def series_data(self, route: str, frequency: str = "daily",
                          data_field: str = "value", facets: dict | None = None,
                          limit: int = 5000) -> pd.DataFrame:
        if not self.api_key:
            raise DataSourceError("EIA_API_KEY not set")
        client = await self._client_()
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "frequency": frequency,
            "data[0]": data_field,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": limit,
        }
        if facets:
            for k, v in facets.items():
                params[f"facets[{k}][]"] = v
        r = await client.get(f"/{route.strip('/')}/data/", params=params)
        r.raise_for_status()
        rows = ((r.json() or {}).get("response", {}) or {}).get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "period" in df.columns:
            df["period"] = pd.to_datetime(df["period"])
            df = df.set_index("period").sort_index()
        return df

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        ) or "WTI"
        # Hot route presets
        presets = {
            "WTI":   ("petroleum/pri/spt", {"series": ["RWTC"]}),
            "BRENT": ("petroleum/pri/spt", {"series": ["RBRTE"]}),
            "HENRYHUB": ("natural-gas/pri/sum", {"series": ["RNGWHHD"]}),
            "GASOLINE": ("petroleum/pri/gnd", {"series": ["EMM_EPMR_PTE_NUS_DPG"]}),
        }
        route, facets = presets.get(sym.upper(), ("petroleum/pri/spt", {"series": ["RWTC"]}))
        df = await self.series_data(route, facets=facets, limit=request.limit or 1000)
        if request.kind == DataKind.QUOTE:
            from showme.engine.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=float(df["value"].iloc[0]) if not df.empty and "value" in df else None,
                source=self.name,
            )
        return df
