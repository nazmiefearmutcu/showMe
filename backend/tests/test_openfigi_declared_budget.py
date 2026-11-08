"""ISIN#2 — single lookups must honour the adapter's declared OpenFIGI budget.

The anonymous budget is 25 requests per minute, which the adapter declares as
``rate_limit_rps = 0.41``. ``lookup`` and ``lookup_by`` used a hard-coded
``@throttle(rps=4.0)``, about ten times that budget, so consecutive single lookups
burst straight into HTTP 429. Both now pace through the same ``_next_slot`` budget
that ``lookup_batch`` uses, at the instance's ``rate_limit_rps``.

Time is faked and no network is used. The client answers 200 and counts requests.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from showme.engine.data_sources.reference import openfigi_adapter as figi_mod
from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIAdapter

ANONYMOUS_SLOT_SECONDS = 1.0 / 0.41


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        self.calls += 1
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        body = [{"data": [{"figi": "BBG000B9XRY4", "ticker": "AAPL", "name": "APPLE INC", "exchCode": "US"}]}]
        return httpx.Response(200, request=request, json=body)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(figi_mod, "time", SimpleNamespace(monotonic=c.monotonic))
    monkeypatch.setattr(figi_mod, "asyncio", SimpleNamespace(sleep=c.sleep))
    return c


def _anonymous_adapter(client: _CountingClient) -> OpenFIGIAdapter:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter.rate_limit_rps = 0.41
    adapter._client = client  # type: ignore[assignment]
    return adapter


def test_two_single_lookups_are_spaced_by_the_declared_budget(clock: _Clock) -> None:
    client = _CountingClient()
    adapter = _anonymous_adapter(client)

    async def _two() -> None:
        await adapter.lookup("AAPL")
        await adapter.lookup("MSFT")

    asyncio.run(_two())

    assert client.calls == 2
    # The second request may not leave until one declared slot (about 2.44 s) has passed.
    assert sum(clock.slept) == pytest.approx(ANONYMOUS_SLOT_SECONDS, abs=1e-6), clock.slept


def test_two_lookup_by_calls_are_spaced_by_the_declared_budget(clock: _Clock) -> None:
    client = _CountingClient()
    adapter = _anonymous_adapter(client)

    async def _two() -> None:
        await adapter.lookup_by(id_type="ID_ISIN", id_value="US0378331005")
        await adapter.lookup_by(id_type="ID_ISIN", id_value="US5949181045")

    asyncio.run(_two())

    assert client.calls == 2
    assert sum(clock.slept) == pytest.approx(ANONYMOUS_SLOT_SECONDS, abs=1e-6), clock.slept


def test_single_lookups_share_the_batch_budget(clock: _Clock) -> None:
    # A batch that has just used the anonymous budget must also delay a following single lookup.
    client = _CountingClient()
    adapter = _anonymous_adapter(client)

    async def _mixed() -> None:
        await adapter.lookup_batch([("ID_ISIN", "US0378331005")], max_wait_seconds=60.0)
        await adapter.lookup("AAPL")

    asyncio.run(_mixed())

    assert sum(clock.slept) == pytest.approx(ANONYMOUS_SLOT_SECONDS, abs=1e-6), clock.slept
