"""ASOF-4: the yfinance chart quote must not present a stale price as current.

No network: the chart client is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from showme.engine.core.base_data_source import DataSourceError
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter


class _Resp:
    status_code = 200

    def __init__(self, meta: dict[str, Any]) -> None:
        self._meta = meta

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"chart": {"result": [{"meta": self._meta}]}}


class _Client:
    def __init__(self, meta: dict[str, Any]) -> None:
        self._meta = meta

    async def get(self, url: str, params: Any = None) -> _Resp:  # noqa: ARG002
        return _Resp(self._meta)


def _adapter_with_meta(meta: dict[str, Any]) -> YFinanceAdapter:
    adapter = YFinanceAdapter()
    adapter._chart_client = _Client(meta)  # type: ignore[assignment]
    return adapter


def _quote(meta: dict[str, Any]) -> Any:
    return asyncio.run(_adapter_with_meta(meta)._fetch_chart_quote("AAPL"))


def test_chart_quote_without_regular_price_is_not_presented_as_last() -> None:
    # previousClose is the prior session's close. It must not become `last`.
    meta = {"previousClose": 271.30, "regularMarketTime": 1731000000}
    with pytest.raises(DataSourceError):
        _quote(meta)


def test_chart_quote_is_stamped_with_exchange_market_time_not_fetch_time() -> None:
    meta = {"regularMarketPrice": 282.62, "regularMarketTime": 1731000000}
    quote = _quote(meta)
    assert quote.last == 282.62
    assert quote.timestamp == datetime.fromtimestamp(1731000000, tz=timezone.utc)


def test_chart_quote_without_market_time_cannot_be_stamped_honestly() -> None:
    meta = {"regularMarketPrice": 282.62}
    with pytest.raises(DataSourceError):
        _quote(meta)
