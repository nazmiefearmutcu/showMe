"""ISIN follow-ups (G1 bond-api): honest provenance and a wall-clock call budget.

* A refusal made by the local pacing budget sends no request. Its text must say
  so, and must not read like an upstream HTTP 429.
* HTTP latency counts against the call. A slow OpenFIGI must not push one
  ISIN call past its function timeout. Batches that cannot finish inside the
  call budget are reported per identifier, and the resolved ones are kept.

No network: the OpenFIGI client is a fake. The pacing test fakes time; the
wall-clock test uses real (very short) delays.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.reference import openfigi_adapter as figi_mod
from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIAdapter
from showme.engine.functions.api import isin as isin_mod
from showme.engine.functions.api.isin import ISINFunction


def _ids(n: int) -> list[str]:
    return [f"TK{i:02d}" for i in range(n)]


def _body(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"data": [{"figi": f"BBG{j['idValue']}", "ticker": j["idValue"], "name": "x", "exchCode": "US", "securityType": "Common Stock"}]}
        for j in jobs
    ]


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FastFigi:
    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        return httpx.Response(200, request=request, json=_body(json or []))


class _SlowFigi:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        await asyncio.sleep(self.delay)
        return httpx.Response(200, request=request, json=_body(json or []))


class _Always429:
    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        return httpx.Response(429, request=request, headers={"retry-after": "17"}, json={"error": "Too many requests"})


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(figi_mod, "time", SimpleNamespace(monotonic=c.monotonic))
    monkeypatch.setattr(figi_mod, "asyncio", SimpleNamespace(sleep=c.sleep))
    monkeypatch.setattr(isin_mod, "time", SimpleNamespace(monotonic=c.monotonic))
    return c


def _errors(res: Any) -> dict[str, str]:
    return {g["input"]: g["error"] for g in res.data["match_groups"] if g.get("error")}


def test_local_pacing_refusal_says_no_request_was_sent(clock: _Clock) -> None:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = _FastFigi()  # type: ignore[assignment]
    adapter.rate_limit_rps = 0.41
    # The previous call used the budget: 6 s are already owed, so later batches are refused locally.
    adapter._next_slot = clock.now + 6.0

    res = asyncio.run(ISINFunction(FunctionDeps(openfigi=adapter)).execute(ids=",".join(_ids(30))))

    errors = _errors(res)
    assert errors, res.data
    for msg in errors.values():
        assert "no request was sent" in msg.lower(), msg
        assert "http 429" not in msg.lower(), msg
    assert "no request was sent" in " ".join(res.warnings).lower()


def test_http_429_reason_does_not_claim_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = _Always429()  # type: ignore[assignment]
    adapter.rate_limit_rps = 1000.0

    res = asyncio.run(ISINFunction(FunctionDeps(openfigi=adapter)).execute(ids="TK00,TK01"))

    reason = str(res.data.get("reason") or "")
    assert "HTTP 429" in reason, reason
    assert "no request was sent" not in reason.lower(), reason
    assert "rate limit reached" in reason.lower(), reason


def test_slow_openfigi_cannot_push_one_call_past_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # Three batches of 10. One answer takes 0.6 s and the call budget is 1.0 s:
    # batch 1 fits, batch 2 cannot finish in the 0.4 s left, batch 3 is never sent.
    monkeypatch.setattr(isin_mod, "_CALL_WALL_BUDGET_SECONDS", 1.0)
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = _SlowFigi(delay=0.6)  # type: ignore[assignment]
    adapter.rate_limit_rps = 1000.0

    started = time.monotonic()
    res = asyncio.run(ISINFunction(FunctionDeps(openfigi=adapter)).execute(ids=",".join(_ids(30))))
    elapsed = time.monotonic() - started

    assert elapsed < 1.6, elapsed
    groups = {g["input"]: g for g in res.data["match_groups"]}
    assert set(groups) == set(_ids(30)), "no input may vanish from the response"
    resolved = [i for i in groups if groups[i]["matches"]]
    failed = [i for i in groups if groups[i].get("error")]
    assert len(resolved) == 10, resolved
    assert len(failed) == 20, failed
    assert all("time budget" in groups[i]["error"] for i in failed), [groups[i]["error"] for i in failed]
    assert res.data["status"] == "partial", res.data["status"]
