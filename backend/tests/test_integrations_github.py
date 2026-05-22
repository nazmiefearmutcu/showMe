"""GitHub search module tests with mocked httpx."""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from showme.integrations.github import CodeHit, search_code, _CACHE


@pytest.fixture(autouse=True)
def _clear_cache():
    _CACHE.clear()
    yield
    _CACHE.clear()


@pytest.mark.asyncio
async def test_returns_hits_on_success():
    body = {
        "items": [
            {"repository": {"full_name": "foo/bar"}, "path": "x.py",
             "html_url": "https://github.com/foo/bar/blob/x.py",
             "score": 42.0,
             "text_matches": [{"fragment": "def foo(): pass"}]},
        ]
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=body)
    async_client = MagicMock()
    async_client.get = AsyncMock(return_value=resp)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=None)
    with patch("showme.integrations.github.httpx.AsyncClient", return_value=async_client):
        hits = await search_code("rsi", language="python", limit=10)
    assert len(hits) == 1
    assert hits[0].repo == "foo/bar"
    assert "def foo" in hits[0].snippet
    assert isinstance(hits[0], CodeHit)


@pytest.mark.asyncio
async def test_returns_empty_on_non_200():
    resp = MagicMock(); resp.status_code = 403
    async_client = MagicMock()
    async_client.get = AsyncMock(return_value=resp)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=None)
    with patch("showme.integrations.github.httpx.AsyncClient", return_value=async_client):
        hits = await search_code("anything")
    assert hits == []


@pytest.mark.asyncio
async def test_returns_empty_on_exception():
    async_client = MagicMock()
    async_client.get = AsyncMock(side_effect=RuntimeError("network"))
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=None)
    with patch("showme.integrations.github.httpx.AsyncClient", return_value=async_client):
        hits = await search_code("anything")
    assert hits == []


@pytest.mark.asyncio
async def test_cache_hit_skips_network():
    body = {"items": [{"repository": {"full_name": "a/b"}, "path": "x",
                       "html_url": "u", "score": 1, "text_matches": []}]}
    resp = MagicMock(); resp.status_code = 200; resp.json = MagicMock(return_value=body)
    async_client = MagicMock()
    async_client.get = AsyncMock(return_value=resp)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=None)
    with patch("showme.integrations.github.httpx.AsyncClient", return_value=async_client):
        await search_code("rsi")
        # Second call — cached:
        hits = await search_code("rsi")
    assert async_client.get.call_count == 1
    assert len(hits) == 1
