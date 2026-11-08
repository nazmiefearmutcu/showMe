"""ISIN#1 follow-up: total pacing inside one ISIN call must fit the 8 s budget.

The ISIN function runs under a 14 s timeout. Each OpenFIGI batch used to get the
full 8 s pacing budget on its own, so a warm anonymous budget could add about
10.9 s of sleeps across three batches (plus HTTP latency) and time out with no
rows. The pacing budget is now one total for the whole call: a batch that would
push the call past the budget is refused and reported per identifier.

Time is faked (no real sleeping, no network). The OpenFIGI client is a fake that
enforces the documented anonymous limits.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.reference import openfigi_adapter as figi_mod
from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIAdapter
from showme.engine.functions.api import isin as isin_mod
from showme.engine.functions.api.isin import ISINFunction

PACING_BUDGET_SECONDS = 8.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _FakeOpenFIGI:
    def __init__(self) -> None:
        self.requests: list[int] = []

    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        jobs = json or []
        self.requests.append(len(jobs))
        body = [{"data": [{"figi": f"BBG{j['idValue']}", "ticker": j["idValue"], "name": "x", "exchCode": "US", "securityType": "Common Stock"}]} for j in jobs]
        return httpx.Response(200, request=request, json=body)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(figi_mod, "time", SimpleNamespace(monotonic=c.monotonic))
    monkeypatch.setattr(figi_mod, "asyncio", SimpleNamespace(sleep=c.sleep))
    monkeypatch.setattr(isin_mod, "time", SimpleNamespace(monotonic=c.monotonic), raising=False)
    return c


def _warm_adapter(fake: _FakeOpenFIGI, clock: _Clock, warm_seconds: float) -> OpenFIGIAdapter:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter.rate_limit_rps = 0.41  # documented anonymous pacing: one request per ~2.44 s
    adapter._client = fake  # type: ignore[assignment]
    # The previous call used the budget; this call starts with `warm_seconds` already owed.
    adapter._next_slot = clock.now + warm_seconds
    return adapter


def test_total_pacing_for_one_thirty_id_call_stays_inside_the_budget(clock: _Clock) -> None:
    fake = _FakeOpenFIGI()
    adapter = _warm_adapter(fake, clock, warm_seconds=6.0)
    ids = [f"TK{i:02d}" for i in range(30)]

    res = asyncio.run(ISINFunction(FunctionDeps(openfigi=adapter)).execute(ids=",".join(ids)))

    total_sleep = sum(clock.slept)
    assert total_sleep <= PACING_BUDGET_SECONDS + 1e-6, (total_sleep, clock.slept)

    groups = {g["input"]: g for g in res.data["match_groups"]}
    assert set(groups) == set(ids), "no input may vanish from the response"
    resolved = [i for i in ids if groups[i]["matches"]]
    failed = [i for i in ids if groups[i].get("error")]
    assert resolved and failed, (len(resolved), len(failed))
    assert len(resolved) + len(failed) == 30
    assert all("rate limit" in groups[i]["error"].lower() for i in failed)
    assert res.data["status"] == "partial", res.data["status"]
    assert res.data["summary"]["unresolved"] == len(failed)


def test_cold_budget_thirty_id_call_still_resolves_every_id(clock: _Clock) -> None:
    fake = _FakeOpenFIGI()
    adapter = _warm_adapter(fake, clock, warm_seconds=0.0)
    ids = [f"TK{i:02d}" for i in range(30)]

    res = asyncio.run(ISINFunction(FunctionDeps(openfigi=adapter)).execute(ids=",".join(ids)))

    assert sum(clock.slept) <= PACING_BUDGET_SECONDS + 1e-6, clock.slept
    assert res.data["status"] == "ok", res.data["status"]
    assert len(res.data["rows"]) == 30
    assert fake.requests == [10, 10, 10]
