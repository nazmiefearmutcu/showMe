"""NGAS#2 — NGAS must not stamp a fetch time as the quote's as_of.

NGAS inherits the BGAS quote path. The quote's as_of must be the exchange's
own market time (or the last history bar's date), never the wall-clock time at
which the function ran. Network is never used: the yfinance transport is
replaced by in-memory fakes; the chart client is a fake that records no calls.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataSourceError
from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.commodity._funcs import NGASFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _Yahoo:
    """Quote stand-in that stamps a fixed exchange market time."""

    def __init__(self, timestamp: datetime) -> None:
        self.timestamp = timestamp

    async def fetch(self, request: Any) -> Any:
        if request.kind.name == "QUOTE":
            return SimpleNamespace(
                last=3.10,
                close_prev=3.00,
                high_24h=3.20,
                low_24h=2.95,
                open_24h=3.01,
                volume_24h=1000.0,
                source="yfinance",
                timestamp=self.timestamp,
            )
        return pd.DataFrame()  # no history bars


def test_ngas_as_of_is_the_quote_market_time_not_the_render_time() -> None:
    market_time = datetime(2024, 6, 3, 19, 59, 30, tzinfo=UTC)
    result = _run(NGASFunction(deps=FunctionDeps(yfinance=_Yahoo(market_time))).execute(contract="NG=F"))
    assert result.data["status"] == "ok"
    row = result.data["rows"][0]
    assert row["as_of"] == market_time.isoformat()
    assert result.data["as_of"] == market_time.isoformat()
    assert not str(row["as_of"]).startswith(datetime.now(UTC).date().isoformat())


class _ChartNoMarketTime:
    """Chart client whose meta carries a price but no regularMarketTime."""

    async def get(self, url: str, params: Any = None) -> Any:  # noqa: ARG002
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 3.10}}]}}

        return _Resp()


class _RealChartQuoteOnly:
    """Routes QUOTE to the real adapter's chart path (fake HTTP), OHLCV to nothing."""

    def __init__(self) -> None:
        self.adapter = YFinanceAdapter()
        self.adapter._chart_client = _ChartNoMarketTime()  # type: ignore[assignment]

    async def fetch(self, request: Any) -> Any:
        if request.kind.name == "QUOTE":
            return await self.adapter._fetch_chart_quote("NG=F")
        return pd.DataFrame()


def test_ngas_without_quote_market_time_serves_no_row_with_a_fetch_time() -> None:
    # The adapter refuses a price with no exchange time, so NGAS has no row to
    # stamp. It must report the outage, never an as_of taken from the clock.
    result = _run(NGASFunction(deps=FunctionDeps(yfinance=_RealChartQuoteOnly())).execute(contract="NG=F"))
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.data.get("as_of") is None


def test_adapter_refuses_chart_quote_without_market_time() -> None:
    adapter = YFinanceAdapter()
    adapter._chart_client = _ChartNoMarketTime()  # type: ignore[assignment]
    try:
        _run(adapter._fetch_chart_quote("NG=F"))
    except DataSourceError:
        return
    raise AssertionError("chart quote without regularMarketTime must not be served")
