"""FRED (Federal Reserve Economic Data) adapter.

DATA PIPELINE:
    Source: https://api.stlouisfed.org/fred (free API key)
    Cache:  in-memory (1h TTL) + DuckDB ``econ_series`` table (Faz 1 sonu)
    Latency: <800ms warm

FRED has 1M+ time series. We expose ``series(id, start, end)`` and
``observation()`` helpers so functions like ECST/CRVF/COUN can grab
data with a single call.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from showme.engine.utils.throttle import throttle

LOG = logging.getLogger("showme.engine.data_sources.fred")


class FREDAdapter(BaseDataSource):
    name = "fred"
    supported_kinds = (DataKind.ECON_SERIES, DataKind.REFDATA)
    rate_limit_rps = 5.0
    requires_api_key = True
    api_key_env = "FRED_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get(
            "base_url", "https://api.stlouisfed.org/fred"
        )
        self._client: httpx.AsyncClient | None = None
        self._series_cache: dict[str, tuple[datetime, pd.DataFrame]] = {}

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
            )
        return self._client

    @throttle(rps=5.0)
    async def series(
        self, series_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        frequency: str | None = None,
        vintage: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame indexed by date with column 'value'."""
        if not self.api_key:
            # QA-fix: log so the missing-key reason is visible in the
            # rotating sidecar log instead of only the raised exception.
            LOG.warning(
                "FRED_API_KEY missing; series %r unavailable (set the env "
                "var to enable macro/bond functions like CRVF/ECST)",
                series_id,
            )
            raise DataSourceError("FRED_API_KEY not set")
        client = await self._client_()
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if start:
            params["observation_start"] = (
                start.strftime("%Y-%m-%d") if isinstance(start, datetime) else start
            )
        if end:
            params["observation_end"] = (
                end.strftime("%Y-%m-%d") if isinstance(end, datetime) else end
            )
        if frequency:
            params["frequency"] = frequency
        if vintage and vintage != "latest":
            params["vintage_dates"] = vintage
        r = await client.get("/series/observations", params=params)
        r.raise_for_status()
        data = r.json().get("observations") or []
        if not data:
            return pd.DataFrame(columns=["value"])
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.set_index("date")[["value"]].dropna()
        return df

    @throttle(rps=5.0)
    async def info(self, series_id: str) -> dict[str, Any]:
        client = await self._client_()
        r = await client.get(
            "/series",
            params={"series_id": series_id, "api_key": self.api_key, "file_type": "json"},
        )
        r.raise_for_status()
        s = r.json().get("seriess") or []
        return s[0] if s else {}

    async def fetch(self, request: DataRequest) -> Any:
        if request.kind == DataKind.ECON_SERIES:
            sid = (request.instrument.symbol if request.instrument else None) or (
                request.symbols[0] if request.symbols else None
            )
            if not sid:
                raise DataSourceError("FRED requires a series_id")
            return await self.series(sid, start=request.start, end=request.end,
                                     frequency=request.extra.get("frequency"))
        if request.kind == DataKind.REFDATA:
            sid = (request.instrument.symbol if request.instrument else None) or (
                request.symbols[0] if request.symbols else None
            )
            return await self.info(sid) if sid else {}
        raise DataSourceError(f"unsupported kind {request.kind}")

    # Convenience presets for hot series ↓
    async def yield_curve(self) -> dict[str, float]:
        ids = ["DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7",
               "DGS10", "DGS20", "DGS30"]
        out: dict[str, float] = {}
        for sid in ids:
            try:
                df = await self.series(sid, frequency="d")
                out[sid] = float(df["value"].iloc[-1]) if not df.empty else float("nan")
            except Exception:
                out[sid] = float("nan")
        return out
