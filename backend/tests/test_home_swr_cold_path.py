"""Home-page SWR cold path (MOST#2, shared root cause of TOP#1).

A cold TOP/BRIEF/MOST call used to wait 1.0 s for the function (3.5 s when
joining a boot prewarm) and then answer an empty "warming in background"
provider_unavailable envelope, although the real payload landed moments
later; the panes do not re-poll, so the user saw empty movers/news. The cold
path now waits up to the function budget and returns the real payload, an
honest timeout, or the function's own error - never an empty "warming" answer
while a result is on its way.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return {"code": "MOST", "data": self.data, "sources": ["yfinance"], "metadata": {}, "warnings": [],
                "fetched_at": "2026-11-08T05:00:00+00:00"}


ROWS = {"rows": [{"symbol": "NVDA", "change_pct": 3.2}, {"symbol": "AAPL", "change_pct": -1.1}]}


@pytest.fixture
def swr_app(monkeypatch):
    from showme import server
    from showme.server_routes import AppDeps, function_index

    store: dict[str, Any] = {}
    monkeypatch.setattr(server, "home_swr_enabled", lambda: True)
    monkeypatch.setattr(server, "_route_function_params", lambda code, params: dict(params))
    monkeypatch.setattr(server, "home_swr_get", lambda key: None)
    monkeypatch.setattr(server, "home_swr_store", lambda key, payload: store.__setitem__(key, payload))
    monkeypatch.setattr(server, "home_swr_capture", lambda *a, **k: None)
    monkeypatch.setattr(server, "home_swr_track", lambda *a, **k: None)
    monkeypatch.setattr(server, "home_swr_inflight_task", lambda key: None)

    def build() -> TestClient:
        app = FastAPI()
        function_index.register(app, AppDeps(boot_state={"engine_attached": True}))
        return TestClient(app)

    return build, store


def test_cold_call_returns_the_real_payload_not_a_warming_envelope(monkeypatch, swr_app):
    from showme import server

    async def slow_exec(code: str, params: dict[str, Any]) -> Any:
        await asyncio.sleep(1.5)  # longer than the old 1.0 s head start
        return _Result(ROWS)

    monkeypatch.setattr(server, "_execute_showme_function", slow_exec)
    build, store = swr_app
    body = build().post("/api/fn/MOST", json={}).json()
    assert "warming" not in str(body.get("reason") or "")
    assert body["status"] == "ok"
    assert body["rows"] and body["rows"][0]["symbol"] == "NVDA"
    assert store, "the payload must also land in the SWR cache"


def test_joining_a_slow_prewarm_waits_for_its_result(monkeypatch, swr_app):
    from showme import server

    async def slow_prewarm() -> Any:
        await asyncio.sleep(4.0)  # longer than the old 3.5 s join window
        return _Result(ROWS)

    monkeypatch.setattr(server, "home_swr_inflight_task", lambda key: asyncio.ensure_future(slow_prewarm()))
    monkeypatch.setattr(server, "_execute_showme_function",
                        lambda *a, **k: pytest.fail("must join the prewarm, not start a duplicate"))
    build, _store = swr_app
    body = build().post("/api/fn/MOST", json={}).json()
    assert body["status"] == "ok"
    assert body["rows"][0]["symbol"] == "NVDA"


def test_over_budget_cold_call_is_an_honest_timeout(monkeypatch, swr_app):
    from showme import server

    async def stuck_exec(code: str, params: dict[str, Any]) -> Any:
        await asyncio.sleep(30)
        return _Result(ROWS)

    monkeypatch.setattr(server, "FUNCTION_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(server, "_execute_showme_function", stuck_exec)
    build, _store = swr_app
    body = build().post("/api/fn/MOST", json={}).json()
    assert body["status"] == "provider_unavailable"
    assert "timed out" in str(body.get("reason") or "")
    assert "warming" not in str(body.get("reason") or "")
