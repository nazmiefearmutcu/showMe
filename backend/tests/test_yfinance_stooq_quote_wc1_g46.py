"""ASOF-4 (race path): the stooq equity quote must not stamp fetch time.

The stooq CSV carries Date/Time columns for the exchange quote. The quote is
stamped with that exchange time (US Eastern) or refused when the row has no
usable time. No network: httpx.AsyncClient is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from showme.engine.data_sources.equity import yfinance_adapter as ya
from showme.engine.data_sources.equity.yfinance_adapter import YFinanceAdapter


_HEADER = "Symbol,Date,Time,Open,High,Low,Close,Volume\n"


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: Any = None) -> _Resp:  # noqa: ARG002
        return _Resp(self._text)


def _stooq(monkeypatch: Any, csv_body: str) -> Any:
    monkeypatch.setattr(ya.httpx, "AsyncClient", lambda *a, **k: _Client(_HEADER + csv_body))
    return asyncio.run(YFinanceAdapter()._fetch_stooq_quote("AAPL"))


def test_stooq_quote_is_stamped_with_exchange_time_not_fetch_time(monkeypatch: Any) -> None:
    quote = _stooq(monkeypatch, "AAPL.US,2026-11-06,16:00:00,270,272,269,271.30,1000\n")
    assert quote is not None
    assert quote.last == 271.30
    # 16:00 US Eastern on 2026-11-06 (EST, UTC-5) is 21:00 UTC.
    assert quote.timestamp == datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)


def test_stooq_quote_without_time_is_refused(monkeypatch: Any) -> None:
    assert _stooq(monkeypatch, "AAPL.US,2026-11-06,N/D,270,272,269,271.30,1000\n") is None


def test_stooq_quote_without_date_is_refused(monkeypatch: Any) -> None:
    assert _stooq(monkeypatch, "AAPL.US,N/D,N/D,270,272,269,271.30,1000\n") is None


def test_stooq_quote_timestamp_is_never_utcnow(monkeypatch: Any) -> None:
    calls: list[int] = []
    monkeypatch.setattr(ya, "utcnow", lambda: calls.append(1) or datetime(2030, 1, 1, tzinfo=timezone.utc))
    quote = _stooq(monkeypatch, "AAPL.US,2026-11-06,10:30:00,270,272,269,271.30,1000\n")
    assert quote is not None
    assert quote.timestamp.year == 2026
    assert calls == []
