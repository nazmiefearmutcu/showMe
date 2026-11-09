"""POLY — status=resolved filters a bounded Gamma window, and must say so.

The adapter pages through at most 400 closed markets (ordered by 24h volume)
and the resolved (UMA status) filter is applied client-side to that window.
When the window is saturated, resolved markets beyond it are not listed, so
the response must carry an explicit truncation warning and the scan size in
metadata instead of a silent ``status: ok``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from showme.engine.data_sources.alt.polymarket_adapter import PolymarketAdapter
from showme.engine.functions.misc.poly import POLYFunction


def _closed_market(i: int, *, resolved: bool) -> dict:
    return {
        "id": f"m{i}",
        "slug": f"m{i}",
        "question": f"Question {i}?",
        "closed": True,
        "active": True,
        "endDate": "2026-01-01T00:00:00Z",
        "liquidity": "1000",
        "volume": str(1_000_000 - i),
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["1", "0"]',
        "umaResolutionStatus": "resolved" if resolved else None,
    }


def _universe(total: int, resolved_at: int) -> list[dict]:
    return [_closed_market(i, resolved=(i == resolved_at)) for i in range(total)]


def _gamma_factory(universe: list[dict]):
    def _gamma(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        offset = int(params.get("offset", "0"))
        limit = int(params.get("limit", "100"))
        rows = universe
        if "closed" in params:
            wanted = params["closed"] == "true"
            rows = [r for r in rows if r["closed"] is wanted]
        return httpx.Response(200, json=rows[offset:offset + limit])

    return _gamma


def _run_resolved(universe: list[dict], limit: int = 100):
    async def run():
        adapter = PolymarketAdapter()
        async with httpx.AsyncClient(transport=httpx.MockTransport(_gamma_factory(universe))) as client:
            adapter._client = client
            return await POLYFunction(SimpleNamespace(polymarket=adapter)).execute(
                status="resolved", min_liquidity_usd=0, limit=limit
            )

    return asyncio.run(run())


def test_saturated_resolved_window_warns_and_reports_scan_size():
    # 450 closed markets; the only resolved one sits beyond the 400-row window.
    result = _run_resolved(_universe(total=450, resolved_at=420))

    assert result.data["status"] == "empty"
    assert result.data["markets"] == []
    assert result.metadata["resolved_scan_window"] == 400
    assert result.metadata["fetched"] == 400
    assert any("first 400" in w for w in result.warnings), result.warnings


def test_resolved_inside_window_is_listed_without_truncation_warning():
    result = _run_resolved(_universe(total=50, resolved_at=10))

    assert [m["slug"] for m in result.data["markets"]] == ["m10"]
    assert not any("first" in w and "closed markets" in w for w in result.warnings)
    assert result.metadata["fetched"] == 50
