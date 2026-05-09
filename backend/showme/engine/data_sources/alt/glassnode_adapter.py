"""Glassnode on-chain metrics adapter.

DATA PIPELINE:
    Source: https://api.glassnode.com/v1/metrics/...
    Free tier: limited metrics (e.g. addresses/active_count, market/price_usd_close).
    Paid tier T2/T3 unlocks the full ~3000+ metric catalogue.

Plan §5 alt-data tablosu: "Crypto on-chain — Glassnode T2".
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)


class GlassnodeAdapter(BaseDataSource):
    name = "glassnode"
    supported_kinds = (DataKind.ECON_SERIES, DataKind.OTHER)
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "GLASSNODE_API_KEY"

    # Free tier hot metrics (no auth required for some, sourced from docs)
    POPULAR = {
        "active_addresses": "addresses/active_count",
        "tx_count":         "transactions/count",
        "tx_volume_usd":    "transactions/transfers_volume_usd_total",
        "fees_usd":         "fees/volume_usd_sum",
        "supply":           "supply/current",
        "price":            "market/price_usd_close",
        "mvrv":             "market/mvrv",
        "nupl":             "indicators/net_unrealized_profit_loss",
        "sopr":             "indicators/sopr",
        "hash_rate":        "mining/hash_rate_mean",
        "miner_balance":    "addresses/miners_balance",
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://api.glassnode.com/v1/metrics")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def metric(self, asset: str, metric_path: str, *,
                     since: int | None = None, until: int | None = None,
                     resolution: str = "24h") -> pd.DataFrame:
        params: dict[str, Any] = {"a": asset.upper(), "i": resolution}
        if since: params["s"] = since
        if until: params["u"] = until
        if self.api_key:
            params["api_key"] = self.api_key
        client = await self._client_()
        try:
            r = await client.get(f"{self.base_url}/{metric_path}", params=params)
            if r.status_code == 401 or r.status_code == 403:
                raise DataSourceError("Glassnode auth required for this metric tier")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            raise DataSourceError(f"glassnode: {e}")
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "t" in df.columns:
            df["ts"] = pd.to_datetime(df["t"], unit="s")
            df = df.set_index("ts").drop(columns="t")
        if "v" in df.columns:
            df = df.rename(columns={"v": "value"})
        return df

    async def fetch(self, request: DataRequest) -> Any:
        asset = (request.instrument.metadata.get("base") if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        ) or "BTC"
        metric_key = (request.extra or {}).get("metric", "active_addresses")
        path = self.POPULAR.get(metric_key, metric_key)
        return await self.metric(asset, path, resolution=request.interval or "24h")
