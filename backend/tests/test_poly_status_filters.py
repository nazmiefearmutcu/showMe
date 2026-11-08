"""POLY — status filters must match what Gamma actually returns.

Gamma's ``closed`` query flag is a hard filter. ``status=all`` must not send
``closed=true`` (that silently drops every open market), and ``status=resolved``
must select markets whose ``umaResolutionStatus`` is ``resolved`` — ``closed``
alone does not imply resolution. The Gamma stand-in below honours the
``closed`` / ``active`` / ``offset`` parameters the way the live endpoint does.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from showme.engine.data_sources.alt.polymarket_adapter import PolymarketAdapter
from showme.engine.functions.misc.poly import POLYFunction


def _market(slug, *, closed, resolved=False, end="2099-01-01T00:00:00Z"):
    return {
        "id": slug,
        "slug": slug,
        "question": f"Question {slug}?",
        "closed": closed,
        "active": True,
        "endDate": end,
        "liquidity": "50000",
        "volume": "90000",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.6", "0.4"]',
        "umaResolutionStatus": "resolved" if resolved else None,
    }


UNIVERSE = [
    _market("open-one", closed=False),
    _market("closed-resolved", closed=True, resolved=True, end="2026-01-01T00:00:00Z"),
    _market("closed-unresolved", closed=True, resolved=False, end="2026-02-01T00:00:00Z"),
]


def _gamma(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if int(params.get("offset", "0")) > 0:
        return httpx.Response(200, json=[])
    rows = list(UNIVERSE)
    if "closed" in params:
        wanted = params["closed"] == "true"
        rows = [r for r in rows if r["closed"] is wanted]
    if "active" in params:
        rows = [r for r in rows if r["active"] is True]
    return httpx.Response(200, json=rows)


def _run_status(status):
    async def run():
        adapter = PolymarketAdapter()
        async with httpx.AsyncClient(transport=httpx.MockTransport(_gamma)) as client:
            adapter._client = client
            result = await POLYFunction(SimpleNamespace(polymarket=adapter)).execute(
                status=status, min_liquidity_usd=0
            )
        return result

    return asyncio.run(run())


def _slugs(result):
    return {m["slug"] for m in result.data["markets"]}


def test_status_all_returns_open_and_closed_markets():
    result = _run_status("all")
    assert _slugs(result) == {"open-one", "closed-resolved", "closed-unresolved"}


def test_status_open_still_excludes_closed_markets():
    result = _run_status("open")
    assert _slugs(result) == {"open-one"}


def test_status_closed_returns_only_closed_markets():
    result = _run_status("closed")
    assert _slugs(result) == {"closed-resolved", "closed-unresolved"}


def test_status_resolved_requires_uma_resolution_not_just_closed():
    result = _run_status("resolved")
    assert _slugs(result) == {"closed-resolved"}
    assert all(m["resolved"] is True for m in result.data["markets"])
    assert all(m["closed"] is True for m in result.data["markets"])
