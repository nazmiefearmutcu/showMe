import asyncio
from types import SimpleNamespace

import httpx

from showme.engine.data_sources.alt.polymarket_adapter import PolymarketAdapter
from showme.engine.functions.misc.poly import POLYFunction


def market(i, liquidity=20000):
    return {"id": str(i), "slug": f"market-{i}", "question": f"Question {i}",
            "closed": False, "active": True, "endDate": "2099-01-01T00:00:00Z",
            "liquidity": liquidity, "volume": 100000 - i,
            "outcomes": '["Yes", "No"]', "outcomePrices": '["0.6", "0.4"]'}


def test_adapter_pages_and_pushes_filters_before_limit():
    requests = []

    def respond(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json=[market(i) for i in range(offset, offset + 100)])

    async def run():
        adapter = PolymarketAdapter()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter._client = client
            result = await POLYFunction(SimpleNamespace(polymarket=adapter)).execute(
                status="open", min_liquidity_usd=10000)
            assert len(result.data["markets"]) == 100
            assert len(result.data["rows"]) == 200
        assert [int(r.url.params["offset"]) for r in requests] == [0, 100, 200, 300]
        for r in requests:
            assert r.url.params["closed"] == "false"
            assert r.url.params["liquidity_num_min"] == "10000.0"
            assert "end_date_min" in r.url.params

    asyncio.run(run())


def test_filtering_does_not_discard_later_pages():
    class Adapter:
        async def search(self, *args, **kwargs):
            return [market(i, 1) for i in range(100)] + [market(i) for i in range(100, 200)]

    result = asyncio.run(POLYFunction(SimpleNamespace(polymarket=Adapter())).execute(
        min_liquidity_usd=10000))
    assert len(result.data["markets"]) == 100
    assert all(m["liquidity"] >= 10000 for m in result.data["markets"])


def test_repeated_provider_page_stops_without_duplicate_markets():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=[market(i) for i in range(100)])

    async def run():
        adapter = PolymarketAdapter()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter._client = client
            rows = await adapter.search(limit=400)
        assert len(rows) == 100
        assert len(calls) == 2

    asyncio.run(run())
