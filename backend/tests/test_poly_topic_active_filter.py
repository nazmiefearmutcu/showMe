"""POLY#3 regression: topic search must honour the active/closed status filters.

``/public-search`` ranks by relevance but does not apply Gamma's ``active``
flag, so an inactive, unclosed market could be reported as ``status=open``.
The HTTP client is a fake; no network is used.
"""

from __future__ import annotations

import asyncio

import httpx

import showme.providers._http as http_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.data_sources.alt.polymarket_adapter import search_markets_by_topic
from showme.engine.functions.misc.poly import POLYFunction


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _market(question, slug, *, active=True, closed=False):
    return {
        "id": slug,
        "slug": slug,
        "question": question,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.40", "0.60"]',
        "liquidity": "120000",
        "volume": "300000",
        "endDate": "2099-06-30T00:00:00Z",
        "active": active,
        "closed": closed,
        "umaResolutionStatus": None,
    }


_EVENTS = {
    "events": [
        {
            "title": "Fed",
            "endDate": "2099-06-30T00:00:00Z",
            "markets": [
                _market("Fed Decision in December?", "fed-active"),
                # Inactive but not closed: Gamma reports active=false.
                _market("Fed cuts in March?", "fed-inactive", active=False, closed=False),
                _market("Fed cuts rates in September?", "fed-closed", active=False, closed=True),
            ],
        },
    ],
    "pagination": {"hasMore": False, "totalResults": 1},
}


class _SearchClient:
    async def get(self, url, params=None, timeout=None):
        assert url.endswith("/public-search"), url
        return _Resp(_EVENTS)


def _patch_client(monkeypatch):
    client = _SearchClient()

    async def _get_client():
        return client

    monkeypatch.setattr(http_mod, "get_client", _get_client)


def _run(coro):
    return asyncio.run(coro)


def test_adapter_topic_search_drops_inactive_markets_when_active_is_requested():
    rows = _run(search_markets_by_topic(_SearchClient(), "fed", target=10, active=True, closed=False))
    slugs = {r["slug"] for r in rows}
    assert slugs == {"fed-active"}


def test_adapter_topic_search_without_status_flags_keeps_all_markets():
    rows = _run(search_markets_by_topic(_SearchClient(), "fed", target=10, active=None, closed=None))
    assert {r["slug"] for r in rows} == {"fed-active", "fed-inactive", "fed-closed"}


def test_open_status_topic_query_never_reports_an_inactive_unclosed_market(monkeypatch):
    _patch_client(monkeypatch)
    fn = POLYFunction(FunctionDeps())
    result = _run(fn.execute(query="fed", status="open", limit=10))
    questions = {m["question"] for m in result.data["markets"]}
    assert questions == {"Fed Decision in December?"}
    assert "Fed cuts in March?" not in questions


def test_open_status_guard_in_poly_drops_inactive_rows_from_any_source():
    # Even when a provider hands back an inactive, unclosed row, status=open must drop it.
    class _Adapter:
        async def search(self, query, **kwargs):
            return [
                _market("Inactive open-looking market", "inactive-x", active=False, closed=False),
                _market("Active market", "active-x"),
            ]

    fn = POLYFunction(FunctionDeps(polymarket=_Adapter()))
    result = _run(fn.execute(query="market", status="open", limit=10))
    questions = {m["question"] for m in result.data["markets"]}
    assert questions == {"Active market"}
