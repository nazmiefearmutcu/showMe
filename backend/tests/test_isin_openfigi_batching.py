"""ISIN#1 regression: multi-identifier lookups must not silently drop matches.

OpenFIGI documents (openfigi.com/api/documentation, checked 2026-11-08):
  * POST /v3/mapping takes up to 10 jobs per request without an API key
    (100 with one); more is rejected with HTTP 413.
  * 25 requests per minute without a key (250 with one); overflow returns
    HTTP 429 with a ``retry-after`` header.

The ISIN function used to send one request per identifier through a fixed
4 rps throttle, so a 30-ticker call exhausted the anonymous budget after 25
requests. The adapter then slept and returned an empty list, which the
function reported as ordinary empty rows, and the whole call timed out.

No network: the adapter's HTTP client is replaced by a fake transport that
enforces the documented budget.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIAdapter
from showme.engine.functions.api.isin import ISINFunction

ANON_PER_MINUTE = 25
ANON_JOBS_PER_REQUEST = 10


class _FakeOpenFIGI:
    """Serves POST /mapping and enforces the anonymous request budget per call."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.requests: list[int] = []  # number of jobs per request

    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        if len(self.requests) >= self.budget:
            return httpx.Response(
                429,
                request=request,
                headers={"retry-after": "17"},
                json={"error": "Too many requests"},
            )
        jobs = json or []
        assert len(jobs) <= ANON_JOBS_PER_REQUEST, "request exceeds the documented job limit"
        self.requests.append(len(jobs))
        body = []
        for job in jobs:
            value = job["idValue"]
            body.append({"data": [{
                "figi": f"BBG{value}",
                "ticker": value,
                "name": f"{value} Corp",
                "exchCode": "US",
                "securityType": "Common Stock",
            }]})
        return httpx.Response(200, request=request, json=body)


def _adapter(fake: _FakeOpenFIGI) -> OpenFIGIAdapter:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = fake  # type: ignore[assignment]
    # Keep the test fast: pacing is covered separately below.
    adapter.rate_limit_rps = 1000.0
    return adapter


def _ids(n: int) -> list[str]:
    return [f"TK{i:02d}" for i in range(n)]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_thirty_tickers_resolve_with_documented_batching() -> None:
    fake = _FakeOpenFIGI(budget=ANON_PER_MINUTE)
    deps = FunctionDeps(openfigi=_adapter(fake))
    ids = _ids(30)
    res = _run(ISINFunction(deps).execute(ids=",".join(ids)))

    groups = {g["input"]: g for g in res.data["match_groups"]}
    assert set(groups) == set(ids), "every input must appear in the response"
    assert all(groups[i]["matches"] for i in ids), [i for i in ids if not groups[i]["matches"]]
    assert res.data["status"] == "ok", res.data["status"]
    assert len(res.data["rows"]) == 30
    # 30 identifiers fit in 3 batched requests, not 30 single requests.
    assert len(fake.requests) == 3, fake.requests


def test_rate_limited_batch_is_reported_per_identifier_not_silently_dropped() -> None:
    # Budget of two requests: the third batch (ids 20-29) hits HTTP 429.
    fake = _FakeOpenFIGI(budget=2)
    deps = FunctionDeps(openfigi=_adapter(fake))
    ids = _ids(30)
    res = _run(ISINFunction(deps).execute(ids=",".join(ids)))

    groups = {g["input"]: g for g in res.data["match_groups"]}
    assert set(groups) == set(ids), "no input may vanish from the response"
    resolved = [i for i in ids if groups[i]["matches"]]
    failed = [i for i in ids if groups[i].get("error")]
    assert len(resolved) == 20, resolved
    assert len(failed) == 10, failed
    assert all("429" in groups[i]["error"] or "rate" in groups[i]["error"].lower() for i in failed)
    assert res.data["status"] == "partial", res.data["status"]
    assert any("rate" in w.lower() for w in res.warnings), res.warnings


def test_pacing_refuses_to_wait_beyond_the_budget_without_sending() -> None:
    fake = _FakeOpenFIGI(budget=ANON_PER_MINUTE)
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = fake  # type: ignore[assignment]
    adapter.rate_limit_rps = 0.41  # documented anonymous pacing (25 per minute)

    first = _run(adapter.lookup_batch([("TICKER", "TK00")], max_wait_seconds=0.0))
    assert first[0]["data"][0]["ticker"] == "TK00"
    sent_before = len(fake.requests)

    from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIRateLimited

    with pytest.raises(OpenFIGIRateLimited):
        _run(adapter.lookup_batch([("TICKER", "TK01")], max_wait_seconds=0.0))
    assert len(fake.requests) == sent_before, "no request may be sent when the wait is refused"


def test_batch_body_is_a_single_request_per_chunk() -> None:
    fake = _FakeOpenFIGI(budget=ANON_PER_MINUTE)
    adapter = _adapter(fake)
    jobs = [("TICKER", v) for v in _ids(7)]
    out = _run(adapter.lookup_batch(jobs, max_wait_seconds=60.0))
    assert len(out) == 7
    assert fake.requests == [7]
    assert json.dumps(out[0]["data"][0]["ticker"]) == json.dumps("TK00")


def test_fully_rate_limited_call_is_provider_unavailable_with_the_real_reason() -> None:
    # Budget of zero: the first batch already gets HTTP 429.
    fake = _FakeOpenFIGI(budget=0)
    deps = FunctionDeps(openfigi=_adapter(fake))
    res = _run(ISINFunction(deps).execute(ids="TK00,TK01"))
    assert res.data["status"] == "provider_unavailable", res.data["status"]
    assert res.data["rows"] == []
    assert "rate limit" in res.data["reason"].lower(), res.data.get("reason")
    assert res.data["summary"]["unresolved"] == 2
