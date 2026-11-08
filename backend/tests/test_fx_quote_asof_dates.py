"""ASOF-5 — FX quotes must carry the rate's own fixing date, not utcnow().

  * ECB publishes one daily reference fixing dated by the CSV TIME_PERIOD
    (the DataFrame index). The quote used to stamp ``utcnow()`` on the last
    fixing, so a Friday fixing read as fresh on Saturday/Sunday and every
    fixing read as current for the rest of the day.
  * exchangerate.host returns a ``date`` next to ``rates``; the adapter
    discarded it and stamped ``utcnow()``.

No network: ECB is patched at ``euro_rate``; exchangerate.host is served by
an httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pandas as pd

from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.data_sources.fx.ecb_adapter import ECBAdapter
from showme.engine.data_sources.fx.exchangerate_host_adapter import (
    ExchangerateHostAdapter,
)


def _run(coro):
    return asyncio.run(coro)


# ── ECB ───────────────────────────────────────────────────────────────────


def _ecb_frame(values: list[float], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"value": values},
        index=pd.DatetimeIndex(pd.to_datetime(dates), name="date"),
    )


def test_ecb_quote_is_stamped_with_fixing_date_not_now(monkeypatch) -> None:
    adapter = ECBAdapter({})
    frame = _ecb_frame([1.1224, 1.1190], ["2026-11-04", "2026-11-06"])

    async def fake_euro_rate(currency, start=None):
        assert currency == "USD"
        return frame

    monkeypatch.setattr(adapter, "euro_rate", fake_euro_rate)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["EURUSD"])))
    assert quote.last == 1.1190
    # The Friday fixing (2026-11-06) must be dated by its own index, never by
    # the wall clock at the time of the call.
    assert quote.timestamp.tzinfo is not None
    assert quote.timestamp.date() == date(2026, 11, 6), quote.timestamp
    assert quote.timestamp == datetime(2026, 11, 6, tzinfo=UTC)


def test_ecb_quote_without_dated_index_does_not_stamp_a_value(monkeypatch) -> None:
    adapter = ECBAdapter({})
    # A frame whose index is not dates cannot say which fixing it is.
    frame = pd.DataFrame({"value": [1.1190]})

    async def fake_euro_rate(currency, start=None):
        return frame

    monkeypatch.setattr(adapter, "euro_rate", fake_euro_rate)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["EURUSD"])))
    assert quote.last is None


# ── exchangerate.host ─────────────────────────────────────────────────────


def _xr_adapter(handler) -> ExchangerateHostAdapter:
    adapter = ExchangerateHostAdapter({})
    adapter._client = httpx.AsyncClient(
        base_url="https://api.exchangerate.host",
        transport=httpx.MockTransport(handler),
    )
    return adapter


def test_exchangerate_host_quote_uses_response_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/latest"
        return httpx.Response(200, json={
            "success": True,
            "base": "EUR",
            "date": "2026-11-06",
            "rates": {"USD": 1.1190},
        })

    adapter = _xr_adapter(handler)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["EURUSD"])))
    assert quote.last == 1.1190
    assert quote.timestamp == datetime(2026, 11, 6, tzinfo=UTC), quote.timestamp


def test_exchangerate_host_quote_without_date_is_not_stamped_now() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "rates": {"USD": 1.1190}})

    adapter = _xr_adapter(handler)
    quote = _run(adapter.fetch(DataRequest(kind=DataKind.QUOTE, symbols=["EURUSD"])))
    # The rate's date is unknown, so the adapter must not claim a value of
    # unknown age: no last price rather than a wall-clock stamp.
    assert quote.last is None


def test_exchangerate_host_latest_keeps_dict_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"date": "2026-11-06", "rates": {"USD": 1.119}})

    adapter = _xr_adapter(handler)
    rates = _run(adapter.latest("EUR", ["USD"]))
    assert rates == {"USD": 1.119}
