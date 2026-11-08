"""wc1-g41: Stooq API key must not leak into provider error text (SEC-1).

Offline: the HTTP layer is an httpx MockTransport.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from showme import chart_history


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── SEC-1: Stooq API key must not appear in provider error text ─────────


def test_stooq_http_error_does_not_leak_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "STOOQ-SECRET-KEY-9f3a"
    monkeypatch.setenv(chart_history.STOOQ_API_KEY_ENV, secret)
    real_client = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        assert secret in str(request.url), "the key is still sent to stooq (query string)"
        return httpx.Response(429, text="Too many requests")

    class _MockClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(_handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    with pytest.raises(RuntimeError) as info:
        _run(chart_history.fetch_stooq_history(
            symbol="AAPL", asset_class="EQUITY", interval="1d", days=365, bars=100,
        ))
    message = str(info.value)
    assert secret not in message
    assert "429" in message
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_stooq_transport_error_does_not_leak_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "STOOQ-SECRET-KEY-7c21"
    monkeypatch.setenv(chart_history.STOOQ_API_KEY_ENV, secret)
    real_client = httpx.AsyncClient

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused for {request.url}")

    class _MockClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(_handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    with pytest.raises(RuntimeError) as info:
        _run(chart_history.fetch_stooq_history(
            symbol="AAPL", asset_class="EQUITY", interval="1d", days=365, bars=100,
        ))
    assert secret not in str(info.value)
