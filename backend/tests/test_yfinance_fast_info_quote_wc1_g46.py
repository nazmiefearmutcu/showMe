"""ASOF-4 (fallback path): the yfinance fast_info quote must not stamp fetch time.

fast_info carries no exchange timestamp, so a last price read from it must not
be presented as current with timestamp=utcnow(). No network: the chart client
and the yfinance ticker are in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from showme.engine.core.base_data_source import DataSourceError
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter


class _FailingClient:
    async def get(self, url: str, params: Any = None) -> Any:  # noqa: ARG002
        raise RuntimeError("chart endpoint unavailable")


class _Ticker:
    def __init__(self, fast_info: dict[str, Any]) -> None:
        self.fast_info = fast_info


def _adapter(fast_info: dict[str, Any]) -> YFinanceAdapter:
    adapter = YFinanceAdapter()
    adapter._chart_client = _FailingClient()  # type: ignore[assignment]
    adapter._ticker = lambda symbol: _Ticker(fast_info)  # type: ignore[assignment]
    return adapter


def _req() -> Any:
    # _fetch_quote reads only .instrument and .symbols.
    return SimpleNamespace(instrument=None, symbols=["AAPL"])


def test_fast_info_quote_without_exchange_time_is_refused_not_stamped() -> None:
    adapter = _adapter({"last_price": 282.62, "previous_close": 271.30})
    with pytest.raises(DataSourceError):
        asyncio.run(adapter._fetch_quote(_req()))


def test_fast_info_without_price_is_refused() -> None:
    adapter = _adapter({"previous_close": 271.30})
    with pytest.raises(DataSourceError):
        asyncio.run(adapter._fetch_quote(_req()))
