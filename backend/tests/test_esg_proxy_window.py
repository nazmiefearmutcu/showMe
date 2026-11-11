"""ESG SEC-proxy counts are a dated window of 10-K filings, not all-years (ESG#1).

The EFTS query used to carry no date range, so AAPL's 'recent 10-K' counts were
filings from 2009 onward, and the total was the sum of the three pillar counts,
which double-counts filings that mention more than one pillar.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import showme.providers._http as http_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.esg import ESGFunction


def _run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, total: int):
        self._total = total

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"hits": {"total": {"value": self._total, "relation": "eq"}, "hits": []}}


class _FakeClient:
    """Answers each EFTS query by which pillar term it contains."""

    def __init__(self, totals: dict[str, int]):
        self.totals = totals
        self.calls: list[dict] = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params or {}))
        q = params["q"]
        if "climate change" in q and "diversity" in q:
            return _FakeResponse(self.totals["union"])
        if "climate change" in q:
            return _FakeResponse(self.totals["environment"])
        if "diversity" in q:
            return _FakeResponse(self.totals["social"])
        return _FakeResponse(self.totals["governance"])


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    async def _get_client():
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)


def test_proxy_queries_carry_a_recent_date_window(monkeypatch):
    client = _FakeClient({"environment": 3, "social": 5, "governance": 7, "union": 9})
    _patch_client(monkeypatch, client)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    assert client.calls, "proxy must query EDGAR full-text search"
    today = date.today()
    for params in client.calls:
        assert "startdt" in params, "EFTS query must bound the filing dates"
        assert params["enddt"] == today.isoformat()
        start = date.fromisoformat(params["startdt"])
        assert today - timedelta(days=3 * 366 + 5) <= start <= today - timedelta(days=3 * 365 - 5)
    assert result.data["window"]["startdt"] == client.calls[0]["startdt"]


def test_proxy_total_is_filings_matching_any_term_not_sum_of_pillars(monkeypatch):
    client = _FakeClient({"environment": 3, "social": 5, "governance": 7, "union": 9})
    _patch_client(monkeypatch, client)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    data = result.data
    assert data["totalEsg"] == 9  # was 15 = 3 + 5 + 7 (double-counted filings)
    assert data["environmentScore"] == 3
    assert data["socialScore"] == 5
    assert data["governanceScore"] == 7
    assert data["rows"][0]["score"] == 9


def test_methodology_describes_the_real_signal(monkeypatch):
    client = _FakeClient({"environment": 1, "social": 1, "governance": 1, "union": 2})
    _patch_client(monkeypatch, client)
    result = _run(ESGFunction(FunctionDeps()).execute(instrument=_instrument()))
    text = result.data["methodology"]
    assert "last 3 years" in text
    assert "not term frequency" in text.lower() or "filings containing" in text.lower()
    assert "term-frequency" not in text.lower()
