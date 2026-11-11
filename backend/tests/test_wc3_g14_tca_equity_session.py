"""TCA#2 follow-up: an exchange-listed equity benchmark is the fill's exchange-local session.

yfinance reads a naive ``start``/``end`` date in the exchange's timezone, so the old
request for the fill's UTC calendar day returned the exchange session of that date.
A US fill at 2026-09-12T02:00Z is 22:00 EDT on 2026-09-11; the old request pulled the
2026-09-12 session, which opens after the fill (look-ahead).

The fake ``yfinance.Ticker`` below reproduces that behaviour: naive dates are localised
to America/New_York, and the returned frame carries a tz-aware index in that zone.
No network is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import pytest
import yfinance

from showme.bots.record import BotRecord, SignalEntry
from showme.bots.store import BotStore
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.trade.tca import TCAFunction

_NY = "America/New_York"

# (exchange-local timestamp, price). Each bar has high = low = close = price.
_BARS = [
    ("2026-09-11 10:00", 100.0),
    ("2026-09-11 14:00", 110.0),
    ("2026-09-12 10:00", 300.0),  # the future session the old request returned
]


class _FakeTicker:
    """Mimics yfinance.Ticker.history for interval=5m: naive dates are exchange-local."""

    requests: list[tuple[str, str]] = []

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, start=None, end=None, interval="5m", **_: object) -> pd.DataFrame:
        _FakeTicker.requests.append((str(start), str(end)))
        lo = pd.Timestamp(start).tz_localize(_NY)
        hi = pd.Timestamp(end).tz_localize(_NY)
        rows = []
        for stamp, px in _BARS:
            ts = pd.Timestamp(stamp).tz_localize(_NY)
            if lo <= ts < hi:
                rows.append((ts, px))
        index = pd.DatetimeIndex([ts for ts, _ in rows], tz=_NY)
        return pd.DataFrame(
            {
                "High": [px for _, px in rows],
                "Low": [px for _, px in rows],
                "Close": [px for _, px in rows],
                "Volume": [1000.0 for _ in rows],
            },
            index=index,
        )


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setattr(
        "showme.engine.services.order_history.runtime_path",
        lambda name: tmp_path / "runtime" / name,
    )
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    _FakeTicker.requests = []
    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    # The fixture fill is a fixed 2026-09 date; once it is older than the
    # provider's intraday retention the handler (rightly) asks for no bars.
    # The session-window logic under test does not depend on the fill's age.
    from showme.engine.functions.trade import tca as tca_mod

    monkeypatch.setattr(tca_mod, "_INTRADAY_RETENTION_DAYS", 10**6)
    yield


def _seed_equity_fill(filled_at: str, fill_px: float = 112.0) -> None:
    BotStore.fresh().save(BotRecord(
        strategy_id="s1", credential_id="c1", exchange_id="ibkr",
        symbol="AAPL", timeframe="1h", mode="live", enabled=True,
        signal_log=[SignalEntry(
            bar_index=0, bar_time="2026-09-11T15:55:00Z", kind="entry",
            price=111.0, action="placed", order_id="eq-session",
            fill_price=fill_px, qty=2.0, bar_close_time=filled_at,
        )],
    ))


def test_after_hours_equity_fill_is_benchmarked_on_its_exchange_session() -> None:
    # 02:00Z on 2026-09-12 is 22:00 EDT on 2026-09-11: the fill belongs to the
    # 2026-09-11 exchange session, whose VWAP over the two bars is (100+110)/2.
    _seed_equity_fill("2026-09-12T02:00:00Z")

    res = asyncio.new_event_loop().run_until_complete(
        TCAFunction(deps=FunctionDeps()).execute(symbol="AAPL", benchmark="VWAP"))
    row = res.data["rows"][0]

    assert row["benchmark_source"] == "yfinance", row
    assert row["benchmark_px"] == pytest.approx(105.0), row
    # The 2026-09-12 session (opens after the fill) must not be used.
    assert row["benchmark_px"] != pytest.approx(300.0)


def test_equity_request_window_covers_the_fill_exchange_session() -> None:
    _seed_equity_fill("2026-09-12T02:00:00Z")
    asyncio.new_event_loop().run_until_complete(
        TCAFunction(deps=FunctionDeps()).execute(symbol="AAPL", benchmark="VWAP"))

    assert _FakeTicker.requests, "yfinance was never asked for bars"
    start, end = _FakeTicker.requests[0]
    # Naive dates are read in the exchange timezone: the request must start no later
    # than the exchange-local day before the UTC day, and end after the fill's day.
    assert start <= "2026-09-11", (start, end)
    assert end > "2026-09-12", (start, end)


def test_methodology_no_longer_claims_the_utc_day_for_equities() -> None:
    _seed_equity_fill("2026-09-12T02:00:00Z")
    res = asyncio.new_event_loop().run_until_complete(
        TCAFunction(deps=FunctionDeps()).execute(symbol="AAPL", benchmark="VWAP"))
    methodology = res.data["methodology"]
    assert "exchange-local trading day of the fill for exchange-listed equities" in methodology, methodology
    assert "the UTC calendar day of the fill (TCA#2" not in methodology, methodology


def test_fixture_fill_is_previous_exchange_day_in_new_york() -> None:
    # Sanity on the fixture: 02:00Z on 2026-09-12 is still 2026-09-11 in New York.
    stamp = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)
    assert stamp.astimezone(ZoneInfo(_NY)).date().isoformat() == "2026-09-11"
