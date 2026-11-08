"""MAP 1D change must be measured against the prior session close (P1a-g12 MAP#1).

The Yahoo chart request uses ``range=5d``. The response meta then carries
``chartPreviousClose`` = the close before the 5-day window, and no
``previousClose``/``regularMarketPreviousClose``. Using that as the baseline made
every "1D" change a multi-session move (SPY showed -2.70% while the true
prior-session change was +0.31%). The baseline must be the prior regular-session
daily close, taken from the bars.

Network is patched: ``requests.get`` returns a recorded-shape chart payload.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme import quotes
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import wmap

# Chart payload shaped like Yahoo v8 for SPY (range=5d, interval=1d), 2026-11-02..06.
# Last session 2026-11-06 close 735.29 (regular session already started 2026-11-06 09:30 EST).
_TS = [1793629800, 1793716200, 1793802600, 1793889000, 1793975400]  # 11-02 .. 11-06 (14:30 UTC)
_CLOSES = [752.10, 754.35, 766.81, 733.00, 735.29]
_REGULAR_START_11_06 = 1793975400  # 2026-11-06 09:30 EST (14:30 UTC)
_MARKET_TIME_11_06 = 1793982600  # 2026-11-06 11:30 EST, the last price's own timestamp
_FRIDAY_CLOSE_11_06 = 1793998800  # 2026-11-06 16:00 EST (21:00 UTC), the Friday close
_TS_11_09 = 1794234600  # 2026-11-09 09:30 EST (14:30 UTC): the Monday bar


def _chart_payload(
    closes: list[float | None] = _CLOSES,
    timestamps: list[int] = _TS,
    regular_start: int | None = _REGULAR_START_11_06,
    market_time: int | None = _MARKET_TIME_11_06,
    market_price: float = 735.29,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "regularMarketPrice": market_price,
        "previousClose": None,
        "chartPreviousClose": 755.72,  # close before the 5-day window: the wrong baseline
        "regularMarketVolume": 1000,
        "currency": "USD",
        "exchangeName": "PCX",
        "bid": 735.28,
        "ask": 735.30,
        "timezone": "EST",
        "gmtoffset": -18000,  # UTC-5 (EST), used to take exchange-local session dates
    }
    if market_time is not None:
        meta["regularMarketTime"] = market_time
    if regular_start is not None:
        meta["currentTradingPeriod"] = {"regular": {"start": regular_start, "end": regular_start + 23400}}
    return {"chart": {"result": [{
        "meta": meta,
        "timestamp": timestamps,
        "indicators": {"quote": [{"close": closes, "volume": [1000] * len(closes)}]},
    }], "error": None}}


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _patch_chart(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    def _get(url: str, *args: Any, **kwargs: Any) -> _Resp:
        assert "query1.finance.yahoo.com/v8/finance/chart/" in url, url
        return _Resp(payload)

    monkeypatch.setattr(quotes.requests, "get", _get)
    quotes.quote_cache_clear()


def test_yahoo_chart_baseline_is_the_prior_session_close(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_chart(monkeypatch, _chart_payload())
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["last"] == pytest.approx(735.29)
    # Prior regular session close is 733.00 (2026-11-05), not the 5-day baseline 755.72.
    assert snap["previous_close"] == pytest.approx(733.00)
    assert snap["change_pct"] == pytest.approx((735.29 / 733.00 - 1.0) * 100.0, abs=1e-9)
    assert snap["change_pct"] == pytest.approx(0.3124, abs=1e-3)


def test_prior_close_is_the_last_bar_before_a_new_regular_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-market 2026-11-09: the bars end on 11-06 and the current regular session starts 11-09.
    _patch_chart(monkeypatch, _chart_payload(regular_start=1794234600))  # 2026-11-09 09:30 EST
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["previous_close"] == pytest.approx(735.29)  # the 11-06 close is the prior session


def test_prior_close_without_trading_period_is_the_bar_before_the_price_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No session boundary published: the last price is 11-06, so the prior session is 11-05.
    _patch_chart(monkeypatch, _chart_payload(regular_start=None))
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["previous_close"] == pytest.approx(733.00)


def test_in_session_null_bar_does_not_push_the_baseline_two_sessions_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 2026-11-09 mid-session: today's bar exists with no close yet, and the last price is
    # Monday's. The prior session is Friday 11-06 (735.29). The old penultimate-bar fallback
    # returned 11-05 (733.00), which is two sessions back.
    closes = [*_CLOSES, None]
    timestamps = [*_TS, _TS_11_09]
    _patch_chart(monkeypatch, _chart_payload(
        closes=closes, timestamps=timestamps, regular_start=None,
        market_time=1794236400, market_price=740.00,  # 2026-11-09 10:00 EST
    ))
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["previous_close"] == pytest.approx(735.29)
    assert snap["change_pct"] == pytest.approx((740.00 / 735.29 - 1.0) * 100.0, abs=1e-9)


def test_weekend_price_uses_the_friday_session_against_thursday(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sunday 2026-11-08: the last price is Friday's close, so the 1D move is Friday vs Thursday.
    _patch_chart(monkeypatch, _chart_payload(regular_start=None, market_time=_FRIDAY_CLOSE_11_06))
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["previous_close"] == pytest.approx(733.00)


def test_no_price_time_means_no_baseline_not_a_guessed_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without a price timestamp or a session boundary the prior session cannot be established:
    # the baseline and the 1D change stay empty instead of taking an arbitrary bar.
    _patch_chart(monkeypatch, _chart_payload(regular_start=None, market_time=None))
    snap = quotes._fetch_yahoo_chart_quote("SPY")
    assert snap["previous_close"] is None
    assert snap["change_pct"] is None


def test_map_1d_change_matches_the_prior_session_move(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_chart(monkeypatch, _chart_payload())
    res = asyncio.run(wmap.MAPFunction(FunctionDeps()).execute(live=True, screen_timeout=4))
    rows = {row["etf"]: row for row in res.data["rows"]}
    # The US row is EUSA (MSCI USA) since MAP#2. The chart payload is a recorded
    # SPY chart reused only as a stub shape for whichever ticker is quoted; the
    # assertions check the baseline arithmetic, not any fund's real price.
    eusa = rows["EUSA"]
    assert eusa["quote_type"] == "live"
    assert eusa["last"] == pytest.approx(735.29)
    assert eusa["change_pct"] == pytest.approx(0.3124, abs=1e-3)
    assert eusa["change_pct"] > 0  # the sign is the prior-session sign, not the 5-day sign
