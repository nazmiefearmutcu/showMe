"""BOIL#2 (wc3-g05): BOIL as_of is the exchange quote time, never the fetch time.

The reviewer saw CL=F/BZ=F rows stamped with the fetch time (a Sunday) while
the price was the Friday exchange close. This drives BOIL through the real
YFinanceAdapter chart-quote path with an in-memory chart client (no network).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter
from showme.engine.functions.commodity._funcs import BOILFunction

EXCHANGE_TIME = datetime(2026, 11, 6, 21, 59, 58, tzinfo=UTC)


class _Resp:
    status_code = 200

    def __init__(self, meta: dict[str, Any]) -> None:
        self._meta = meta

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"chart": {"result": [{"meta": self._meta}]}}


class _ChartClient:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    async def get(self, url: str, params: Any = None) -> _Resp:  # noqa: ARG002
        symbol = url.rsplit("/", 1)[-1]
        return _Resp({
            "regularMarketPrice": self._prices[symbol],
            "previousClose": self._prices[symbol] - 0.5,
            "regularMarketTime": int(EXCHANGE_TIME.timestamp()),
        })


class _ChainedYfinance:
    """Quote legs go through the real adapter; history is empty (no network)."""

    def __init__(self) -> None:
        self.adapter = YFinanceAdapter()
        self.adapter._chart_client = _ChartClient({"CL=F": 80.0, "BZ=F": 84.0})  # type: ignore[assignment]

    async def fetch(self, request: Any) -> Any:
        if request.kind == DataKind.QUOTE:
            return await self.adapter._fetch_chart_quote(request.instrument.symbol)
        if request.kind == DataKind.OHLCV:
            return pd.DataFrame()
        raise AssertionError(f"unexpected kind {request.kind}")


def _boil_rows() -> dict[str, dict[str, Any]]:
    fn = BOILFunction(deps=FunctionDeps(yfinance=_ChainedYfinance()))
    res = asyncio.run(fn.execute(instrument=None))
    assert res.data["status"] == "ok", res.data
    return {row["symbol"]: row for row in res.data["rows"]}


def test_boil_rows_are_stamped_with_exchange_quote_time_not_fetch_time() -> None:
    rows = _boil_rows()
    assert set(rows) == {"CL=F", "BZ=F"}
    for symbol, row in rows.items():
        assert row["as_of"] == EXCHANGE_TIME.isoformat(), (symbol, row["as_of"])
        assert not str(row["as_of"]).startswith(datetime.now(UTC).date().isoformat()), symbol


def test_boil_last_and_as_of_come_from_the_same_exchange_quote() -> None:
    rows = _boil_rows()
    assert rows["CL=F"]["last"] == 80.0
    assert rows["BZ=F"]["last"] == 84.0
    assert rows["CL=F"]["source_mode"] == "live_yfinance"
