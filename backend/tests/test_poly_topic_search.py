"""POLY#3 regression: topic queries must reach Polymarket's real search.

Gamma's ``/markets`` ignores its ``search`` parameter, so every topic returned
the same top-volume markets and the client-side AND-token filter then dropped
relevant ones. Topic queries now go to ``/public-search``. The HTTP client is
a fake; no network is used.
"""

from __future__ import annotations

import asyncio

import showme.providers._http as http_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc.poly import POLYFunction


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _market(question, slug, *, closed=False, price="0.40"):
    return {
        "id": slug,
        "slug": slug,
        "question": question,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{price}", "{round(1 - float(price), 2)}"]',
        "liquidity": "120000",
        "volume": "300000",
        "endDate": "2099-06-30T00:00:00Z",
        "active": not closed,
        "closed": closed,
        "umaResolutionStatus": None,
    }


_EVENTS = {
    "events": [
        {
            "title": "Fed decision",
            "endDate": "2099-06-30T00:00:00Z",
            "markets": [
                # Relevant to "fed cuts" although it does not contain the word "cuts".
                _market("Fed Decision in December?", "fed-decision-dec"),
                _market("Fed cuts rates in September?", "fed-cut-sept-closed", closed=True),
            ],
        },
        {
            "title": "Rate cuts",
            "endDate": "2099-12-31T00:00:00Z",
            "markets": [_market("How many Fed rate cuts in 2026?", "fed-cuts-2026", price="0.25")],
        },
    ],
    "pagination": {"hasMore": False, "totalResults": 2},
}


class _RecordingClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/public-search"):
            return _Resp(_EVENTS)
        # Gamma /markets: returns the same top-volume list whatever the search param says.
        return _Resp([_market("Xi Jinping out before 2027?", "xi-out")])


def _patch_client(monkeypatch):
    client = _RecordingClient()

    async def _get_client():
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)
    return client


def _run(coro):
    return asyncio.run(coro)


def test_topic_query_is_sent_to_public_search_and_relevant_markets_are_kept(monkeypatch):
    client = _patch_client(monkeypatch)
    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(query="fed cuts", status="open", limit=10))

    search_calls = [c for c in client.calls if c[0].endswith("/public-search")]
    assert search_calls, f"topic query never reached public-search: {client.calls}"
    assert search_calls[0][1].get("q") == "fed cuts"
    assert not any("search" in params for _, params in client.calls), (
        "the Gamma /markets endpoint ignores 'search'; it must not be sent there"
    )

    data = result.data
    assert data["status"] == "ok"
    questions = {m["question"] for m in data["markets"]}
    # Server relevance decides: a market that matches only one of the words is kept.
    assert "Fed Decision in December?" in questions
    assert "How many Fed rate cuts in 2026?" in questions
    # Xi Jinping (the /markets fallback row) must not leak into a topic result.
    assert "Xi Jinping out before 2027?" not in questions


def test_topic_query_still_drops_closed_markets_when_status_is_open(monkeypatch):
    _patch_client(monkeypatch)
    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(query="fed cuts", status="open", limit=10))
    questions = {m["question"] for m in result.data["markets"]}
    assert "Fed cuts rates in September?" not in questions


def test_topic_query_with_no_matches_reports_the_reason(monkeypatch):
    class _EmptySearch(_RecordingClient):
        async def get(self, url, params=None, timeout=None):
            self.calls.append((url, dict(params or {})))
            return _Resp({"events": [], "pagination": {"hasMore": False}})

    client = _EmptySearch()

    async def _get_client():
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)
    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(query="zzqx no such topic", status="open", limit=10))
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    assert any("zzqx no such topic" in w for w in result.warnings)


def test_browse_without_query_still_uses_markets_endpoint(monkeypatch):
    client = _patch_client(monkeypatch)
    fn = POLYFunction(FunctionDeps())
    _run(fn.execute(status="open", limit=10))
    assert client.calls
    assert all(not url.endswith("/public-search") for url, _ in client.calls)
    assert all(url.endswith("/markets") for url, _ in client.calls)
