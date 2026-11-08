"""P2A-G07 regression tests: DEBT#4 residual (unsupported ISO-2 codes are reported).

The World Bank client is replaced with a fake; no network is used.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.bond import _stubs


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.urls: list[str] = []

    async def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        return _FakeResponse([{}, [{"value": 61.5, "date": "2024"}]])


def _debt(monkeypatch):
    client = _FakeClient()

    async def _get_client():
        return client

    monkeypatch.setattr(_stubs, "get_client", _get_client)
    return _stubs.DEBTFunction(), client


def _run(coro):
    return asyncio.run(coro)


def test_debt_unknown_iso2_code_is_reported_not_silently_dropped(monkeypatch):
    fn, client = _debt(monkeypatch)
    res = _run(fn.execute(countries="US,XX"))
    d = res.data
    assert d["status"] == "ok"
    assert [r["country"] for r in d["rows"]] == ["US"]
    # XX has no World Bank mapping: it must be named, not vanish.
    assert d["summary"]["unsupported_countries"] == ["XX"]
    assert any("XX" in w for w in res.warnings)
    assert all("/USA/" in u for u in client.urls)


def test_debt_only_unknown_codes_is_an_input_error(monkeypatch):
    fn, client = _debt(monkeypatch)
    res = _run(fn.execute(countries="XX"))
    assert res.data["status"] == "input_error"
    assert res.data["summary"]["unsupported_countries"] == ["XX"]
    assert "XX" in res.data["reason"]
    assert client.urls == []
