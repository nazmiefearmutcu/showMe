import asyncio
import time
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from showme.engine.data_sources.news.gdelt_adapter import GDELTAdapter
from showme.engine.core.base_data_source import DataSourceError


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_cancel_shared_request():
    calls = []
    release = asyncio.Event()

    async def handle(request):
        calls.append(request)
        await release.wait()
        return httpx.Response(200, json={"articles": [{"title": "Fed", "url": "https://example.com/a"}]})

    adapter = GDELTAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    a = asyncio.create_task(adapter.search("inflation"))
    b = asyncio.create_task(adapter.search("inflation"))
    await asyncio.sleep(0.01)
    a.cancel()
    await asyncio.gather(a, return_exceptions=True)
    release.set()
    assert len(await b) == 1
    assert len(await adapter.search("inflation")) == 1
    assert len(calls) == 1
    await adapter.aclose()


@pytest.mark.asyncio
async def test_429_retry_after_prevents_next_network_request():
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    adapter = GDELTAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.search("inflation")
    assert adapter._next_request - time.monotonic() > 119
    with pytest.raises(DataSourceError, match="backoff"):
        await adapter.search("another")
    assert len(calls) == 1
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gal_ready_before_slow_doc_and_quality_filters():
    now = datetime.now(timezone.utc)
    stamp = format_datetime(now)
    release = asyncio.Event()
    rss = f'''<rss><channel>
    <item><title>Federal Reserve cuts interest rates</title><link>https://example.com/fed</link><pubDate>{stamp}</pubDate></item>
    <item><title>Federal Reserve cuts interest rates</title><link>https://example.com/fed</link><pubDate>{stamp}</pubDate></item>
    <item><title>Federal Reserve cuts interest rates</title><link>javascript:bad</link><pubDate>{stamp}</pubDate></item>
    <item><title>Federal Reserve cuts interest rates</title><link>https://example.com/undated</link></item>
    <item><title>Local bakery opens</title><link>https://example.com/noise</link><pubDate>{stamp}</pubDate></item>
    </channel></rss>'''

    async def handle(request):
        if request.url.host == "data.gdeltproject.org":
            return httpx.Response(200, text=rss)
        await release.wait()
        return httpx.Response(200, json={"articles": [{"title": "CPI inflation", "url": "https://example.com/cpi"}]})

    adapter = GDELTAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    rows, _, _ = await adapter.world_snapshot("inflation", now)
    assert rows == []
    for _ in range(100):
        if adapter._world_result[0]:
            break
        await asyncio.sleep(0.01)
    rows, source, note = await adapter.world_snapshot("inflation", now)
    assert len(rows) == 1
    assert source == "gdelt_gal"
    assert "language is not supplied" in note
    assert rows[0]["timestamp_basis"] == "provider_feed_time"
    release.set()
    await adapter._world_task
    rows, source, _ = await adapter.world_snapshot("inflation", now)
    assert len(rows) == 2
    assert source == "gdelt+gdelt_gal"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_close_cancels_background_network_tasks():
    async def handle(request):
        await asyncio.Event().wait()

    adapter = GDELTAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await adapter.world_snapshot("inflation", datetime.now(timezone.utc))
    await asyncio.sleep(0.01)
    await adapter.aclose()
    assert adapter._world_task is None
    assert not adapter._inflight


@pytest.mark.asyncio
async def test_distinct_requests_are_spaced_by_shared_gate():
    starts = []

    async def handle(request):
        starts.append(time.monotonic())
        return httpx.Response(200, json={"articles": []})

    adapter = GDELTAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await asyncio.gather(adapter.search("first"), adapter.search("second"))
    assert starts[1] - starts[0] >= 5
    await adapter.aclose()


@pytest.mark.asyncio
async def test_meet_uses_completed_background_snapshot_without_waiting(monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.comm.meet import MEETFunction

    adapter = GDELTAdapter()
    adapter._world_checked = time.monotonic()
    adapter._world_result = ([{"title": "Fed cuts rates", "url": "https://example.com/fed"}], "gdelt_gal", "language unknown")
    fn = MEETFunction(FunctionDeps(gdelt=adapter))
    rows, source, note = await fn._world_headlines(now=datetime.now(timezone.utc), timeout=2)
    assert len(rows) == 1 and source == "gdelt_gal"
    assert note == "language unknown"
    assert adapter._world_task is None


@pytest.mark.asyncio
async def test_meet_merges_rss_cache_with_new_gal_snapshot(monkeypatch):
    from showme.engine.core.base_function import FunctionDeps
    from showme.engine.functions.comm import meet

    monkeypatch.setattr(meet, "_WORLD_CACHE", (time.monotonic(),
        ([{"title": "RSS headline", "url": "https://example.com/rss"}], "rss", None), 60))
    adapter = GDELTAdapter()
    adapter._world_checked = time.monotonic()
    adapter._world_result = ([{"title": "GAL headline", "url": "https://example.com/gal"}], "gdelt_gal", None)
    fn = meet.MEETFunction(FunctionDeps(gdelt=adapter, rss=object()))
    rows, source, _ = await fn._world_headlines(now=datetime.now(timezone.utc), timeout=2)
    assert len(rows) == 2
    assert source == "rss+gdelt_gal"
