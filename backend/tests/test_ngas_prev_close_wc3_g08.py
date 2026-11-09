"""NGAS#2 — the previous close behind NGAS change and change % must be checked.

The quote's ``previousClose`` is taken as-is by the shared quote path, so a
stale value (BGAS#1: prev 3.533 for NG=F, change -15.14%) flowed straight into
NGAS change and change_pct. NGAS must verify the previous close against the
daily bars it serves: the prior session's close is the last bar dated before
the quote's market day. Disagreement is replaced by the daily-bar value and
labelled; a previous close that cannot be checked is labelled unverified.

Network is never used: the yfinance transport is an in-memory fake.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
import sys
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.commodity._funcs import NGASFunction


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


MARKET_TIME = datetime(2024, 6, 3, 19, 59, 30, tzinfo=UTC)


class _Yahoo:
    """Quote with a given previousClose, plus daily bars (or none)."""

    def __init__(self, close_prev: float | None, bars: pd.DataFrame | None) -> None:
        self.close_prev = close_prev
        self.bars = bars

    async def fetch(self, request: Any) -> Any:
        if request.kind.name == "QUOTE":
            return SimpleNamespace(
                last=3.10,
                close_prev=self.close_prev,
                high_24h=3.20,
                low_24h=2.95,
                open_24h=3.01,
                volume_24h=1000.0,
                source="yfinance",
                timestamp=MARKET_TIME,
            )
        if self.bars is None:
            return pd.DataFrame()
        return self.bars


def _daily_bars() -> pd.DataFrame:
    # Prior session 2024-05-31 closed 3.00; the market day 2024-06-03 is the last bar.
    index = pd.DatetimeIndex(["2024-05-30", "2024-05-31", "2024-06-03"])
    return pd.DataFrame(
        {
            "open": [2.90, 2.95, 3.05],
            "high": [3.00, 3.02, 3.20],
            "low": [2.85, 2.90, 3.00],
            "close": [2.98, 3.00, 3.10],
            "volume": [100.0, 110.0, 120.0],
        },
        index=index,
    )


def _ngas(yahoo: Any) -> Any:
    return _run(NGASFunction(deps=FunctionDeps(yfinance=yahoo)).execute(contract="NG=F"))


def test_stale_previous_close_is_replaced_by_the_prior_daily_bar() -> None:
    # previousClose 3.533 contradicts the daily bar 3.00 for the prior session.
    result = _ngas(_Yahoo(close_prev=3.533, bars=_daily_bars()))
    assert result.data["status"] == "ok"
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(3.00)
    assert row["change"] == pytest.approx(3.10 - 3.00)
    assert row["change_pct"] == pytest.approx((3.10 / 3.00 - 1) * 100)
    assert row["prev_source"] == "daily_bar_prior_close"
    assert row["prev_check"] == "quote_previous_close_disagrees"
    assert any("previousClose" in w for w in result.warnings)


def test_previous_close_that_matches_the_daily_bar_is_kept_and_marked_verified() -> None:
    result = _ngas(_Yahoo(close_prev=3.00, bars=_daily_bars()))
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(3.00)
    assert row["prev_source"] == "quote_previous_close"
    assert row["prev_check"] == "matches_daily_bar"
    assert row["change_pct"] == pytest.approx((3.10 / 3.00 - 1) * 100)


def test_previous_close_without_daily_bars_is_labelled_unverified() -> None:
    result = _ngas(_Yahoo(close_prev=3.00, bars=None))
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(3.00)
    assert row["prev_source"] == "quote_previous_close"
    assert row["prev_check"] == "unverified_no_daily_bar"


def test_missing_quote_previous_close_takes_the_daily_bar_value() -> None:
    result = _ngas(_Yahoo(close_prev=None, bars=_daily_bars()))
    row = result.data["rows"][0]
    assert row["prev"] == pytest.approx(3.00)
    assert row["prev_source"] == "daily_bar_prior_close"
    assert row["prev_check"] == "quote_previous_close_missing"


def test_no_previous_close_and_no_daily_bars_gives_no_change() -> None:
    result = _ngas(_Yahoo(close_prev=None, bars=None))
    row = result.data["rows"][0]
    assert row["prev"] is None
    assert row["change"] is None
    assert row["change_pct"] is None
    assert row["prev_source"] is None


def test_evening_quote_uses_the_eastern_trade_day_not_the_utc_date(monkeypatch) -> None:
    """NGAS#2: at 20:00 ET the UTC date is already tomorrow. The forming bar of
    the current trade day must not be taken as the prior close."""
    import showme.engine.functions.commodity._funcs as funcs

    evening = datetime(2024, 6, 4, 0, 30, tzinfo=UTC)  # 2024-06-03 20:30 ET
    monkeypatch.setattr(sys.modules[__name__], "MARKET_TIME", evening)
    result = _ngas(_Yahoo(close_prev=3.00, bars=_daily_bars()))
    row = result.data["rows"][0]
    assert funcs._exchange_trade_day(evening.isoformat()) == "2024-06-03"
    assert row["prev"] == pytest.approx(3.00)
    assert row["change"] == pytest.approx(0.10)
    assert row["prev_check"] == "matches_daily_bar"
