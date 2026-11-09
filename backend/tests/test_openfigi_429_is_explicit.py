"""ISIN#1 follow-up: OpenFIGI HTTP 429 must not look like "no match".

``lookup_by`` and ``lookup`` used to sleep one second and return ``[]`` / ``None``
on HTTP 429, which callers read as an ordinary empty result. They now raise
``OpenFIGIRateLimited`` (the same contract as ``lookup_batch``) so the caller can
report the identifier as unresolved.

No network: the HTTP client is a fake that always answers 429.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from showme.engine.data_sources.reference.openfigi_adapter import OpenFIGIAdapter, OpenFIGIRateLimited


class _Always429:
    async def post(self, url: str, json: Any = None, **_: Any) -> httpx.Response:  # noqa: A002
        request = httpx.Request("POST", f"https://api.openfigi.com/v3{url}")
        return httpx.Response(429, request=request, headers={"retry-after": "17"}, json={"error": "Too many requests"})


def _adapter() -> OpenFIGIAdapter:
    adapter = OpenFIGIAdapter()
    adapter.api_key = None
    adapter._client = _Always429()  # type: ignore[assignment]
    return adapter


def test_lookup_by_raises_on_429_instead_of_returning_empty() -> None:
    with pytest.raises(OpenFIGIRateLimited) as info:
        asyncio.run(_adapter().lookup_by(id_type="TICKER", id_value="AAPL"))
    assert info.value.retry_after == 17.0


def test_lookup_raises_on_429_instead_of_returning_none() -> None:
    with pytest.raises(OpenFIGIRateLimited) as info:
        asyncio.run(_adapter().lookup("AAPL"))
    assert info.value.retry_after == 17.0
