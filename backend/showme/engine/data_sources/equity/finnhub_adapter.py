"""Finnhub adapter — quote, profile, fundamentals, estimates, recommendations, news.

DATA PIPELINE:
    Source: https://finnhub.io/api/v1
    Plan: 60 calls/min ücretsiz
    Latency: <500ms warm
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]

import httpx
import pandas as pd

from showme.engine.core.base_data_source import (
    BaseDataSource, DataKind, DataRequest, DataSourceError
)
from showme.engine.utils.throttle import throttle

# B5: Finnhub's date filters (/company-news) and intraday candle ranges are
# anchored to America/New_York exchange time. Internal datetimes always live
# in UTC; convert at the boundary so naive timestamps don't silently leak the
# wrong epoch to the wire.
_NY_TZ = ZoneInfo("America/New_York") if ZoneInfo is not None else timezone.utc


def _ensure_utc(dt: datetime) -> datetime:
    """Treat a naive datetime as ET (Finnhub convention), else preserve tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_NY_TZ).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_ny_date_str(dt: datetime) -> str:
    """Render a date for Finnhub's ``from``/``to`` filters (NY-local YYYY-MM-DD)."""
    return _ensure_utc(dt).astimezone(_NY_TZ).strftime("%Y-%m-%d")


def _epoch_seconds(dt: datetime) -> int:
    """Return the UTC epoch seconds for a (possibly naive) datetime."""
    return int(_ensure_utc(dt).timestamp())


class FinnhubAdapter(BaseDataSource):
    name = "finnhub"
    supported_kinds = (
        DataKind.QUOTE, DataKind.OHLCV, DataKind.REFDATA,
        DataKind.FUNDAMENTALS, DataKind.EVENTS, DataKind.NEWS,
    )
    rate_limit_rps = 1.0
    requires_api_key = True
    api_key_env = "FINNHUB_API_KEY"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_key = os.environ.get(self.api_key_env, "")
        self.base_url = (config or {}).get("base_url", "https://finnhub.io/api/v1")
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds,
                params={"token": self.api_key} if self.api_key else None,
            )
        return self._client

    @throttle(rps=1.0)
    async def _get(self, endpoint: str, **params: Any) -> Any:
        if not self.api_key:
            raise DataSourceError("FINNHUB_API_KEY not set")
        client = await self._client_()
        r = await client.get(endpoint, params={**params, "token": self.api_key})
        r.raise_for_status()
        return r.json()

    async def fetch(self, request: DataRequest) -> Any:
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            raise DataSourceError("Finnhub needs symbol")
        if request.kind == DataKind.QUOTE:
            data = await self._get("/quote", symbol=sym)
            from showme.engine.core.quote import Quote, utcnow
            return Quote(
                symbol=sym, timestamp=utcnow(),
                last=data.get("c"), close_prev=data.get("pc"),
                open_24h=data.get("o"), high_24h=data.get("h"), low_24h=data.get("l"),
                source=self.name,
            )
        if request.kind == DataKind.OHLCV:
            res = (request.interval or "D").upper()
            # B5: ensure both bounds are tz-aware UTC epochs. Default ``end``
            # was using ``datetime.now()`` (naive) which would silently shift
            # by the host machine's offset.
            start_dt = request.start or datetime(2020, 1, 1, tzinfo=_NY_TZ)
            end_dt = request.end or datetime.now(tz=timezone.utc)
            r = await self._get(
                "/stock/candle",
                symbol=sym, resolution=res,
                **{
                    "from": _epoch_seconds(start_dt),
                    "to": _epoch_seconds(end_dt),
                },
            )
            if r.get("s") != "ok":
                return pd.DataFrame()
            df = pd.DataFrame({
                "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
                "close": r.get("c"), "volume": r.get("v"),
                "ts": pd.to_datetime(r.get("t"), unit="s"),
            }).set_index("ts")
            return df
        if request.kind == DataKind.REFDATA:
            data = await self._get("/stock/profile2", symbol=sym)
            from showme.engine.core.refdata import ReferenceData
            from showme.engine.core.quote import utcnow
            return ReferenceData(
                symbol=sym, name=data.get("name"), exchange=data.get("exchange"),
                country=data.get("country"), currency=data.get("currency"),
                industry=data.get("finnhubIndustry"),
                market_cap=(data.get("marketCapitalization") or 0) * 1_000_000,
                shares_outstanding=(data.get("shareOutstanding") or 0) * 1_000_000,
                website=data.get("weburl"),
                ipo_date=pd.to_datetime(data.get("ipo")) if data.get("ipo") else None,
                source=self.name, fetched_at=utcnow(),
            )
        if request.kind == DataKind.FUNDAMENTALS:
            return await self._get("/stock/financials-reported", symbol=sym, freq=request.extra.get("freq", "annual"))
        if request.kind == DataKind.EVENTS:
            return {
                "earnings": await self._get("/stock/earnings", symbol=sym),
                "calendar": await self._get("/calendar/earnings", symbol=sym),
                "splits": await self._get("/stock/split", symbol=sym),
                "dividends": await self._get("/stock/dividend2", symbol=sym),
            }
        if request.kind == DataKind.NEWS:
            # B5: Finnhub expects NY-local YYYY-MM-DD. Naive datetimes get
            # localized to ET (the API's native zone) before formatting so
            # ``datetime.now()`` on a London laptop doesn't bleed into the
            # query window.
            start_dt = request.start or datetime(2024, 1, 1, tzinfo=_NY_TZ)
            end_dt = request.end or datetime.now(tz=timezone.utc)
            return await self._get("/company-news", symbol=sym,
                                    **{"from": _to_ny_date_str(start_dt),
                                       "to": _to_ny_date_str(end_dt)})
        raise DataSourceError(f"unsupported kind {request.kind}")

    # ── Hot helpers used by EE/ANR functions ──
    async def recommendations(self, symbol: str) -> list[dict[str, Any]]:
        return await self._get("/stock/recommendation", symbol=symbol)

    async def price_target(self, symbol: str) -> dict[str, Any]:
        return await self._get("/stock/price-target", symbol=symbol)

    async def peers(self, symbol: str) -> list[str]:
        return await self._get("/stock/peers", symbol=symbol)

    async def metrics(self, symbol: str, metric: str = "all") -> dict[str, Any]:
        return await self._get("/stock/metric", symbol=symbol, metric=metric)
