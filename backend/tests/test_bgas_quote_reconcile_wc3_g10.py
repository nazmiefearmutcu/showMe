"""WC3-G10 BGAS#1 / BGAS#2: the NG=F quote is reconciled with its daily bars.

BGAS#1: the chart meta ``previousClose`` can disagree with the daily bars the
same backend fetched. The change must come from the bars, with a warning.
BGAS#2: the quote is stamped with the exchange market time (not fetch time),
so a Sunday request for the Friday close shows the Friday date.

No network: the yfinance adapter is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import BGASFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _NGFake:
    """yfinance stand-in: a quote with a stale previousClose and two daily bars."""

    def __init__(self, *, prev: float, quote_time: datetime) -> None:
        self.prev = prev
        self.quote_time = quote_time

    async def fetch(self, request: Any) -> Any:
        if request.kind.name == "QUOTE":
            return SimpleNamespace(
                last=2.998,
                close_prev=self.prev,
                high_24h=3.05,
                low_24h=2.90,
                open_24h=2.95,
                volume_24h=1000.0,
                source="yfinance",
                timestamp=self.quote_time,
            )
        index = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame(
            {
                "open": [2.90, 2.95],
                "high": [2.97, 3.05],
                "low": [2.85, 2.90],
                "close": [2.947, 2.998],
                "volume": [100.0, 120.0],
            },
            index=index,
        )


_FRIDAY_MARKET_TIME = datetime(2026, 11, 6, 21, 59, 58, tzinfo=UTC)


def test_stale_previous_close_is_replaced_by_the_daily_bar_close() -> None:
    """Pre-fix: prev 3.533 (stale) gave change_pct -15.14 against bars that show +1.73."""
    fn = BGASFunction(deps=FunctionDeps(yfinance=_NGFake(prev=3.533, quote_time=_FRIDAY_MARKET_TIME)))
    result = _run(fn.execute(contract="NG=F"))
    assert result.data["status"] == "ok", result.data
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(2.947)
    assert row["change_pct"] == pytest.approx((2.998 / 2.947 - 1) * 100)
    assert any("previousClose" in w and "daily bar" in w for w in result.warnings), result.warnings


def test_agreeing_previous_close_is_kept_without_warning() -> None:
    fn = BGASFunction(deps=FunctionDeps(yfinance=_NGFake(prev=2.947, quote_time=_FRIDAY_MARKET_TIME)))
    result = _run(fn.execute(contract="NG=F"))
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(2.947)
    assert not any("daily bar" in w for w in result.warnings), result.warnings


def test_as_of_is_the_exchange_market_time_not_the_fetch_time() -> None:
    """Pre-fix risk: a Sunday request must not stamp today's date on Friday's close."""
    fn = BGASFunction(deps=FunctionDeps(yfinance=_NGFake(prev=2.947, quote_time=_FRIDAY_MARKET_TIME)))
    result = _run(fn.execute(contract="NG=F"))
    row = result.data["rows"][0]
    assert str(row["as_of"]).startswith("2026-11-06"), row["as_of"]
    assert result.data["as_of"] == row["as_of"]
