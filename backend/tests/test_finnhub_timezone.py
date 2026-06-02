"""B5 regression: Finnhub adapter must treat naive datetimes as ET.

Finnhub's REST API expects:

* ``/stock/candle?from=…&to=…`` — **UTC epoch seconds**;
* ``/company-news?from=YYYY-MM-DD&to=YYYY-MM-DD`` — **NY-local calendar
  dates**.

The original adapter was calling ``datetime.now()`` (no tz) and
``dt.strftime("%Y-%m-%d")`` on whatever ``request.start`` happened to be,
which silently leaked the host machine's offset into the query window. The
fix routes everything through tz-aware helpers; these tests pin them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity.finnhub_adapter import (
    FinnhubAdapter,
    _ensure_utc,
    _epoch_seconds,
    _to_ny_date_str,
)


def test_b5_ensure_utc_localizes_naive_to_et():
    """A naive 12:00 timestamp ⇒ 17:00 UTC during EST (UTC-5)."""
    naive = datetime(2026, 1, 15, 12, 0, 0)  # winter ⇒ EST UTC-5
    converted = _ensure_utc(naive)
    assert converted.tzinfo is timezone.utc
    assert converted.hour == 17


def test_b5_ensure_utc_preserves_aware_datetimes():
    aware = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    converted = _ensure_utc(aware)
    assert converted == aware


def test_b5_epoch_seconds_uses_utc_epoch():
    aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert _epoch_seconds(aware) == 1767225600


def test_b5_to_ny_date_str_uses_ny_calendar_day():
    """A UTC midnight that falls on the previous NY day must render as that day."""
    # 2026-01-02 03:00 UTC = 2026-01-01 22:00 EST
    utc_dt = datetime(2026, 1, 2, 3, 0, 0, tzinfo=timezone.utc)
    assert _to_ny_date_str(utc_dt) == "2026-01-01"


async def test_b5_news_request_uses_ny_local_date_format():
    """``request.start``/``request.end`` must be reformatted via NY tz."""
    adapter = FinnhubAdapter({"base_url": "https://example.test"})
    adapter.api_key = "fake-key"
    request = DataRequest(
        kind=DataKind.NEWS,
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        start=datetime(2026, 1, 2, 3, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 5, 3, 0, 0, tzinfo=timezone.utc),
    )
    with patch.object(adapter, "_get", new=AsyncMock(return_value=[])) as get:
        await adapter.fetch(request)
    args, kwargs = get.call_args
    assert args[0] == "/company-news"
    assert kwargs["from"] == "2026-01-01"
    assert kwargs["to"] == "2026-01-04"


async def test_b5_ohlcv_request_uses_utc_epoch_seconds():
    adapter = FinnhubAdapter({"base_url": "https://example.test"})
    adapter.api_key = "fake-key"
    request = DataRequest(
        kind=DataKind.OHLCV,
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        interval="D",
        start=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 8, 0, 0, 0, tzinfo=timezone.utc),
    )
    with patch.object(adapter, "_get", new=AsyncMock(return_value={"s": "no_data"})) as get:
        await adapter.fetch(request)
    args, kwargs = get.call_args
    assert args[0] == "/stock/candle"
    assert kwargs["from"] == 1767225600  # 2026-01-01 UTC
    assert kwargs["to"] == 1767830400   # 2026-01-08 UTC


async def test_b5_default_end_is_now_utc(monkeypatch):
    """Missing ``request.end`` must default to ``datetime.now(tz=utc)``."""
    adapter = FinnhubAdapter({"base_url": "https://example.test"})
    adapter.api_key = "fake-key"
    request = DataRequest(
        kind=DataKind.NEWS,
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
    )
    with patch.object(adapter, "_get", new=AsyncMock(return_value=[])) as get:
        await adapter.fetch(request)
    args, kwargs = get.call_args
    # The default end is "now" which translates to a string we just check is
    # in YYYY-MM-DD shape (10 chars) — we don't assert today's date because
    # the test could span midnight in NY.
    assert len(kwargs["from"]) == 10
    assert len(kwargs["to"]) == 10
    assert kwargs["to"].count("-") == 2
